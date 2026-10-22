"""Index.md parsing, skill auditing, and atomic completion engine."""

import difflib
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import yaml

from skill_manager.core.scanner import parse_yaml_frontmatter
from skill_manager.models import AuditResult


DEFAULT_REQUIRED_FIELDS = ["name", "description"]
DEFAULT_REQUIRED_SECTIONS = ["When to Use", "Instructions"]
DEFAULT_RECOMMENDED_DIRS = ["scripts", "references"]


class IndexSchemaError(Exception):
    """Raised when index.md is invalid or cannot be parsed."""
    pass


def parse_index_schema(index_path: Path) -> Dict[str, Any]:
    """Parse index.md or specification guide to extract required sections and structure."""
    if not index_path.exists() or not index_path.is_file():
        raise FileNotFoundError(f"Index file not found: {index_path}")

    try:
        content = index_path.read_text(encoding="utf-8")
    except Exception as e:
        raise IndexSchemaError(f"Cannot read index file: {e}") from e

    if not content.strip():
        raise IndexSchemaError("INVALID_INDEX_SCHEMA: unable to parse section headers from index.md")

    # Match markdown headings (e.g. ## Heading)
    headers = re.findall(r"^#{1,3}\s+(.+)$", content, flags=re.MULTILINE)
    if not headers:
        raise IndexSchemaError("INVALID_INDEX_SCHEMA: unable to parse section headers from index.md")

    required_sections: List[str] = []
    # Identify headings that represent required sections
    for h in headers:
        clean_h = h.strip()
        # Common skill sections
        for target in ("When to Use", "Instructions", "Overview", "Examples", "References"):
            if target.lower() in clean_h.lower() and target not in required_sections:
                required_sections.append(target)

    if not required_sections:
        required_sections = list(DEFAULT_REQUIRED_SECTIONS)

    return {
        "required_fields": list(DEFAULT_REQUIRED_FIELDS),
        "required_sections": required_sections,
        "recommended_dirs": list(DEFAULT_RECOMMENDED_DIRS),
    }


def audit_skill(skill_dir: Path, index_path: Optional[Path] = None) -> AuditResult:
    """Audit target skill directory against index.md specifications."""
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise FileNotFoundError(f"Target skill directory not found: {skill_dir}")

    # Check if directory has any files
    entries = list(skill_dir.iterdir())
    if not entries:
        raise ValueError("TARGET_DIR_EMPTY: Directory contains no files.")

    # Determine schema
    schema = {
        "required_fields": DEFAULT_REQUIRED_FIELDS,
        "required_sections": DEFAULT_REQUIRED_SECTIONS,
        "recommended_dirs": DEFAULT_RECOMMENDED_DIRS,
    }

    if index_path and index_path.exists():
        schema = parse_index_schema(index_path)

    skill_md = skill_dir / "SKILL.md"
    missing_fields: List[str] = []
    missing_sections: List[str] = []
    missing_dirs: List[str] = []

    # Check recommended subdirectories
    for d_name in schema.get("recommended_dirs", DEFAULT_RECOMMENDED_DIRS):
        sub_d = skill_dir / d_name
        if not sub_d.exists() or not sub_d.is_dir():
            missing_dirs.append(d_name)

    if not skill_md.exists():
        missing_fields = list(schema["required_fields"])
        missing_sections = list(schema["required_sections"])
        diff = generate_skeleton_skill_md(
            skill_name=skill_dir.name,
            missing_fields=missing_fields,
            missing_sections=missing_sections,
            original_content="",
        )
        return AuditResult(
            is_compliant=False,
            missing_fields=missing_fields,
            missing_sections=missing_sections,
            missing_dirs=missing_dirs,
            diff_content=diff,
            details={"has_skill_md": False},
        )

    # Parse existing SKILL.md
    meta, body = parse_yaml_frontmatter(skill_md)

    for field in schema.get("required_fields", DEFAULT_REQUIRED_FIELDS):
        if field not in meta or not str(meta[field]).strip():
            missing_fields.append(field)

    # Check sections in body
    existing_headings = re.findall(r"^#{1,3}\s+(.+)$", body, flags=re.MULTILINE)
    existing_headings_clean = [h.strip().lower() for h in existing_headings]

    for sec in schema.get("required_sections", DEFAULT_REQUIRED_SECTIONS):
        if not any(sec.lower() in eh for eh in existing_headings_clean):
            missing_sections.append(sec)

    is_compliant = (len(missing_fields) == 0 and len(missing_sections) == 0 and len(missing_dirs) == 0)

    diff_content = ""
    if not is_compliant:
        original_text = skill_md.read_text(encoding="utf-8", errors="replace")
        diff_content = generate_skeleton_skill_md(
            skill_name=meta.get("name") or skill_dir.name,
            missing_fields=missing_fields,
            missing_sections=missing_sections,
            original_content=original_text,
        )

    return AuditResult(
        is_compliant=is_compliant,
        missing_fields=missing_fields,
        missing_sections=missing_sections,
        missing_dirs=missing_dirs,
        diff_content=diff_content,
        details={"existing_fields": list(meta.keys())},
    )


def generate_skeleton_skill_md(
    skill_name: str,
    missing_fields: List[str],
    missing_sections: List[str],
    original_content: str,
) -> str:
    """Generate proposed content and compute Unified Diff."""
    lines = original_content.splitlines(keepends=True)

    # If original content is empty, build from scratch
    if not lines:
        new_content = [
            "---\n",
            f"name: {skill_name}\n",
            f"description: Skill description for {skill_name}\n",
            "---\n\n",
            f"# {skill_name}\n\n",
        ]
        for sec in missing_sections:
            new_content.append(f"## {sec}\n\nAdd details here.\n\n")
        completed_text = "".join(new_content)
    else:
        # Append missing sections to existing content
        new_content = list(lines)
        if not new_content[-1].endswith("\n"):
            new_content[-1] += "\n"
        new_content.append("\n")

        for sec in missing_sections:
            new_content.append(f"## {sec}\n\nAdd details here.\n\n")
        completed_text = "".join(new_content)

    orig_lines = original_content.splitlines(keepends=True)
    comp_lines = completed_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        comp_lines,
        fromfile="SKILL.md (current)",
        tofile="SKILL.md (completed)",
    )
    return "".join(diff)


def complete_skill(
    skill_dir: Path,
    index_path: Optional[Path] = None,
    dry_run: bool = True,
) -> Tuple[bool, str, List[str]]:
    """Complete missing sections and directories in target skill.
    
    Returns (success, diff_string, list_of_modified_files).
    """
    audit = audit_skill(skill_dir, index_path=index_path)
    if audit.is_compliant:
        return True, "", []

    modified_files: List[str] = []
    skill_md = skill_dir / "SKILL.md"

    # Compute target content
    original_text = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
    meta, _ = parse_yaml_frontmatter(skill_md) if skill_md.exists() else ({}, "")

    skill_name = meta.get("name") or skill_dir.name
    diff_text = generate_skeleton_skill_md(
        skill_name=skill_name,
        missing_fields=audit.missing_fields,
        missing_sections=audit.missing_sections,
        original_content=original_text,
    )

    if dry_run:
        # Dry-run: do not modify disk
        return True, diff_text, [str(skill_md)]

    # Actual modification with atomic write
    try:
        # 1. Create missing directories (with CWE-22 Path Traversal guard)
        resolved_root = skill_dir.resolve()
        for d in audit.missing_dirs:
            target_sub = (skill_dir / d).resolve()
            if not target_sub.is_relative_to(resolved_root):
                raise ValueError(f"PATH_TRAVERSAL_BLOCKED: '{d}' escapes skill root directory")
            target_sub.mkdir(parents=True, exist_ok=True)
            keep_file = target_sub / ".gitkeep"
            if not keep_file.exists():
                keep_file.write_text("", encoding="utf-8")
                modified_files.append(str(keep_file))

        # 2. Complete SKILL.md using atomic write
        # Generate completed text
        if not original_text:
            completed_text = (
                f"---\nname: {skill_name}\ndescription: Auto-generated description for {skill_name}\n---\n\n"
                f"# {skill_name}\n\n"
            )
            for sec in audit.missing_sections:
                completed_text += f"## {sec}\n\nAdd details here.\n\n"
        else:
            completed_text = original_text
            if not completed_text.endswith("\n"):
                completed_text += "\n"
            completed_text += "\n"
            for sec in audit.missing_sections:
                completed_text += f"## {sec}\n\nAdd details here.\n\n"

        tmp_file = skill_dir / f"SKILL.md.tmp.{os.getpid()}"
        tmp_file.write_text(completed_text, encoding="utf-8")
        # Atomic replacement
        tmp_file.replace(skill_md)
        modified_files.append(str(skill_md))

        return True, diff_text, modified_files
    except PermissionError as pe:
        raise PermissionError(f"WRITE_PERMISSION_DENIED: {skill_dir}") from pe

