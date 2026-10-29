"""Unit tests for workflow skill requirements parsing, auditing, and auto-completion (FR-06)."""

import os
from pathlib import Path
import pytest

from skill_manager.core.workflow_auditor import (
    audit_workflow_skills,
    complete_workflow_skills,
    find_default_workflow_file,
    find_skill_in_sources,
    parse_workflow_requirements,
)
from skill_manager.models import PlatformType, WorkflowSkillStatus


@pytest.fixture
def sample_workflow_file(temp_dir):
    """Create a sample workflow markdown file with skill bindings and paths."""
    wf_path = temp_dir / "workflow.md"
    content = """# System Development Workflow

## 1. Global Meta Skills
- using-superpowers (skills/using-superpowers/SKILL.md)
- i-have-adhd (skills/i-have-adhd/SKILL.md)

## 2. Phase 1
- 綁定技能：brainstorming, writing-plans

## 3. Phase 2
- 調用技能 (Skills Allocation): tdd, dispatching-parallel-agents
- Ref: skills/modern-web-guidance/SKILL.md

| Skill Name | Path |
| :--- | :--- |
| **systematic-debugging** | `skills/systematic-debugging/SKILL.md` |
"""
    wf_path.write_text(content, encoding="utf-8")
    return wf_path


@pytest.mark.r1
def test_t_r1_ac_06_01_parse_workflow_requirements(sample_workflow_file):
    """T-R1-AC-06-01 (Source: AC-06-01): Successfully extract skills from workflow markdown."""
    skills = parse_workflow_requirements(sample_workflow_file)
    assert "using-superpowers" in skills
    assert "i-have-adhd" in skills
    assert "brainstorming" in skills
    assert "writing-plans" in skills
    # 'tdd' should be mapped to canonical 'test-driven-development'
    assert "test-driven-development" in skills
    assert "dispatching-parallel-agents" in skills
    assert "modern-web-guidance" in skills
    assert "systematic-debugging" in skills


@pytest.mark.r1
def test_t_r1_ac_06_01_audit_workflow_status(sample_workflow_file, temp_dir):
    """T-R1-AC-06-01 (Source: AC-06-01): Correctly categorizes INSTALLED, MISSING, and INCOMPLETE."""
    # Create installed skills directory
    skills_root = temp_dir / "installed_skills"
    skills_root.mkdir()

    # 1. Fully compliant skill
    valid_skill = skills_root / "using-superpowers"
    valid_skill.mkdir()
    (valid_skill / "SKILL.md").write_text(
        "---\nname: using-superpowers\ndescription: Core superpowers\n---\n# using-superpowers\n## When to Use\nAlways\n## Instructions\nFollow it\n",
        encoding="utf-8",
    )
    (valid_skill / "scripts").mkdir()
    (valid_skill / "references").mkdir()

    # 2. Incomplete skill (missing sections and dirs)
    incomp_skill = skills_root / "i-have-adhd"
    incomp_skill.mkdir()
    (incomp_skill / "SKILL.md").write_text(
        "---\nname: i-have-adhd\ndescription: Concise\n---\n# i-have-adhd\n",
        encoding="utf-8",
    )

    res = audit_workflow_skills(
        workflow_path=sample_workflow_file,
        platform=PlatformType.UNIVERSAL,
        custom_paths=[str(skills_root)],
    )

    assert res.total_required > 0
    skills_dict = {s.name: s for s in res.skills}

    assert skills_dict["using-superpowers"].status == WorkflowSkillStatus.INSTALLED
    assert skills_dict["i-have-adhd"].status == WorkflowSkillStatus.INCOMPLETE
    assert skills_dict["brainstorming"].status == WorkflowSkillStatus.MISSING
    assert res.installed_count >= 1
    assert res.incomplete_count >= 1
    assert res.missing_count >= 1
    assert not res.is_fully_satisfied


@pytest.mark.r1
def test_t_r1_ac_06_02_and_03_auto_complete_dry_run_and_apply(sample_workflow_file, temp_dir):
    """T-R1-AC-06-02 / T-R1-AC-06-03 (Source: AC-06-02, AC-06-03): Auto-complete from sources and skeleton generation."""
    # Setup candidate source
    source_root = temp_dir / "candidate_sources"
    source_root.mkdir()
    src_bs = source_root / "brainstorming"
    src_bs.mkdir()
    (src_bs / "SKILL.md").write_text("---\nname: brainstorming\ndescription: Design\n---\n# Brainstorming\n", encoding="utf-8")

    # Target directory for missing skills
    target_install_dir = temp_dir / "target_skills"

    # Audit initially
    audit_res = audit_workflow_skills(
        workflow_path=sample_workflow_file,
        custom_paths=[str(target_install_dir)],
    )
    assert audit_res.missing_count > 0

    # 1. Dry run
    comp_dry = complete_workflow_skills(
        audit_result=audit_res,
        target_dir=target_install_dir,
        skill_sources=[source_root],
        dry_run=True,
    )
    assert comp_dry.dry_run is True
    assert "brainstorming" in comp_dry.completed_skills
    # In dry run, files must not exist yet on disk
    assert not (target_install_dir / "brainstorming" / "SKILL.md").exists()

    # 2. No dry run (Apply)
    comp_apply = complete_workflow_skills(
        audit_result=audit_res,
        target_dir=target_install_dir,
        skill_sources=[source_root],
        dry_run=False,
    )
    assert comp_apply.dry_run is False
    assert (target_install_dir / "brainstorming" / "SKILL.md").exists()
    # Skills not found in source should have skeleton created
    assert "writing-plans" in comp_apply.created_skeletons
    assert (target_install_dir / "writing-plans" / "SKILL.md").exists()


@pytest.mark.r2
def test_t_r2_ac_06_04_missing_workflow_file():
    """T-R2-AC-06-04 (Source: AC-06-04): Non-existent workflow file raises FileNotFoundError."""
    missing_file = Path("D:/non_existent_path_xyz_123/workflow.md")
    with pytest.raises(FileNotFoundError, match="ERR_WORKFLOW_NOT_FOUND"):
        parse_workflow_requirements(missing_file)


@pytest.mark.r2
def test_t_r2_ac_06_05_and_ec_06_01_empty_workflow(temp_dir):
    """T-R2-AC-06-05 / T-R2-EC-06-01 (Source: AC-06-05, EC-06-01): Empty workflow file returns 0 skills gracefully."""
    empty_file = temp_dir / "empty_workflow.md"
    empty_file.write_text("", encoding="utf-8")

    skills = parse_workflow_requirements(empty_file)
    assert skills == []

    res = audit_workflow_skills(workflow_path=empty_file)
    assert res.total_required == 0
    assert res.skills == []
    assert res.is_fully_satisfied is False


@pytest.mark.r2
def test_t_r2_ec_06_02_large_workflow_file(temp_dir):
    """T-R2-EC-06-02 (Source: EC-06-02): Workflow file larger than 5MB is rejected."""
    large_file = temp_dir / "large_workflow.md"
    # Write slightly over 5MB
    large_file.write_text("x" * (5 * 1024 * 1024 + 100), encoding="utf-8")

    with pytest.raises(ValueError, match="WORKFLOW_FILE_TOO_LARGE"):
        parse_workflow_requirements(large_file)


@pytest.mark.r2
def test_t_r2_ec_06_03_corrupted_encoding(temp_dir):
    """T-R2-EC-06-03 (Source: EC-06-03): Corrupted non-UTF8 bytes are handled with replace mode."""
    corrupt_file = temp_dir / "corrupt_workflow.md"
    # Write invalid bytes followed by a valid skill mention
    corrupt_file.write_bytes(b"\xff\xfe\xfa\x80skills/my-robust-skill/SKILL.md\x00\x00")

    skills = parse_workflow_requirements(corrupt_file)
    assert "my-robust-skill" in skills


@pytest.mark.r2
def test_t_r2_ec_06_05_preserve_existing_skill_content(temp_dir):
    """T-R2-EC-06-05 (Source: EC-06-05): Incomplete skill completion preserves existing custom lines."""
    skill_dir = temp_dir / "custom-incomplete-skill"
    skill_dir.mkdir()
    original_custom_text = "### Custom Implementation Notes\nDo not erase me!\n"
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: custom-incomplete-skill\ndescription: Custom\n---\n# custom-incomplete-skill\n\n{original_custom_text}",
        encoding="utf-8",
    )

    wf_file = temp_dir / "wf.md"
    wf_file.write_text("- skills/custom-incomplete-skill/SKILL.md\n", encoding="utf-8")

    audit_res = audit_workflow_skills(workflow_path=wf_file, custom_paths=[str(temp_dir)])
    complete_workflow_skills(audit_res, target_dir=temp_dir, dry_run=False)

    updated_content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert original_custom_text in updated_content
    assert "## When to Use" in updated_content


@pytest.mark.r2
def test_t_r2_ec_06_06_atomic_replace_no_temp_residue(temp_dir):
    """T-R2-EC-06-06 (Source: EC-06-06): Concurrent/atomic completion uses PID-isolated .tmp files and leaves no residue."""
    wf_file = temp_dir / "wf_atomic.md"
    wf_file.write_text("- skills/atomic-wf-skill/SKILL.md\n", encoding="utf-8")

    audit_res = audit_workflow_skills(workflow_path=wf_file, custom_paths=[str(temp_dir)])
    res = complete_workflow_skills(audit_res, target_dir=temp_dir, dry_run=False)

    assert res.success is True
    skill_dir = temp_dir / "atomic-wf-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert list(skill_dir.glob("*.tmp*")) == []


@pytest.mark.r2
def test_t_r2_ac_06_06_and_ec_06_07_write_permission_denied(temp_dir, monkeypatch):
    """T-R2-AC-06-06 / T-R2-EC-06-07 (Source: AC-06-06, EC-06-07): Intercept write permission errors gracefully."""
    wf_file = temp_dir / "wf_perm.md"
    wf_file.write_text("- skills/brainstorming/SKILL.md\n", encoding="utf-8")
    audit_res = audit_workflow_skills(workflow_path=wf_file)

    def mock_copytree(*args, **kwargs):
        raise PermissionError("Access is denied")

    monkeypatch.setattr("shutil.copytree", mock_copytree)

    # Provide a source so it attempts copytree
    dummy_source = temp_dir / "source"
    dummy_source.mkdir()
    (dummy_source / "brainstorming").mkdir()

    with pytest.raises(PermissionError, match="WRITE_PERMISSION_DENIED"):
        complete_workflow_skills(
            audit_result=audit_res,
            target_dir=temp_dir / "target",
            skill_sources=[dummy_source],
            dry_run=False,
        )


@pytest.mark.r1
def test_find_default_workflow_file(temp_dir):
    """T-R1-AC-06-01 (Source: AC-06-01): Verify auto-detection of default workflow files."""
    assert find_default_workflow_file(temp_dir) is None

    wf = temp_dir / "workflow.md"
    wf.write_text("# Test", encoding="utf-8")
    assert find_default_workflow_file(temp_dir) == wf


@pytest.mark.r2
def test_complete_incomplete_skill_and_permission_error(temp_dir, monkeypatch):
    """T-R2-AC-06-06 (Source: AC-06-06): Test completing an incomplete skill with dry-run, apply, and permission error."""
    skill_dir = temp_dir / "incomp-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: incomp-skill\ndescription: Test\n---\n# Test\n", encoding="utf-8")

    wf = temp_dir / "wf.md"
    wf.write_text("- skills/incomp-skill/SKILL.md\n", encoding="utf-8")

    audit_res = audit_workflow_skills(workflow_path=wf, custom_paths=[str(temp_dir)])
    assert audit_res.incomplete_count == 1

    # 1. Dry run
    comp_dry = complete_workflow_skills(audit_res, dry_run=True)
    assert "incomp-skill" in comp_dry.completed_skills
    assert comp_dry.dry_run is True

    # 2. Permission error on complete_skill
    def mock_complete_err(*args, **kwargs):
        raise PermissionError("Access denied")

    monkeypatch.setattr("skill_manager.core.workflow_auditor.complete_skill", mock_complete_err)
    with pytest.raises(PermissionError, match="WRITE_PERMISSION_DENIED"):
        complete_workflow_skills(audit_res, dry_run=False)


@pytest.mark.r1
def test_find_skill_in_sources_nested_and_missing(temp_dir):
    """T-R1-AC-06-02 (Source: AC-06-02): Test finding skill in nested subfolder and non-existent source directory."""
    pack_dir = temp_dir / "packs"
    sub_vendor = pack_dir / "vendor"
    sub_vendor.mkdir(parents=True)
    target_skill = sub_vendor / "nested-skill"
    target_skill.mkdir()

    # Search with nested directory
    found = find_skill_in_sources("nested-skill", [pack_dir, temp_dir / "non_existent_folder"])
    assert found == target_skill

    # Search for non-existent skill
    assert find_skill_in_sources("phantom-skill", [pack_dir]) is None


@pytest.mark.r1
def test_audit_workflow_auto_detect_file(temp_dir, monkeypatch):
    """T-R1-AC-06-01 (Source: AC-06-01): Test audit_workflow_skills auto-detects workflow.md in current directory."""
    wf = temp_dir / "workflow.md"
    wf.write_text("- skills/my-auto-skill/SKILL.md\n", encoding="utf-8")
    monkeypatch.chdir(temp_dir)

    res = audit_workflow_skills()
    assert res.total_required == 1
    assert res.skills[0].name == "my-auto-skill"


@pytest.mark.r2
def test_complete_skills_skip_installed_and_skeleton_permission_error(sample_workflow_file, temp_dir, monkeypatch):
    """T-R2-EC-06-07 (Source: EC-06-07): Test complete_workflow_skills skips INSTALLED skills and handles skeleton write permission error."""
    # 1. Test skipping INSTALLED skills
    skills_root = temp_dir / "installed_skills"
    skills_root.mkdir()
    valid_skill = skills_root / "using-superpowers"
    valid_skill.mkdir()
    (valid_skill / "SKILL.md").write_text(
        "---\nname: using-superpowers\ndescription: Core\n---\n# using-superpowers\n## When to Use\nAlways\n## Instructions\nFollow\n",
        encoding="utf-8",
    )
    (valid_skill / "scripts").mkdir()
    (valid_skill / "references").mkdir()

    audit_res = audit_workflow_skills(
        workflow_path=sample_workflow_file,
        custom_paths=[str(skills_root)],
    )
    # Target directory with dry-run
    res_dry = complete_workflow_skills(audit_res, target_dir=temp_dir / "out", dry_run=True)
    assert "using-superpowers" not in res_dry.completed_skills

    # 2. Test permission error during skeleton creation
    wf_single = temp_dir / "wf_single.md"
    wf_single.write_text("- skills/brand-new-skeleton/SKILL.md\n", encoding="utf-8")
    audit_single = audit_workflow_skills(workflow_path=wf_single)

    def mock_skel_err(*args, **kwargs):
        raise PermissionError("Access denied")

    monkeypatch.setattr("skill_manager.core.workflow_auditor.complete_skill", mock_skel_err)
    with pytest.raises(PermissionError, match="WRITE_PERMISSION_DENIED"):
        complete_workflow_skills(audit_single, target_dir=temp_dir / "out_skel", dry_run=False)


