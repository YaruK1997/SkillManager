"""Local skills directory scanner with cross-platform platform detection."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple
import yaml

from skill_manager.config import AppConfig, resolve_platform_paths
from skill_manager.models import (
    PlatformType,
    ScanResult,
    ScanSummary,
    SkillEntity,
    VersionStatus,
)


def parse_yaml_frontmatter(file_path: Path) -> Tuple[Dict[str, Any], str]:
    """Extract YAML frontmatter and body from a markdown file.
    
    Returns (metadata_dict, body_string).
    """
    if not file_path.exists() or not file_path.is_file():
        return {}, ""

    try:
        # Guard against huge binary or abnormal files (> 50 MB)
        if file_path.stat().st_size > 50 * 1024 * 1024:
            return {}, ""

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if not lines or lines[0].strip() != "---":
            # No YAML frontmatter header
            return {}, "".join(lines)

        yaml_lines = []
        body_start = 1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
            yaml_lines.append(lines[i])
        else:
            # Closing delimiter not found
            return {}, "".join(lines)

        yaml_content = "".join(yaml_lines)
        try:
            parsed = yaml.safe_load(yaml_content) or {}
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception as ye:
            sys.stderr.write(f"[WARN] Failed parsing YAML frontmatter in {file_path}: {ye}\n")
            parsed = {}

        body = "".join(lines[body_start:])
        return parsed, body
    except Exception as e:
        sys.stderr.write(f"[WARN] Failed parsing YAML frontmatter in {file_path}: {e}\n")
        return {}, ""


def inspect_single_skill(dir_path: Path, platform: PlatformType) -> Optional[SkillEntity]:
    """Inspect a directory to determine if it is a valid skill and extract its metadata."""
    try:
        skill_md = dir_path / "SKILL.md"
        plugin_json = dir_path / "plugin.json"

        has_skill_md = skill_md.exists() and skill_md.is_file()
        has_plugin_json = plugin_json.exists() and plugin_json.is_file()

        if not has_skill_md and not has_plugin_json:
            return None

        yaml_meta: Dict[str, Any] = {}
        description = ""
        name = dir_path.name

        if has_skill_md:
            yaml_meta, _ = parse_yaml_frontmatter(skill_md)
            if "name" in yaml_meta and yaml_meta["name"]:
                name = str(yaml_meta["name"]).strip()
            if "description" in yaml_meta and yaml_meta["description"]:
                description = str(yaml_meta["description"]).strip()

        has_scripts = (dir_path / "scripts").is_dir()
        has_references = (dir_path / "references").is_dir()

        # Check git status if directory is a git repository
        git_dir = dir_path / ".git"
        commit_sha = None
        upstream_url = None
        version_status = VersionStatus.UNTRACKED

        if git_dir.exists():
            try:
                import git
                repo = git.Repo(dir_path)
                if not repo.bare and repo.head.is_valid():
                    commit_sha = repo.head.commit.hexsha
                    if repo.remotes:
                        upstream_url = repo.remotes.origin.url if "origin" in repo.remotes else list(repo.remotes)[0].url
                        version_status = VersionStatus.UP_TO_DATE
            except Exception:
                pass

        return SkillEntity(
            id=dir_path.name,
            name=name,
            description=description,
            platform=platform,
            path=str(dir_path.resolve()),
            has_skill_md=has_skill_md,
            has_scripts=has_scripts,
            has_references=has_references,
            yaml_metadata=yaml_meta,
            version_status=version_status,
            commit_sha=commit_sha,
            upstream_url=upstream_url,
        )
    except PermissionError:
        sys.stderr.write(f"ACCESS_DENIED: {dir_path}\n")
        return None
    except Exception as e:
        sys.stderr.write(f"[WARN] Error inspecting skill at {dir_path}: {e}\n")
        return None


def scan_directory_tree(
    root_dir: Path,
    platform: PlatformType,
    max_depth: int = 3,
    visited_realpaths: Optional[Set[str]] = None,
) -> Iterator[SkillEntity]:
    """Walk directory using os.scandir with depth limit and circular symlink protection."""
    if visited_realpaths is None:
        visited_realpaths = set()

    try:
        real_root = str(root_dir.resolve())
        if real_root in visited_realpaths:
            # Prevent circular symlink loops
            sys.stderr.write(f"[WARN] Circular symlink detected at {root_dir}, skipping.\n")
            return
        visited_realpaths.add(real_root)

        if not root_dir.exists() or not root_dir.is_dir():
            return

        # Check if the root directory itself is a skill
        self_skill = inspect_single_skill(root_dir, platform)
        if self_skill:
            yield self_skill
            return

        # Queue of (current_dir, current_depth)
        queue: List[Tuple[Path, int]] = [(root_dir, 1)]

        while queue:
            curr_dir, depth = queue.pop(0)
            if depth > max_depth:
                continue

            try:
                with os.scandir(curr_dir) as entries:
                    for entry in entries:
                        try:
                            if not entry.is_dir(follow_symlinks=True):
                                continue

                            entry_path = Path(entry.path)
                            # Skip common hidden and ignored directories
                            if entry.name.startswith(".") or entry.name in ("__pycache__", "node_modules", "venv"):
                                continue

                            # Circular symlink protection check
                            real_entry = str(entry_path.resolve())
                            if real_entry in visited_realpaths:
                                continue
                            visited_realpaths.add(real_entry)

                            # Test if entry is a skill
                            skill = inspect_single_skill(entry_path, platform)
                            if skill:
                                yield skill
                            elif depth < max_depth:
                                queue.append((entry_path, depth + 1))
                        except (PermissionError, FileNotFoundError):
                            continue
            except PermissionError:
                sys.stderr.write(f"ACCESS_DENIED: {curr_dir}\n")
            except FileNotFoundError:
                continue

    except PermissionError:
        sys.stderr.write(f"ACCESS_DENIED: {root_dir}\n")
    except Exception as e:
        sys.stderr.write(f"[WARN] Failed scanning {root_dir}: {e}\n")


def scan_skills(
    platform: PlatformType = PlatformType.ALL,
    custom_paths: Optional[List[str]] = None,
    max_depth: int = 3,
    config: Optional[AppConfig] = None,
) -> ScanResult:
    """Scan all designated local paths and gather SkillEntity records."""
    target_paths = resolve_platform_paths(platform=platform, custom_paths=custom_paths, config=config)
    found_skills: List[SkillEntity] = []
    visited_realpaths: Set[str] = set()
    total_dirs_scanned = 0

    for path in target_paths:
        if not path.exists():
            sys.stderr.write(f"PATH_NOT_FOUND: {path}\n")
            continue

        total_dirs_scanned += 1
        # Infer platform ecosystem from path if platform was ALL
        inferred_platform = platform
        if platform == PlatformType.ALL:
            path_str = str(path).lower()
            if ".claude" in path_str:
                inferred_platform = PlatformType.CLAUDE
            elif ".gemini" in path_str or "antigravity" in path_str:
                inferred_platform = PlatformType.ANTIGRAVITY
            elif "codex" in path_str or "copilot" in path_str:
                inferred_platform = PlatformType.CODEX
            elif "cursor" in path_str:
                inferred_platform = PlatformType.CURSOR
            else:
                inferred_platform = PlatformType.UNIVERSAL

        for skill in scan_directory_tree(
            root_dir=path,
            platform=inferred_platform,
            max_depth=max_depth,
            visited_realpaths=visited_realpaths,
        ):
            found_skills.append(skill)

    # Deduplicate by absolute path
    deduped: List[SkillEntity] = []
    seen_paths = set()
    for s in found_skills:
        if s.path not in seen_paths:
            seen_paths.add(s.path)
            deduped.append(s)

    summary = ScanSummary(
        total_scanned=total_dirs_scanned,
        valid_skills=len(deduped),
        invalid_skills=0,
    )

    return ScanResult(skills=deduped, summary=summary)

