"""Workflow specification parser, skill requirement auditor, and startup auto-completer."""

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from skill_manager.config import AppConfig
from skill_manager.core.indexer import audit_skill, complete_skill
from skill_manager.core.scanner import scan_skills
from skill_manager.models import (
    PlatformType,
    WorkflowAuditResult,
    WorkflowCompleteResult,
    WorkflowSkillRequirement,
    WorkflowSkillStatus,
)

# Standard skill alias mappings
SKILL_ALIASES = {
    "tdd": "test-driven-development",
    "pwg": "PWG",
}

MAX_WORKFLOW_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


class WorkflowAuditError(Exception):
    """Base exception for workflow audit operations."""
    pass


def find_default_workflow_file(start_dir: Optional[Path] = None) -> Optional[Path]:
    """Auto-detect workflow specification file in current workspace."""
    base = (start_dir or Path.cwd()).resolve()
    candidates = [
        base / "workflow.md",
        base / "WORKFLOW.md",
        base / ".agents" / "workflow.md",
        base / "docs" / "workflow.md",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def parse_workflow_requirements(workflow_path: Path) -> List[str]:
    """Parse workflow.md to extract required skill names and identifiers.
    
    Raises:
        FileNotFoundError: If workflow file does not exist.
        ValueError: If file exceeds size limit or is unreadable.
    """
    if not workflow_path.exists() or not workflow_path.is_file():
        raise FileNotFoundError(f"ERR_WORKFLOW_NOT_FOUND: {workflow_path}")

    # Check file size (EC-06-02)
    file_size = workflow_path.stat().st_size
    if file_size > MAX_WORKFLOW_FILE_SIZE:
        raise ValueError(f"WORKFLOW_FILE_TOO_LARGE: file size ({file_size} bytes) exceeds 5MB limit")

    if file_size == 0:
        return []

    try:
        content = workflow_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        sys.stderr.write(f"[WARN] Error reading workflow file: {e}\n")
        return []

    required_skills: List[str] = []
    seen: Set[str] = set()

    def add_skill(name: str):
        cleaned = name.strip().strip("`*\"'#()[]:").strip()
        # Remove trailing extensions or paths if any
        if cleaned.endswith(".md"):
            cleaned = Path(cleaned).stem
        if "/" in cleaned or "\\" in cleaned:
            cleaned = Path(cleaned).name
            if cleaned.upper() == "SKILL":
                cleaned = Path(name).parent.name

        cleaned = cleaned.strip("`*\"'#()[]:").strip()
        # Ensure valid skill identifier (ASCII alphanumeric and hyphens/underscores)
        if not re.match(r"^[a-zA-Z0-9_\-]+$", cleaned):
            return
        # Skip pure digits/ordinals like 1, 2, 3
        if cleaned.replace("-", "").replace("_", "").isdigit():
            return

        canon = SKILL_ALIASES.get(cleaned.lower(), cleaned)
        if canon and len(canon) >= 2 and canon not in seen:
            # Exclude markdown syntax or non-skill words
            if canon.lower() not in ("skills", "skill", "plugins", "plugin", "skill.md", "http", "https"):
                seen.add(canon)
                required_skills.append(canon)

    # Pattern 1: Path references like `skills/<skill-name>/SKILL.md` or `skills/<skill-name>/`
    path_matches = re.findall(r"skills/([a-zA-Z0-9_\-]+)(?:/SKILL\.md|/)?", content, flags=re.IGNORECASE)
    for m in path_matches:
        add_skill(m)

    # Pattern 2: Binding mentions like `綁定技能：...` or `調用技能 (Skills Allocation)`
    binding_lines = re.findall(r"(?:綁定技能|調用技能|Global Meta Skills)[^:\n]*[：:]\s*([^\n\r]+)", content)
    for line in binding_lines:
        # Split by comma, semicolon, space, or slashes
        tokens = re.split(r"[,;、\s]+", line)
        for tok in tokens:
            cleaned = re.sub(r"\(.*?\)", "", tok).strip()
            if cleaned:
                add_skill(cleaned)

    # Pattern 3: Table items matching markdown table rows with skill mentions
    # e.g., | **using-superpowers** | `skills/using-superpowers/SKILL.md` |
    table_matches = re.findall(r"\|\s*\*\*([a-zA-Z0-9_\-]+)\*\*\s*\|\s*`?(?:skills/)?([a-zA-Z0-9_\-]+)", content)
    for m1, m2 in table_matches:
        add_skill(m1)
        if m2 and m2 != m1:
            add_skill(m2)

    return required_skills


def find_skill_in_sources(skill_name: str, source_dirs: List[Path]) -> Optional[Path]:
    """Search for an existing skill directory within candidate source directories."""
    canon_name = SKILL_ALIASES.get(skill_name.lower(), skill_name)

    for src in source_dirs:
        if not src.exists() or not src.is_dir():
            continue

        # 1. Direct subfolder
        direct = src / canon_name
        if direct.exists() and direct.is_dir():
            return direct

        direct_raw = src / skill_name
        if direct_raw.exists() and direct_raw.is_dir():
            return direct_raw

        # 2. Search one or two levels deep
        try:
            for entry in src.iterdir():
                if entry.is_dir():
                    if entry.name.lower() in (canon_name.lower(), skill_name.lower()):
                        return entry
                    sub_match = entry / canon_name
                    if sub_match.exists() and sub_match.is_dir():
                        return sub_match
        except PermissionError:
            continue

    return None


def audit_workflow_skills(
    workflow_path: Optional[Path] = None,
    platform: PlatformType = PlatformType.ALL,
    custom_paths: Optional[List[str]] = None,
    config: Optional[AppConfig] = None,
) -> WorkflowAuditResult:
    """Audit local skills against workflow specifications.
    
    Raises:
        FileNotFoundError: If workflow file cannot be located.
        ValueError: If workflow file is too large.
    """
    target_workflow = workflow_path
    if not target_workflow:
        target_workflow = find_default_workflow_file()
        if not target_workflow:
            raise FileNotFoundError("ERR_WORKFLOW_NOT_FOUND: workflow.md not found in workspace")

    target_workflow = target_workflow.resolve()
    required_skill_names = parse_workflow_requirements(target_workflow)

    # Scan local skills
    scan_res = scan_skills(platform=platform, custom_paths=custom_paths, config=config)

    # Build local lookup map (by name and id)
    local_skills_map: Dict[str, Any] = {}
    for s in scan_res.skills:
        local_skills_map[s.name.lower()] = s
        local_skills_map[s.id.lower()] = s

    audit_items: List[WorkflowSkillRequirement] = []
    installed_count = 0
    missing_count = 0
    incomplete_count = 0

    for name in required_skill_names:
        lookup_key = name.lower()
        canon_lookup = SKILL_ALIASES.get(lookup_key, lookup_key)

        matched_entity = local_skills_map.get(lookup_key) or local_skills_map.get(canon_lookup)

        if matched_entity:
            skill_dir = Path(matched_entity.path)
            # Audit structural completeness of this installed skill
            try:
                sub_audit = audit_skill(skill_dir)
                if sub_audit.is_compliant:
                    status = WorkflowSkillStatus.INSTALLED
                    installed_count += 1
                    missing_secs = []
                    missing_dirs = []
                else:
                    status = WorkflowSkillStatus.INCOMPLETE
                    incomplete_count += 1
                    missing_secs = sub_audit.missing_sections
                    missing_dirs = sub_audit.missing_dirs
            except Exception:
                status = WorkflowSkillStatus.INSTALLED
                installed_count += 1
                missing_secs = []
                missing_dirs = []

            audit_items.append(
                WorkflowSkillRequirement(
                    name=name,
                    status=status,
                    installed_path=str(skill_dir),
                    description=matched_entity.description or "",
                    missing_sections=missing_secs,
                    missing_dirs=missing_dirs,
                )
            )
        else:
            status = WorkflowSkillStatus.MISSING
            missing_count += 1
            audit_items.append(
                WorkflowSkillRequirement(
                    name=name,
                    status=status,
                    installed_path=None,
                    missing_sections=[],
                    missing_dirs=[],
                )
            )

    is_satisfied = (len(required_skill_names) > 0 and missing_count == 0 and incomplete_count == 0)

    return WorkflowAuditResult(
        workflow_path=str(target_workflow),
        total_required=len(required_skill_names),
        installed_count=installed_count,
        missing_count=missing_count,
        incomplete_count=incomplete_count,
        is_fully_satisfied=is_satisfied,
        skills=audit_items,
    )


def complete_workflow_skills(
    audit_result: WorkflowAuditResult,
    target_dir: Optional[Path] = None,
    skill_sources: Optional[List[Path]] = None,
    dry_run: bool = True,
) -> WorkflowCompleteResult:
    """Auto-complete missing or incomplete workflow skills.
    
    If source skill directory is found in skill_sources, copy it.
    Otherwise, generate standard compliant SKILL.md skeleton and directories.
    """
    # Determine target destination directory for missing skills
    dest_dir = target_dir
    if not dest_dir:
        # Default destination: .agents/skills in current workspace
        dest_dir = Path.cwd() / ".agents" / "skills"
    dest_dir = dest_dir.resolve()

    # Determine candidate source directories
    candidate_sources: List[Path] = list(skill_sources or [])
    default_sources = [
        Path.cwd() / "skill-packs",
        Path.cwd() / "skills",
        dest_dir,
    ]
    for d in default_sources:
        if d.exists() and d not in candidate_sources:
            candidate_sources.append(d)

    completed_skills: List[str] = []
    created_skeletons: List[str] = []
    modified_files: List[str] = []
    diff_snippets: List[str] = []

    for req in audit_result.skills:
        if req.status == WorkflowSkillStatus.INSTALLED:
            continue

        skill_name = req.name

        if req.status == WorkflowSkillStatus.MISSING:
            # Check candidate sources
            found_src = find_skill_in_sources(skill_name, candidate_sources)

            target_skill_path = dest_dir / skill_name
            if found_src and found_src.resolve() != target_skill_path.resolve():
                # Copy from source
                diff_snippets.append(f"--- [COPY] {skill_name}\n+++ from {found_src} -> {target_skill_path}\n")
                if not dry_run:
                    try:
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(found_src, target_skill_path, dirs_exist_ok=True)
                        modified_files.append(str(target_skill_path))
                        completed_skills.append(skill_name)
                    except PermissionError as pe:
                        raise PermissionError(f"WRITE_PERMISSION_DENIED: {target_skill_path}") from pe
                else:
                    completed_skills.append(skill_name)
                    modified_files.append(str(target_skill_path))
            else:
                # Generate skeleton
                diff_snippets.append(f"--- [SKELETON] {skill_name}\n+++ create {target_skill_path}/SKILL.md\n")
                if not dry_run:
                    try:
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        target_skill_path.mkdir(parents=True, exist_ok=True)
                        # Write initial SKILL.md so indexer engine can audit and complete missing sections/subdirs
                        skill_md = target_skill_path / "SKILL.md"
                        initial_content = (
                            f"---\nname: {skill_name}\ndescription: Auto-generated skill for {skill_name}\n---\n\n"
                            f"# {skill_name}\n\n"
                        )
                        skill_md.write_text(initial_content, encoding="utf-8")
                        ok, diff_t, mods = complete_skill(target_skill_path, dry_run=False)
                        if ok:
                            created_skeletons.append(skill_name)
                            completed_skills.append(skill_name)
                            if str(skill_md) not in mods:
                                mods.append(str(skill_md))
                            modified_files.extend(mods)
                            if diff_t:
                                diff_snippets.append(diff_t)
                    except PermissionError as pe:
                        raise PermissionError(f"WRITE_PERMISSION_DENIED: {target_skill_path}") from pe
                else:
                    created_skeletons.append(skill_name)
                    completed_skills.append(skill_name)
                    modified_files.append(str(target_skill_path / "SKILL.md"))

        elif req.status == WorkflowSkillStatus.INCOMPLETE and req.installed_path:
            # Complete missing sections/dirs in existing skill
            skill_path = Path(req.installed_path)
            diff_snippets.append(f"--- [COMPLETE] {skill_name} at {skill_path}\n")
            if not dry_run:
                try:
                    ok, diff_t, mods = complete_skill(skill_path, dry_run=False)
                    if ok:
                        completed_skills.append(skill_name)
                        modified_files.extend(mods)
                        if diff_t:
                            diff_snippets.append(diff_t)
                except PermissionError as pe:
                    raise PermissionError(f"WRITE_PERMISSION_DENIED: {skill_path}") from pe
            else:
                ok, diff_t, mods = complete_skill(skill_path, dry_run=True)
                completed_skills.append(skill_name)
                modified_files.extend(mods)
                if diff_t:
                    diff_snippets.append(diff_t)

    diff_summary = "".join(diff_snippets) if diff_snippets else None

    return WorkflowCompleteResult(
        success=True,
        dry_run=dry_run,
        completed_skills=completed_skills,
        created_skeletons=created_skeletons,
        modified_files=modified_files,
        diff_summary=diff_summary,
    )
