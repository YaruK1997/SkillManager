"""Unit tests for versioning module (FR-04)."""

import os
from pathlib import Path
import git
import pytest
from skill_manager.core.versioning import (
    DirtyWorktreeError,
    GitVersionError,
    check_version_status,
    rollback_skill,
    upgrade_skill,
)
from skill_manager.models import VersionStatus


@pytest.mark.r1
def test_t_r1_ac_04_01_behind_status(git_repo_with_remote, temp_dir):
    """T-R1-AC-04-01 (Source: AC-04-01): Detect BEHIND status when remote has new commits."""
    local_repo_dir, bare_remote_dir = git_repo_with_remote

    # Clone another repo to simulate remote updates
    sim_dir = temp_dir / "sim_repo"
    sim_repo = git.Repo.clone_from(str(bare_remote_dir), str(sim_dir))
    (sim_dir / "NEW.md").write_text("remote update", encoding="utf-8")
    sim_repo.index.add(["NEW.md"])
    sim_repo.index.commit("Remote commit 1")
    sim_repo.git.push("origin", "main")

    # Local checks status
    status = check_version_status(local_repo_dir)
    assert status.version_status == VersionStatus.BEHIND
    assert status.behind_count == 1


@pytest.mark.r1
def test_t_r1_ac_04_02_and_03_upgrade_and_rollback(git_repo_with_remote, temp_dir):
    """T-R1-AC-04-02 / T-R1-AC-04-03 (Source: AC-04-02, AC-04-03): Upgrade creates backup tag, rollback restores commit."""
    local_repo_dir, bare_remote_dir = git_repo_with_remote

    local_repo = git.Repo(local_repo_dir)
    initial_sha = local_repo.head.commit.hexsha

    # Push remote update
    sim_dir = temp_dir / "sim_repo_2"
    sim_repo = git.Repo.clone_from(str(bare_remote_dir), str(sim_dir))
    (sim_dir / "UPDATE.md").write_text("new content", encoding="utf-8")
    sim_repo.index.add(["UPDATE.md"])
    sim_repo.index.commit("Remote commit 2")
    sim_repo.git.push("origin", "main")
    remote_sha = sim_repo.head.commit.hexsha

    # Perform upgrade
    res_up = upgrade_skill(local_repo_dir)
    assert res_up.version_status == VersionStatus.UP_TO_DATE
    assert res_up.local_commit == remote_sha

    # Verify backup tag was created
    backup_tags = [t.name for t in local_repo.tags if t.name.startswith("backup-pre-upgrade-")]
    assert len(backup_tags) == 1

    # Perform rollback
    res_down = rollback_skill(local_repo_dir)
    assert res_down.local_commit == initial_sha


@pytest.mark.r2
def test_t_r2_ac_04_04_dirty_worktree_guard(git_repo_with_remote):
    """T-R2-AC-04-04 (Source: AC-04-04): Upgrade fails when uncommitted changes exist."""
    local_repo_dir, _ = git_repo_with_remote

    # Create uncommitted dirty file
    (local_repo_dir / "dirty_file.txt").write_text("dirty content", encoding="utf-8")

    with pytest.raises(DirtyWorktreeError, match="DIRTY_WORKTREE_DETECTED"):
        upgrade_skill(local_repo_dir, force=False)


@pytest.mark.r2
def test_t_r2_ec_04_01_untracked_directory(temp_dir):
    """T-R2-EC-04-01 (Source: EC-04-01): Non-git directory raises GitVersionError."""
    plain_dir = temp_dir / "plain_dir"
    plain_dir.mkdir()

    with pytest.raises(GitVersionError, match="UNTRACKED"):
        check_version_status(plain_dir)

