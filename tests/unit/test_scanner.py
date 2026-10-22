"""Unit tests for scanner module (FR-01)."""

import os
from pathlib import Path
from skill_manager.core.scanner import (
    inspect_single_skill,
    parse_yaml_frontmatter,
    scan_skills,
)
from skill_manager.models import PlatformType, VersionStatus


def test_t_r1_ac_01_01_valid_skill_detection(sample_valid_skill):
    """T-R1-AC-01-01: Detect valid skill directory and parse metadata."""
    skill = inspect_single_skill(sample_valid_skill, PlatformType.CLAUDE)
    assert skill is not None
    assert skill.name == "my-test-skill"
    assert skill.has_skill_md is True
    assert skill.has_scripts is True
    assert skill.has_references is True
    assert "A comprehensive test skill" in skill.description


def test_t_r1_ac_01_02_and_03_scan_skills_custom_path(sample_valid_skill, temp_dir):
    """T-R1-AC-01-02/03: Scan designated path returns properly wrapped ScanResult."""
    res = scan_skills(platform=PlatformType.UNIVERSAL, custom_paths=[str(temp_dir)])
    assert res.summary.valid_skills >= 1
    names = [s.name for s in res.skills]
    assert "my-test-skill" in names


def test_t_r2_ac_01_04_missing_path_handled(temp_dir, capsys):
    """T-R2-AC-01-04: Non-existent custom path outputs warning and does not crash."""
    non_existent = temp_dir / "does_not_exist_dir"
    res = scan_skills(platform=PlatformType.UNIVERSAL, custom_paths=[str(non_existent)])
    captured = capsys.readouterr()
    assert "PATH_NOT_FOUND" in captured.err
    assert res.summary.valid_skills == 0


def test_t_r2_ec_01_01_empty_directory(temp_dir):
    """T-R2-EC-01-01: Empty directory returns 0 skills with success status."""
    empty_sub = temp_dir / "empty_dir"
    empty_sub.mkdir()
    res = scan_skills(platform=PlatformType.UNIVERSAL, custom_paths=[str(empty_sub)])
    assert len(res.skills) == 0
    assert res.summary.valid_skills == 0


def test_t_r2_ec_01_03_circular_symlink(temp_dir):
    """T-R2-EC-01-03: Circular symlink detection skips loop without infinite recursion."""
    # Attempt symlink creation; skip if OS lacks symlink privilege without dev mode
    sub_dir = temp_dir / "sub"
    sub_dir.mkdir()
    link = sub_dir / "loop"
    try:
        os.symlink(str(sub_dir), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        # Symlink creation privilege not available on some Windows accounts without elevation
        return

    res = scan_skills(platform=PlatformType.UNIVERSAL, custom_paths=[str(temp_dir)])
    assert isinstance(res.skills, list)


def test_parse_yaml_frontmatter_corrupted(temp_dir):
    """Test handling of invalid or non-yaml frontmatter."""
    corrupted_file = temp_dir / "corrupted.md"
    corrupted_file.write_text("---\n: invalid : yaml : [[\n---\nBody", encoding="utf-8")
    meta, body = parse_yaml_frontmatter(corrupted_file)
    assert meta == {}
    assert "Body" in body or body == ""

