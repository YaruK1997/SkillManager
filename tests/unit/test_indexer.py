"""Unit tests for indexer and audit module (FR-03)."""

from pathlib import Path
import pytest
from skill_manager.core.indexer import (
    IndexSchemaError,
    audit_skill,
    complete_skill,
    parse_index_schema,
)


@pytest.mark.r1
def test_t_r1_ac_03_01_audit_incomplete_skill(sample_incomplete_skill, sample_index_file):
    """T-R1-AC-03-01 (Source: AC-03-01): Incomplete skill fails audit and identifies missing sections & dirs."""
    res = audit_skill(sample_incomplete_skill, index_path=sample_index_file)
    assert res.is_compliant is False
    assert "When to Use" in res.missing_sections
    assert "Instructions" in res.missing_sections
    assert "scripts" in res.missing_dirs
    assert "references" in res.missing_dirs
    assert res.diff_content is not None
    assert "## When to Use" in res.diff_content


@pytest.mark.r1
def test_t_r1_ac_03_02_complete_skill_applied(sample_incomplete_skill, sample_index_file):
    """T-R1-AC-03-02 (Source: AC-03-02): Auto-completion fixes missing sections and creates directories."""
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


@pytest.mark.r2
def test_t_r2_ac_03_03_invalid_index_schema(temp_dir):
    """T-R2-AC-03-03 (Source: AC-03-03): Empty index.md raises IndexSchemaError."""
    bad_index = temp_dir / "bad_index.md"
    bad_index.write_text("   \n\n  ", encoding="utf-8")

    with pytest.raises(IndexSchemaError, match="INVALID_INDEX_SCHEMA"):
        parse_index_schema(bad_index)


@pytest.mark.r2
def test_t_r2_ec_03_01_empty_directory_audit(temp_dir):
    """T-R2-EC-03-01 (Source: EC-03-01): Empty target directory raises ValueError."""
    empty_skill = temp_dir / "empty-skill-dir"
    empty_skill.mkdir()

    with pytest.raises(ValueError, match="TARGET_DIR_EMPTY"):
        audit_skill(empty_skill)


@pytest.mark.r1
def test_audit_fully_compliant_skill(sample_valid_skill, sample_index_file):
    """T-R1-AC-03-01 (Source: AC-03-01): Audit of valid skill returns compliant."""
    res = audit_skill(sample_valid_skill, index_path=sample_index_file)
    assert res.is_compliant is True
    assert len(res.missing_fields) == 0
    assert len(res.missing_sections) == 0
    assert len(res.missing_dirs) == 0


@pytest.mark.r1
def test_complete_skill_missing_frontmatter(temp_dir):
    """Verify Frontmatter completion for existing SKILL.md missing description or entire frontmatter."""
    # Case 1: SKILL.md with frontmatter but missing description
    skill1 = temp_dir / "skill-missing-desc"
    skill1.mkdir()
    skill1_md = skill1 / "SKILL.md"
    skill1_md.write_text("---\nname: skill-missing-desc\n---\n# skill-missing-desc\n## When to Use\nDetails\n## Instructions\nSteps\n", encoding="utf-8")
    (skill1 / "scripts").mkdir()
    (skill1 / "references").mkdir()

    res1 = audit_skill(skill1)
    assert "description" in res1.missing_fields

    success, diff, modified = complete_skill(skill1, dry_run=False)
    assert success is True
    assert str(skill1_md) in modified

    content1 = skill1_md.read_text(encoding="utf-8")
    assert "description: Skill description for skill-missing-desc" in content1
    re_audit1 = audit_skill(skill1)
    assert re_audit1.is_compliant is True

    # Case 2: SKILL.md without any frontmatter
    skill2 = temp_dir / "skill-no-fm"
    skill2.mkdir()
    skill2_md = skill2 / "SKILL.md"
    skill2_md.write_text("# skill-no-fm\n## When to Use\nDetails\n## Instructions\nSteps\n", encoding="utf-8")
    (skill2 / "scripts").mkdir()
    (skill2 / "references").mkdir()

    res2 = audit_skill(skill2)
    assert "name" in res2.missing_fields
    assert "description" in res2.missing_fields

    success2, diff2, modified2 = complete_skill(skill2, dry_run=False)
    assert success2 is True
    content2 = skill2_md.read_text(encoding="utf-8")
    assert content2.startswith("---\nname: skill-no-fm\ndescription: Skill description for skill-no-fm\n---\n")
    re_audit2 = audit_skill(skill2)
    assert re_audit2.is_compliant is True


@pytest.mark.r1
def test_audit_skill_code_block_false_positive(temp_dir):
    """Verify code block comments are stripped to prevent false positives in heading checks."""
    skill = temp_dir / "skill-code-block"
    skill.mkdir()
    skill_md = skill / "SKILL.md"
    # Document has no ## Instructions heading, only a comment inside fenced code block
    skill_md.write_text(
        "---\nname: skill-code-block\ndescription: Code block test\n---\n"
        "# skill-code-block\n"
        "## When to Use\n"
        "```python\n"
        "# Instructions for running code\n"
        "print('hello')\n"
        "```\n"
        "## Not Instructions\n"
        "Some unrelated text.\n",
        encoding="utf-8",
    )
    (skill / "scripts").mkdir()
    (skill / "references").mkdir()

    res = audit_skill(skill)
    # Must correctly flag Instructions as missing despite code block comment and negative heading
    assert "Instructions" in res.missing_sections
    assert res.is_compliant is False

    # Now test with a decorated heading ## **Instructions**
    skill_md.write_text(
        "---\nname: skill-code-block\ndescription: Code block test\n---\n"
        "# skill-code-block\n"
        "## When to Use\n"
        "Use details.\n"
        "## **Instructions**\n"
        "Step 1: run.\n",
        encoding="utf-8",
    )
    res_dec = audit_skill(skill)
    assert "Instructions" not in res_dec.missing_sections
    assert res_dec.is_compliant is True


@pytest.mark.r1
def test_complete_skill_empty_directory(temp_dir):
    """Verify complete_skill successfully initializes an empty directory without deadlocking."""
    empty_skill = temp_dir / "brand-new-skill"
    empty_skill.mkdir()

    # Direct audit with default allow_empty=False raises TARGET_DIR_EMPTY (EC-03-01)
    with pytest.raises(ValueError, match="TARGET_DIR_EMPTY"):
        audit_skill(empty_skill)

    # audit with allow_empty=True returns non-compliant AuditResult
    audit_res = audit_skill(empty_skill, allow_empty=True)
    assert audit_res.is_compliant is False
    assert "name" in audit_res.missing_fields
    assert "scripts" in audit_res.missing_dirs

    # complete_skill succeeds on empty directory and generates full skeleton
    success, diff, modified = complete_skill(empty_skill, dry_run=False)
    assert success is True
    assert (empty_skill / "SKILL.md").is_file()
    assert (empty_skill / "scripts").is_dir()
    assert (empty_skill / "references").is_dir()

    content = (empty_skill / "SKILL.md").read_text(encoding="utf-8")
    assert "name: brand-new-skill" in content
    assert "## When to Use" in content
    assert "## Instructions" in content

    # Re-audit should now be fully compliant
    final_audit = audit_skill(empty_skill)
    assert final_audit.is_compliant is True


