"""End-to-end integration workflow tests (R3 Acceptance & Regression)."""

import json
import pytest
from typer.testing import CliRunner
from skill_manager.cli import app

runner = CliRunner()


@pytest.mark.r3
def test_e2e_full_lifecycle(sample_incomplete_skill, sample_index_file, temp_dir):
    """T-R3-E2E-01 (Source: FR-01, FR-03, FR-05): E2E lifecycle Scan -> Audit -> Complete -> Scan (JSON verification)."""
    # 1. Scan before completion
    res_scan1 = runner.invoke(app, ["scan", "--path", str(temp_dir), "--format", "json"])
    assert res_scan1.exit_code == 0
    data1 = json.loads(res_scan1.stdout)
    assert data1["summary"]["valid_skills"] >= 1

    # 2. Audit
    res_audit = runner.invoke(app, ["audit", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file), "--format", "json"])
    assert res_audit.exit_code == 0
    audit_data = json.loads(res_audit.stdout)
    assert audit_data["is_compliant"] is False

    # 3. Complete
    res_comp = runner.invoke(app, ["complete", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file), "--no-dry-run", "--format", "json"])
    assert res_comp.exit_code == 0
    comp_data = json.loads(res_comp.stdout)
    assert comp_data["success"] is True

    # 4. Audit again
    res_audit2 = runner.invoke(app, ["audit", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file), "--format", "json"])
    assert res_audit2.exit_code == 0
    audit_data2 = json.loads(res_audit2.stdout)
    assert audit_data2["is_compliant"] is True


@pytest.mark.r3
def test_e2e_workflow_audit_and_auto_complete_lifecycle(temp_dir):
    """T-R3-E2E-02 (Source: FR-05, FR-06): E2E lifecycle for workflow-audit -> auto-complete -> re-audit."""
    wf_file = temp_dir / "workflow.md"
    wf_file.write_text(
        "# Workflow\n- 綁定技能：brainstorming, systematic-debugging\n",
        encoding="utf-8",
    )
    target_skills_dir = temp_dir / "installed_skills"
    target_skills_dir.mkdir()

    # 1. Audit and auto-complete missing workflow skills (--no-dry-run)
    res_comp = runner.invoke(
        app,
        [
            "workflow-audit",
            "--workflow",
            str(wf_file),
            "--target-dir",
            str(target_skills_dir),
            "--auto-complete",
            "--no-dry-run",
            "--format",
            "json",
        ],
    )
    assert res_comp.exit_code == 0
    comp_payload = json.loads(res_comp.stdout)
    assert comp_payload["total_required"] == 2
    assert comp_payload["completion_result"]["success"] is True
    assert "brainstorming" in comp_payload["completion_result"]["completed_skills"]
    assert (target_skills_dir / "brainstorming" / "SKILL.md").exists()
    assert (target_skills_dir / "systematic-debugging" / "SKILL.md").exists()

