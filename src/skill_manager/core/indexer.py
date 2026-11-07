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


def strip_markdown_code_blocks(text: str) -> str:
    """Remove fenced code blocks and HTML comments from markdown text."""
    # Remove fenced code blocks (``` or ~~~) even if unclosed at EOF
    cleaned = re.sub(r"(?ms)^[ \t]*(```|~~~).*?(?:^\1[ \t]*$|\Z)", "", text)
    # Remove HTML comments
    cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
    return cleaned


def extract_markdown_headings(text: str) -> List[str]:
    """Extract clean markdown heading titles (ATX headings # to ###), stripping code blocks."""
    clean_text = strip_markdown_code_blocks(text)
    raw_headings = re.findall(r"^[ \t]*#{1,3}[ \t]+(.+?)[ \t]*#*[ \t]*$", clean_text, flags=re.MULTILINE)
    cleaned = []
    for h in raw_headings:
        # Strip markdown formatting like **bold**, *italic*, `code`, [links](...)
        t = re.sub(r"\*\*([^*]+)\*\*", r"\1", h)
        t = re.sub(r"\*([^*]+)\*", r"\1", t)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
        t = t.strip()
        if t:
            cleaned.append(t)
    return cleaned


def is_section_matching(target_sec: str, existing_heading: str) -> bool:
    """Check if an existing heading matches target_sec with high precision."""
    sec_norm = target_sec.strip().lower()
    head_norm = existing_heading.strip().lower()

    # Exact match after normalization
    if head_norm == sec_norm:
        return True

    # Reject headings starting with negative qualifiers (e.g. "not instructions", "no instructions")
    if re.search(r"\b(not|no|without|unrelated|anti)\b", head_norm):
        return False

    # Check for word boundary matching, e.g. "Detailed Instructions" or "Instructions (Usage)"
    pattern = rf"\b{re.escape(sec_norm)}\b"
    return bool(re.search(pattern, head_norm))


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

    # Match markdown headings (excluding code blocks)
    headers = extract_markdown_headings(content)
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


def audit_skill(
    skill_dir: Path,
    index_path: Optional[Path] = None,
    allow_empty: bool = False,
) -> AuditResult:
    """Audit target skill directory against index.md specifications."""
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise FileNotFoundError(f"Target skill directory not found: {skill_dir}")

    # Determine schema first so it is available for empty dir or existing dir
    schema = {
        "required_fields": DEFAULT_REQUIRED_FIELDS,
        "required_sections": DEFAULT_REQUIRED_SECTIONS,
        "recommended_dirs": DEFAULT_RECOMMENDED_DIRS,
    }
    if index_path and index_path.exists():
        schema = parse_index_schema(index_path)

    # Check if directory has any files
    entries = list(skill_dir.iterdir())
    if not entries:
        if not allow_empty:
            raise ValueError("TARGET_DIR_EMPTY: Directory contains no files.")
        # When allow_empty=True, treat empty directory as fully missing for completion
        missing_fields = list(schema["required_fields"])
        missing_sections = list(schema["required_sections"])
        missing_dirs = list(schema.get("recommended_dirs", DEFAULT_RECOMMENDED_DIRS))
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
            details={"has_skill_md": False, "is_empty_dir": True},
        )

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

    # Check sections in body using code-block stripped headings and precise matching
    existing_headings = extract_markdown_headings(body)

    for sec in schema.get("required_sections", DEFAULT_REQUIRED_SECTIONS):
        if not any(is_section_matching(sec, eh) for eh in existing_headings):
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


def build_completed_skill_md(
    original_content: str,
    skill_name: str,
    missing_fields: List[str],
    missing_sections: List[str],
) -> str:
    """Build completed SKILL.md content, intelligently patching frontmatter and appending missing sections."""
    lines = original_content.splitlines(keepends=True)
    if not lines or not original_content.strip():
        # Completely new file
        res = [
            "---\n",
            f"name: {skill_name}\n",
            f"description: Skill description for {skill_name}\n",
            "---\n\n",
            f"# {skill_name}\n\n",
        ]
        for sec in missing_sections:
            res.append(f"## {sec}\n\nAdd details here.\n\n")
        return "".join(res)

    # Check if file starts with YAML frontmatter delimiter
    has_frontmatter = lines[0].strip() == "---"
    closing_idx = -1
    if has_frontmatter:
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                closing_idx = idx
                break

    if not has_frontmatter or closing_idx == -1:
        # File has NO valid frontmatter header -> Prepend frontmatter
        fm_lines = ["---\n"]
        name_val = skill_name
        desc_val = f"Skill description for {skill_name}"
        fm_lines.append(f"name: {name_val}\n")
        fm_lines.append(f"description: {desc_val}\n")
        for field in missing_fields:
            if field not in ("name", "description"):
                fm_lines.append(f"{field}: Auto-completed {field}\n")
        fm_lines.append("---\n\n")

        new_content = fm_lines + list(lines)
    else:
        # File has frontmatter: lines[0] is opening '---', lines[closing_idx] is closing '---'
        # Patch or insert missing fields inside frontmatter
        fm_inner = list(lines[1:closing_idx])
        for field in missing_fields:
            val = skill_name if field == "name" else f"Skill description for {skill_name}"
            target_line = f"{field}: {val}\n"
            # Check if field key exists in frontmatter (e.g. empty or whitespace value)
            for i, l in enumerate(fm_inner):
                if re.match(rf"^\s*{re.escape(field)}\s*:", l):
                    fm_inner[i] = target_line
                    break
            else:
                # Append before closing delimiter
                fm_inner.append(target_line)

        new_content = [lines[0]] + fm_inner + list(lines[closing_idx:])

    # Handle missing sections in body
    if missing_sections:
        if not new_content[-1].endswith("\n"):
            new_content[-1] += "\n"
        new_content.append("\n")
        for sec in missing_sections:
            new_content.append(f"## {sec}\n\nAdd details here.\n\n")

    return "".join(new_content)


def generate_skeleton_skill_md(
    skill_name: str,
    missing_fields: List[str],
    missing_sections: List[str],
    original_content: str,
) -> str:
    """Generate proposed content and compute Unified Diff."""
    completed_text = build_completed_skill_md(
        original_content=original_content,
        skill_name=skill_name,
        missing_fields=missing_fields,
        missing_sections=missing_sections,
    )

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
    allow_empty: bool = True,
) -> Tuple[bool, str, List[str]]:
    """Complete missing sections and directories in target skill.
    
    Returns (success, diff_string, list_of_modified_files).
    """
    audit = audit_skill(skill_dir, index_path=index_path, allow_empty=allow_empty)
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
        completed_text = build_completed_skill_md(
            original_content=original_text,
            skill_name=skill_name,
            missing_fields=audit.missing_fields,
            missing_sections=audit.missing_sections,
        )

        tmp_file = skill_dir / f"SKILL.md.tmp.{os.getpid()}"
        try:
            tmp_file.write_text(completed_text, encoding="utf-8")
            # Atomic replacement
            tmp_file.replace(skill_md)
            modified_files.append(str(skill_md))
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

        return True, diff_text, modified_files
    except PermissionError as pe:
        raise PermissionError(f"WRITE_PERMISSION_DENIED: {skill_dir}") from pe
