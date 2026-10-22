"""Unit tests for indexer and audit module (FR-03)."""

from pathlib import Path
import pytest
from skill_manager.core.indexer import (
    IndexSchemaError,
    audit_skill,
    complete_skill,
    parse_index_schema,
)


def test_t_r1_ac_03_01_audit_incomplete_skill(sample_incomplete_skill, sample_index_file):
    """T-R1-AC-03-01: Incomplete skill fails audit and identifies missing sections & dirs."""
    res = audit_skill(sample_incomplete_skill, index_path=sample_index_file)
    assert res.is_compliant is False
    assert "When to Use" in res.missing_sections
    assert "Instructions" in res.missing_sections
    assert "scripts" in res.missing_dirs
    assert "references" in res.missing_dirs
    assert res.diff_content is not None
    assert "## When to Use" in res.diff_content


def test_t_r1_ac_03_02_complete_skill_applied(sample_incomplete_skill, sample_index_file):
    """T-R1-AC-03-02: Auto-completion fixes missing sections and creates directories."""
    # Run completion with dry_run=False
    success, diff, modified = complete_skill(sample_incomplete_skill, index_path=sample_index_file, dry_run=False)
    assert success is True
    assert len(modified) > 0

    # Verify directories exist
    assert (sample_incomplete_skill / "scripts").is_dir()
    assert (sample_incomplete_skill / "references").is_dir()

    # Verify SKILL.md now contains missing sections
    skill_md = sample_incomplete_skill / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")
    assert "## When to Use" in content
    assert "## Instructions" in content

    # Re-audit should now be compliant
    re_audit = audit_skill(sample_incomplete_skill, index_path=sample_index_file)
    assert re_audit.is_compliant is True


def test_t_r2_ac_03_03_invalid_index_schema(temp_dir):
    """T-R2-AC-03-03: Empty index.md raises IndexSchemaError."""
    bad_index = temp_dir / "bad_index.md"
    bad_index.write_text("   \n\n  ", encoding="utf-8")

    with pytest.raises(IndexSchemaError, match="INVALID_INDEX_SCHEMA"):
        parse_index_schema(bad_index)


def test_t_r2_ec_03_01_empty_directory_audit(temp_dir):
    """T-R2-EC-03-01: Empty target directory raises ValueError."""
    empty_skill = temp_dir / "empty-skill-dir"
    empty_skill.mkdir()

    with pytest.raises(ValueError, match="TARGET_DIR_EMPTY"):
        audit_skill(empty_skill)


def test_audit_fully_compliant_skill(sample_valid_skill, sample_index_file):
    """Audit of valid skill returns compliant."""
    res = audit_skill(sample_valid_skill, index_path=sample_index_file)
    assert res.is_compliant is True
    assert len(res.missing_fields) == 0
    assert len(res.missing_sections) == 0
    assert len(res.missing_dirs) == 0

