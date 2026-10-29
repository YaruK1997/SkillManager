"""Git and HuggingFace skill version control, sync, snapshot, and rollback engine."""

import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional
import git

from skill_manager.models import TrackResult, VersionStatus

_SAFE_REF_PATTERN = re.compile(r"^[a-zA-Z0-9_./\-]+$")


def _validate_git_ref(ref: str) -> str:
    """Validate git reference string against argument injection (CWE-88)."""
    cleaned = ref.strip()
    if not cleaned or cleaned.startswith("-") or ".." in cleaned or not _SAFE_REF_PATTERN.match(cleaned):
        raise GitVersionError(f"INVALID_GIT_REF: Potentially unsafe git reference '{ref}'")
    return cleaned


class GitVersionError(Exception):
    """Base exception for version control operations."""
    pass


class DirtyWorktreeError(GitVersionError):
    """Raised when uncommitted changes prevent safe upgrade."""
    pass


class GitNetworkTimeoutError(GitVersionError):
    """Raised when git fetch or remote communication times out."""
    pass


def get_git_repo(skill_dir: Path) -> git.Repo:
    """Load Git repository or raise error if untracked."""
    if not (skill_dir / ".git").exists():
        raise GitVersionError(f"UNTRACKED: directory is not a git repository: {skill_dir}")

    try:
        return git.Repo(skill_dir)
    except Exception as e:
        raise GitVersionError(f"GIT_CORRUPT: Failed loading repository at {skill_dir}: {e}") from e


def check_version_status(skill_dir: Path, fetch_remote: bool = True) -> TrackResult:
    """Inspect local git repository and compare with remote tracking branch."""
    repo = get_git_repo(skill_dir)
    try:
        if not repo.head.is_valid():
            return TrackResult(
                skill_name=skill_dir.name,
                skill_path=str(skill_dir.resolve()),
                version_status=VersionStatus.UNTRACKED,
            )

        local_commit = repo.head.commit.hexsha

        if not repo.remotes:
            return TrackResult(
                skill_name=skill_dir.name,
                skill_path=str(skill_dir.resolve()),
                version_status=VersionStatus.UNTRACKED,
                local_commit=local_commit,
            )

        remote = repo.remotes.origin if "origin" in repo.remotes else list(repo.remotes)[0]

        if fetch_remote:
            try:
                remote.fetch(kill_after_timeout=15)
            except Exception as e:
                sys.stderr.write(f"[WARN] Failed to fetch remote for {skill_dir.name}: {e}\n")
                return TrackResult(
                    skill_name=skill_dir.name,
                    skill_path=str(skill_dir.resolve()),
                    version_status=VersionStatus.NETWORK_TIMEOUT,
                    local_commit=local_commit,
                )

        # Determine remote tracking branch
        active_branch_name = repo.active_branch.name if not repo.head.is_detached else "main"
        remote_ref = None

        for ref in remote.refs:
            if ref.name.endswith(f"/{active_branch_name}"):
                remote_ref = ref
                break

        if not remote_ref and remote.refs:
            # Fallback to first remote reference
            remote_ref = list(remote.refs)[0]

        if not remote_ref:
            return TrackResult(
                skill_name=skill_dir.name,
                skill_path=str(skill_dir.resolve()),
                version_status=VersionStatus.UP_TO_DATE,
                local_commit=local_commit,
            )

        remote_commit = remote_ref.commit.hexsha

        if local_commit == remote_commit:
            return TrackResult(
                skill_name=skill_dir.name,
                skill_path=str(skill_dir.resolve()),
                version_status=VersionStatus.UP_TO_DATE,
                local_commit=local_commit,
                remote_commit=remote_commit,
                behind_count=0,
            )

        # Calculate commits behind / ahead
        try:
            behind_commits = list(repo.iter_commits(f"{local_commit}..{remote_commit}"))
            ahead_commits = list(repo.iter_commits(f"{remote_commit}..{local_commit}"))

            behind_count = len(behind_commits)
            ahead_count = len(ahead_commits)

            if behind_count > 0 and ahead_count == 0:
                status = VersionStatus.BEHIND
            elif ahead_count > 0 and behind_count == 0:
                status = VersionStatus.AHEAD
            else:
                status = VersionStatus.DIVERGED

            diff_summary = f"{behind_count} behind, {ahead_count} ahead"

            return TrackResult(
                skill_name=skill_dir.name,
                skill_path=str(skill_dir.resolve()),
                version_status=status,
                local_commit=local_commit,
                remote_commit=remote_commit,
                behind_count=behind_count,
                diff_summary=diff_summary,
            )
        except Exception as e:
            sys.stderr.write(f"[WARN] Diff calculation error: {e}\n")
            return TrackResult(
                skill_name=skill_dir.name,
                skill_path=str(skill_dir.resolve()),
                version_status=VersionStatus.DIVERGED,
                local_commit=local_commit,
                remote_commit=remote_commit,
            )
    finally:
        try:
            repo.close()
        except Exception:
            pass


def upgrade_skill(
    skill_dir: Path,
    target_ref: Optional[str] = None,
    force: bool = False,
) -> TrackResult:
    """Safely upgrade a skill to remote reference, creating a snapshot tag beforehand."""
    if target_ref is not None:
        _validate_git_ref(target_ref)

    repo = get_git_repo(skill_dir)
    try:
        # Check for uncommitted dirty changes
        if (repo.is_dirty() or len(repo.untracked_files) > 0) and not force:
            raise DirtyWorktreeError("DIRTY_WORKTREE_DETECTED: stash or commit local changes before upgrading")

        # Create safety backup tag
        timestamp = int(time.time())
        backup_tag_name = f"backup-pre-upgrade-{timestamp}"
        repo.create_tag(backup_tag_name, message=f"Automatic backup before upgrading at {timestamp}", force=True)

        if not repo.remotes:
            raise GitVersionError(f"UNTRACKED: repository has no remote upstream configured in {skill_dir}")

        remote = repo.remotes.origin if "origin" in repo.remotes else list(repo.remotes)[0]
        try:
            remote.fetch(kill_after_timeout=15)
        except Exception as e:
            raise GitVersionError(f"NETWORK_TIMEOUT: failed to fetch remote for {skill_dir.name}: {e}")

        active_branch_name = repo.active_branch.name if not repo.head.is_detached else "main"
        ref_to_checkout = _validate_git_ref(target_ref or f"{remote.name}/{active_branch_name}")
        try:
            repo.git.reset("--hard", ref_to_checkout)
        except git.exc.GitCommandError as ge:
            raise GitVersionError(f"GIT_RESET_FAILED: {ge}")

        return check_version_status(skill_dir, fetch_remote=False)
    finally:
        try:
            repo.close()
        except Exception:
            pass


def rollback_skill(
    skill_dir: Path,
    tag_name: Optional[str] = None,
) -> TrackResult:
    """Roll back local repository to previous backup tag."""
    repo = get_git_repo(skill_dir)
    try:
        target_tag = tag_name
        if not target_tag:
            # Find latest backup-pre-upgrade-* tag
            backup_tags = [t for t in repo.tags if t.name.startswith("backup-pre-upgrade-")]
            if not backup_tags:
                raise GitVersionError(f"No previous backup tag found for rollback in {skill_dir}")
            # Sort by tag commit date or timestamp
            backup_tags.sort(key=lambda t: t.commit.committed_date, reverse=True)
            target_tag = backup_tags[0].name

        safe_tag = _validate_git_ref(target_tag)
        try:
            repo.git.reset("--hard", safe_tag)
        except git.exc.GitCommandError as ge:
            raise GitVersionError(f"GIT_ROLLBACK_FAILED: {ge}")
        return check_version_status(skill_dir, fetch_remote=False)
    finally:
        try:
            repo.close()
        except Exception:
            pass

