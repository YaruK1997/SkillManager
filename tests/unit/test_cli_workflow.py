"""Unit tests for workflow-audit CLI command (FR-05 & FR-06)."""

import json
from pathlib import Path
import pytest
from typer.testing import CliRunner

from skill_manager.cli import app

runner = CliRunner()


@pytest.mark.r1
def test_cli_workflow_audit_table_and_json(temp_dir):
    """T-R1-AC-06-01 / T-R1-AC-05-01: Test workflow-audit command in both table and clean json formats."""
    wf_file = temp_dir / "workflow.md"
    wf_file.write_text(
        "# Workflow\n- skills/using-superpowers/SKILL.md\n- skills/writing-plans/SKILL.md\n",
        encoding="utf-8",
    )

    # 1. JSON format
    res_json = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--format", "json"])
    assert res_json.exit_code == 0
    parsed = json.loads(res_json.stdout)
    assert parsed["total_required"] == 2
    assert "skills" in parsed
    assert len(parsed["skills"]) == 2

    # 2. Table format
    res_table = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--format", "table"])
    assert res_table.exit_code == 0
    assert "Workflow Skills Audit" in res_table.stdout
    assert "using-superpowers" in res_table.stdout


@pytest.mark.r1
def test_cli_workflow_audit_auto_complete(temp_dir):
    """T-R1-AC-06-02 / T-R1-AC-06-03: Test workflow-audit with --auto-complete dry-run and apply flags."""
    wf_file = temp_dir / "workflow.md"
    wf_file.write_text("# Workflow\n- skills/auto-complete-test/SKILL.md\n", encoding="utf-8")
    target_install = temp_dir / "target_skills"

    # Dry-run
    res_dry = runner.invoke(
        app,
        [
            "workflow-audit",
            "--workflow", str(wf_file),
            "--target-dir", str(target_install),
            "--auto-complete",
            "--dry-run",
            "--format", "json",
        ],
    )
    assert res_dry.exit_code == 0
    data_dry = json.loads(res_dry.stdout)
    assert data_dry["completion_result"]["dry_run"] is True
    assert not (target_install / "auto-complete-test" / "SKILL.md").exists()

    # Apply
    res_apply = runner.invoke(
        app,
        [
            "workflow-audit",
            "--workflow", str(wf_file),
            "--target-dir", str(target_install),
            "--auto-complete",
            "--no-dry-run",
            "--format", "table",
        ],
    )
    assert res_apply.exit_code == 0
    assert "Auto-Completion" in res_apply.stdout
    assert (target_install / "auto-complete-test" / "SKILL.md").exists()


@pytest.mark.r2
def test_cli_workflow_audit_missing_file_error():
    """T-R2-AC-06-04: Test CLI exit code 2 when specified workflow file does not exist."""
    res = runner.invoke(app, ["workflow-audit", "--workflow", "not_exist_file_999.md"])
    assert res.exit_code == 2
    assert "ERR_WORKFLOW_NOT_FOUND" in res.stderr


@pytest.mark.r2
def test_cli_workflow_audit_invalid_platform(temp_dir):
    """T-R2-AC-05-03: Test CLI exit code 2 when invalid platform option is passed."""
    wf_file = temp_dir / "wf.md"
    wf_file.write_text("# Test", encoding="utf-8")
    res = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--platform", "invalid_plat"])
    assert res.exit_code == 2
    assert "VALIDATION_ERROR" in res.stderr


@pytest.mark.r2
def test_cli_workflow_audit_empty_file(temp_dir):
    """T-R2-AC-06-05 / T-R2-EC-06-01: Test CLI handles empty workflow file gracefully."""
    wf_file = temp_dir / "empty.md"
    wf_file.write_text("", encoding="utf-8")
    res = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--format", "table"])
    assert res.exit_code == 0
    assert "NO_SKILL_REQUIREMENTS_FOUND" in res.stdout


@pytest.mark.r1
def test_cli_workflow_audit_target_dir_persistence(temp_dir):
    """IMP-04: Test workflow-audit re-detects completed skill in --target-dir."""
    wf_file = temp_dir / "workflow.md"
    wf_file.write_text("# Workflow\n- skills/persisted-skill/SKILL.md\n", encoding="utf-8")
    target_install = temp_dir / "target_skills"

    # 1. Complete into target_install
    res_c = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--target-dir", str(target_install), "--auto-complete", "--no-dry-run"])
    assert res_c.exit_code == 0

    # 2. Re-audit with --target-dir
    res_re = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--target-dir", str(target_install), "--format", "json"])
    assert res_re.exit_code == 0
    data = json.loads(res_re.stdout)
    assert data["installed_count"] == 1
    assert data["missing_count"] == 0

