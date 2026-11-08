"""Skill execution mode controller and global policy master switch."""

from __future__ import annotations

import os
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from skill_manager.models import (
    SkillEntity,
    SkillExecutionMode,
    GlobalPolicyMode,
    PlatformType,
)
from skill_manager.events import (
    SkillModeChangedEvent,
    GlobalPolicyChangedEvent,
)


def get_default_config_path() -> Path:
    """Return default configuration path for SkillManager."""
    return Path.home() / ".config" / "skill-manager" / "config.toml"


def get_skill_mode_from_frontmatter(metadata: Dict[str, Any]) -> SkillExecutionMode:
    """Determine execution mode from parsed YAML frontmatter."""
    activation = str(metadata.get("activation", "")).strip().lower()
    always_apply = metadata.get("alwaysApply")

    if activation == "resident" or always_apply is True or str(always_apply).lower() == "true":
        return SkillExecutionMode.RESIDENT
    return SkillExecutionMode.ON_DEMAND


def get_skill_mode(skill_dir: Path | str) -> SkillExecutionMode:
    """Inspect SKILL.md in directory and return current execution mode."""
    skill_path = Path(skill_dir)
    skill_md = skill_path / "SKILL.md"
    if not skill_md.is_file():
        return SkillExecutionMode.ON_DEMAND

    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception:
        return SkillExecutionMode.ON_DEMAND

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return SkillExecutionMode.ON_DEMAND

    try:
        metadata = yaml.safe_load(match.group(1)) or {}
        if isinstance(metadata, dict):
            return get_skill_mode_from_frontmatter(metadata)
    except Exception:
        pass
    return SkillExecutionMode.ON_DEMAND


def _atomic_write_file(path: Path, content: str) -> None:
    """Atomically write content to file using a .tmp file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def update_frontmatter_mode(content: str, target_mode: SkillExecutionMode, fallback_name: str = "") -> str:
    """
    Safely update or inject activation and alwaysApply in SKILL.md frontmatter.
    Preserves all existing body content and unrelated frontmatter fields.
    """
    activation_val = "resident" if target_mode == SkillExecutionMode.RESIDENT else "on_demand"
    always_apply_val = "true" if target_mode == SkillExecutionMode.RESIDENT else "false"

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        body = fm_match.group(2)

        # Replace or add activation
        if re.search(r"^activation:\s*.*$", fm_text, flags=re.MULTILINE):
            fm_text = re.sub(r"^activation:\s*.*$", f"activation: {activation_val}", fm_text, flags=re.MULTILINE)
        else:
            fm_text = f"{fm_text}\nactivation: {activation_val}"

        # Replace or add alwaysApply
        if re.search(r"^alwaysApply:\s*.*$", fm_text, flags=re.MULTILINE):
            fm_text = re.sub(r"^alwaysApply:\s*.*$", f"alwaysApply: {always_apply_val}", fm_text, flags=re.MULTILINE)
        else:
            fm_text = f"{fm_text}\nalwaysApply: {always_apply_val}"

        return f"---\n{fm_text.strip()}\n---\n\n{body.lstrip()}"
    else:
        # No frontmatter present -> prepend new frontmatter
        name_str = fallback_name or "unnamed-skill"
        header = (
            f"---\n"
            f"name: {name_str}\n"
            f"description: \"\"\n"
            f"activation: {activation_val}\n"
            f"alwaysApply: {always_apply_val}\n"
            f"---\n\n"
        )
        return header + content.lstrip()


def load_config_toml(config_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Read config.toml into a nested dict."""
    p = Path(config_path) if config_path else get_default_config_path()
    if not p.is_file():
        return {}
    try:
        import tomllib
        with p.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def save_config_toml(data: Dict[str, Any], config_path: Optional[Path | str] = None) -> None:
    """Serialize and atomically save dict as simple TOML."""
    p = Path(config_path) if config_path else get_default_config_path()
    lines: List[str] = []

    # Write root scalars first
    for k, v in data.items():
        if not isinstance(v, dict):
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            elif v is None:
                continue
            else:
                lines.append(f'{k} = "{v}"')

    # Write tables
    for section, subdict in data.items():
        if isinstance(subdict, dict):
            lines.append(f"\n[{section}]")
            for sk, sv in subdict.items():
                if isinstance(sv, bool):
                    lines.append(f"{sk} = {str(sv).lower()}")
                elif isinstance(sv, (int, float)):
                    lines.append(f"{sk} = {sv}")
                elif sv is None:
                    continue
                else:
                    lines.append(f'{sk} = "{sv}"')

    content = "\n".join(lines).strip() + "\n"
    _atomic_write_file(p, content)


def toggle_skill_mode(
    skill_path: Path | str,
    target_mode: SkillExecutionMode | str,
    config_path: Optional[Path | str] = None,
) -> SkillModeChangedEvent:
    """
    Toggle or explicitly set execution mode for a single skill.
    Updates SKILL.md frontmatter atomically and records preference in config.toml.
    """
    skill_dir = Path(skill_path)
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill directory not found: {skill_dir}")

    mode_enum = SkillExecutionMode(target_mode) if isinstance(target_mode, str) else target_mode
    old_mode = get_skill_mode(skill_dir)
    skill_md = skill_dir / "SKILL.md"

    if skill_md.is_file():
        original_content = skill_md.read_text(encoding="utf-8")
    else:
        original_content = f"# {skill_dir.name}\n\nSkill instructions and usage.\n"

    new_content = update_frontmatter_mode(original_content, mode_enum, fallback_name=skill_dir.name)
    _atomic_write_file(skill_md, new_content)

    # Update config.toml record
    cfg = load_config_toml(config_path)
    skill_modes = cfg.setdefault("skill_modes", {})
    skill_modes[skill_dir.name] = mode_enum.value
    try:
        save_config_toml(cfg, config_path)
    except Exception:
        pass

    return SkillModeChangedEvent(
        skill_name=skill_dir.name,
        platform="universal",
        old_mode=old_mode,
        new_mode=mode_enum,
        skill_path=str(skill_dir.resolve()),
        success=True,
    )


def apply_global_policy(
    policy: GlobalPolicyMode | str,
    skills: List[SkillEntity],
    platform: Optional[PlatformType | str] = None,
    config_path: Optional[Path | str] = None,
) -> GlobalPolicyChangedEvent:
    """
    Apply global execution policy across skills (ALL_RESIDENT, ALL_ON_DEMAND, or CUSTOM).
    Saves snapshot of individual preferences before switching to global modes;
    restores snapshot when switching back to CUSTOM.
    """
    pol_enum = GlobalPolicyMode(policy) if isinstance(policy, str) else policy
    if isinstance(platform, Enum):
        target_platform = platform.value.lower()
    elif platform:
        target_platform = str(platform).lower()
    else:
        target_platform = "all"

    # Filter target skills
    matching_skills = [
        s for s in skills
        if target_platform in ("all", "universal") or s.platform.value == target_platform
    ]

    cfg = load_config_toml(config_path)
    snapshot = cfg.get("skill_modes_snapshot", {})

    modified_backups: Dict[Path, str] = {}
    affected_count = 0

    try:
        if pol_enum == GlobalPolicyMode.ALL_RESIDENT:
            # Capture current states into snapshot
            new_snapshot = {s.name: get_skill_mode(s.path).value for s in matching_skills}
            cfg["skill_modes_snapshot"] = new_snapshot
            cfg["global_policy"] = GlobalPolicyMode.ALL_RESIDENT.value
            save_config_toml(cfg, config_path)

            for s in matching_skills:
                p = Path(s.path)
                md = p / "SKILL.md"
                if md.is_file():
                    modified_backups[md] = md.read_text(encoding="utf-8")
                toggle_skill_mode(p, SkillExecutionMode.RESIDENT, config_path)
                affected_count += 1

        elif pol_enum == GlobalPolicyMode.ALL_ON_DEMAND:
            # Capture current states into snapshot
            new_snapshot = {s.name: get_skill_mode(s.path).value for s in matching_skills}
            cfg["skill_modes_snapshot"] = new_snapshot
            cfg["global_policy"] = GlobalPolicyMode.ALL_ON_DEMAND.value
            save_config_toml(cfg, config_path)

            for s in matching_skills:
                p = Path(s.path)
                md = p / "SKILL.md"
                if md.is_file():
                    modified_backups[md] = md.read_text(encoding="utf-8")
                toggle_skill_mode(p, SkillExecutionMode.ON_DEMAND, config_path)
                affected_count += 1

        elif pol_enum == GlobalPolicyMode.CUSTOM:
            cfg["global_policy"] = GlobalPolicyMode.CUSTOM.value
            save_config_toml(cfg, config_path)

            for s in matching_skills:
                saved_mode_str = snapshot.get(s.name)
                if saved_mode_str:
                    target_m = SkillExecutionMode(saved_mode_str)
                    p = Path(s.path)
                    md = p / "SKILL.md"
                    if md.is_file():
                        modified_backups[md] = md.read_text(encoding="utf-8")
                    toggle_skill_mode(p, target_m, config_path)
                    affected_count += 1

        return GlobalPolicyChangedEvent(
            policy=pol_enum,
            affected_count=affected_count,
            snapshot_path=str(config_path) if config_path else None,
            success=True,
        )

    except Exception as exc:
        # Transactional rollback on error
        for file_path, original_txt in modified_backups.items():
            try:
                _atomic_write_file(file_path, original_txt)
            except Exception:
                pass
        return GlobalPolicyChangedEvent(
            policy=pol_enum,
            affected_count=0,
            snapshot_path=str(config_path) if config_path else None,
            success=False,
            error_message=str(exc),
        )
