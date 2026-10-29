"""Unit tests for workflow-audit CLI command (FR-05 & FR-06)."""

import json
from pathlib import Path
from typer.testing import CliRunner

from skill_manager.cli import app

runner = CliRunner()


def test_cli_workflow_audit_table_and_json(temp_dir):
    """Test workflow-audit command in both table and clean json formats."""
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


def test_cli_workflow_audit_auto_complete(temp_dir):
    """Test workflow-audit with --auto-complete dry-run and apply flags."""
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


def test_cli_workflow_audit_missing_file_error():
    """Test CLI exit code 2 when specified workflow file does not exist."""
    res = runner.invoke(app, ["workflow-audit", "--workflow", "not_exist_file_999.md"])
    assert res.exit_code == 2
    assert "ERR_WORKFLOW_NOT_FOUND" in res.stderr


def test_cli_workflow_audit_invalid_platform(temp_dir):
    """Test CLI exit code 2 when invalid platform option is passed."""
    wf_file = temp_dir / "wf.md"
    wf_file.write_text("# Test", encoding="utf-8")
    res = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--platform", "invalid_plat"])
    assert res.exit_code == 2
    assert "VALIDATION_ERROR" in res.stderr


def test_cli_workflow_audit_empty_file(temp_dir):
    """Test CLI handles empty workflow file gracefully."""
    wf_file = temp_dir / "empty.md"
    wf_file.write_text("", encoding="utf-8")
    res = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--format", "table"])
    assert res.exit_code == 0
    assert "NO_SKILL_REQUIREMENTS_FOUND" in res.stdout
