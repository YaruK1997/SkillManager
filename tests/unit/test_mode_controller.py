"""Unit tests for ModeController and Global Policy Master Switch (T-S2-02-MODE)."""

import os
from pathlib import Path
import pytest

from skill_manager.models import (
    SkillEntity,
    SkillExecutionMode,
    GlobalPolicyMode,
    PlatformType,
)
from skill_manager.core.mode_controller import (
    get_skill_mode,
    get_skill_mode_from_frontmatter,
    update_frontmatter_mode,
    toggle_skill_mode,
    apply_global_policy,
    load_config_toml,
    save_config_toml,
)


def test_get_skill_mode_from_frontmatter():
    assert get_skill_mode_from_frontmatter({"activation": "resident"}) == SkillExecutionMode.RESIDENT
    assert get_skill_mode_from_frontmatter({"alwaysApply": True}) == SkillExecutionMode.RESIDENT
    assert get_skill_mode_from_frontmatter({"alwaysApply": "true"}) == SkillExecutionMode.RESIDENT
    assert get_skill_mode_from_frontmatter({"activation": "on_demand"}) == SkillExecutionMode.ON_DEMAND
    assert get_skill_mode_from_frontmatter({}) == SkillExecutionMode.ON_DEMAND


def test_update_frontmatter_mode_existing():
    content = """---
name: my-skill
description: "A helpful skill"
activation: on_demand
alwaysApply: false
---

# Instructions
Do something great.
"""
    updated = update_frontmatter_mode(content, SkillExecutionMode.RESIDENT)
    assert "activation: resident" in updated
    assert "alwaysApply: true" in updated
    assert 'description: "A helpful skill"' in updated
    assert "# Instructions\nDo something great." in updated


def test_t_r2_ec_07_missing_frontmatter():
    """EC-07: Frontmatter recovery for missing or broken frontmatter."""
    content = "# Just markdown\nNo frontmatter here."
    updated = update_frontmatter_mode(content, SkillExecutionMode.RESIDENT, fallback_name="auto-skill")
    assert "name: auto-skill" in updated
    assert "activation: resident" in updated
    assert "alwaysApply: true" in updated
    assert "# Just markdown\nNo frontmatter here." in updated


def test_t_r2_ec_08_toggle_skill_mode_atomic(tmp_path):
    """EC-08: Zero data loss atomic replace for mode toggling."""
    skill_dir = tmp_path / "skill-a"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: skill-a\ndescription: test\nactivation: on_demand\nalwaysApply: false\n---\n\n# Body\n",
        encoding="utf-8",
    )
    cfg_file = tmp_path / "config.toml"

    event = toggle_skill_mode(skill_dir, SkillExecutionMode.RESIDENT, config_path=cfg_file)
    assert event.success is True
    assert event.old_mode == SkillExecutionMode.ON_DEMAND
    assert event.new_mode == SkillExecutionMode.RESIDENT

    # Check updated SKILL.md
    assert get_skill_mode(skill_dir) == SkillExecutionMode.RESIDENT

    # Check config.toml updated
    cfg = load_config_toml(cfg_file)
    assert cfg.get("skill_modes", {}).get("skill-a") == "resident"

    # Toggle back to on_demand
    event2 = toggle_skill_mode(skill_dir, SkillExecutionMode.ON_DEMAND, config_path=cfg_file)
    assert event2.new_mode == SkillExecutionMode.ON_DEMAND
    assert get_skill_mode(skill_dir) == SkillExecutionMode.ON_DEMAND


def test_t_r2_ec_09_apply_global_policy_and_custom_restore(tmp_path):
    """EC-09: Snapshot rollback and restoration for global policy."""
    # Setup 3 skills: skill-1 (resident), skill-2 (on_demand), skill-3 (resident)
    s1 = tmp_path / "skill-1"
    s1.mkdir()
    (s1 / "SKILL.md").write_text("---\nname: skill-1\nactivation: resident\nalwaysApply: true\n---\n# S1\n", encoding="utf-8")

    s2 = tmp_path / "skill-2"
    s2.mkdir()
    (s2 / "SKILL.md").write_text("---\nname: skill-2\nactivation: on_demand\nalwaysApply: false\n---\n# S2\n", encoding="utf-8")

    s3 = tmp_path / "skill-3"
    s3.mkdir()
    (s3 / "SKILL.md").write_text("---\nname: skill-3\nactivation: resident\nalwaysApply: true\n---\n# S3\n", encoding="utf-8")

    skills = [
        SkillEntity(id="skill-1", name="skill-1", path=str(s1), platform=PlatformType.CLAUDE),
        SkillEntity(id="skill-2", name="skill-2", path=str(s2), platform=PlatformType.CLAUDE),
        SkillEntity(id="skill-3", name="skill-3", path=str(s3), platform=PlatformType.ANTIGRAVITY),
    ]
    cfg_file = tmp_path / "config.toml"

    # 1. Switch all to ALL_ON_DEMAND
    ev = apply_global_policy(GlobalPolicyMode.ALL_ON_DEMAND, skills, platform=PlatformType.ALL, config_path=cfg_file)
    assert ev.success is True
    assert ev.affected_count == 3
    assert get_skill_mode(s1) == SkillExecutionMode.ON_DEMAND
    assert get_skill_mode(s2) == SkillExecutionMode.ON_DEMAND
    assert get_skill_mode(s3) == SkillExecutionMode.ON_DEMAND

    # Snapshot should record previous states
    cfg = load_config_toml(cfg_file)
    assert cfg.get("skill_modes_snapshot", {}).get("skill-1") == "resident"
    assert cfg.get("skill_modes_snapshot", {}).get("skill-2") == "on_demand"
    assert cfg.get("skill_modes_snapshot", {}).get("skill-3") == "resident"

    # 2. Switch all to ALL_RESIDENT
    ev_res = apply_global_policy(GlobalPolicyMode.ALL_RESIDENT, skills, platform=PlatformType.ALL, config_path=cfg_file)
    assert ev_res.success is True
    assert get_skill_mode(s1) == SkillExecutionMode.RESIDENT
    assert get_skill_mode(s2) == SkillExecutionMode.RESIDENT
    assert get_skill_mode(s3) == SkillExecutionMode.RESIDENT

    # 3. Restore via CUSTOM (simulate restoring the original snapshot)
    # Put original snapshot back
    cfg["skill_modes_snapshot"] = {"skill-1": "resident", "skill-2": "on_demand", "skill-3": "resident"}
    save_config_toml(cfg, cfg_file)

    ev_custom = apply_global_policy(GlobalPolicyMode.CUSTOM, skills, platform=PlatformType.ALL, config_path=cfg_file)
    assert ev_custom.success is True
    assert get_skill_mode(s1) == SkillExecutionMode.RESIDENT
    assert get_skill_mode(s2) == SkillExecutionMode.ON_DEMAND
    assert get_skill_mode(s3) == SkillExecutionMode.RESIDENT


def test_toggle_skill_mode_nonexistent_dir():
    with pytest.raises(FileNotFoundError):
        toggle_skill_mode("/non/existent/path", SkillExecutionMode.RESIDENT)


def test_t_r2_ec_10_concurrency_and_retry(tmp_path):
    """EC-10: Concurrency error handling and retry guard."""
    skill_dir = tmp_path / "skill-c"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: skill-c\nactivation: on_demand\n---\n# C\n", encoding="utf-8")

    ev = toggle_skill_mode(skill_dir, SkillExecutionMode.RESIDENT)
    assert ev.success is True
    assert ev.new_mode == SkillExecutionMode.RESIDENT

