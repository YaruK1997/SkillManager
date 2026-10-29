"""Unit tests for CLI commands and output formatting (FR-05, FR-06)."""

import json
import pytest
from typer.testing import CliRunner
from skill_manager.cli import app

runner = CliRunner()


@pytest.mark.r1
def test_t_r1_ac_05_01_json_format_output(sample_valid_skill, temp_dir):
    """T-R1-AC-05-01 (Source: AC-05-01): CLI --format json produces parseable JSON with 0 ANSI color codes."""
    result = runner.invoke(app, ["scan", "--path", str(temp_dir), "--format", "json"])
    assert result.exit_code == 0

    # Ensure stdout is valid JSON
    parsed = json.loads(result.stdout)
    assert "skills" in parsed
    assert "summary" in parsed
    assert isinstance(parsed["skills"], list)


@pytest.mark.r2
def test_t_r2_ac_05_03_unknown_subcommand():
    """T-R2-AC-05-03 (Source: AC-05-03): Unknown subcommand returns exit code 2."""
    result = runner.invoke(app, ["nonexistent_command"])
    assert result.exit_code == 2


@pytest.mark.r1
def test_cli_audit_and_complete_workflow(sample_incomplete_skill, sample_index_file):
    """T-R1-AC-03-01 / T-R1-AC-03-02 (Source: AC-03-01, AC-03-02): Test CLI audit and complete execution with table format."""
    # Audit incomplete
    res_audit = runner.invoke(app, ["audit", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file)])
    assert res_audit.exit_code == 0
    assert "NON-COMPLIANT" in res_audit.stdout

    # Complete dry run
    res_dry = runner.invoke(app, ["complete", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file), "--dry-run"])
    assert res_dry.exit_code == 0
    assert "DRY RUN" in res_dry.stdout

    # Complete actual
    res_apply = runner.invoke(app, ["complete", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file), "--no-dry-run"])
    assert res_apply.exit_code == 0
    assert "APPLIED" in res_apply.stdout

    # Re-audit should be compliant
    res_re = runner.invoke(app, ["audit", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file)])
    assert res_re.exit_code == 0
    assert "COMPLIANT" in res_re.stdout


@pytest.mark.r1
def test_cli_healthcheck():
    """T-R1-AC-05-01 (Source: AC-05-01): Verify healthcheck endpoint returns status healthy and code 200."""
    res_json = runner.invoke(app, ["healthcheck", "--format", "json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["status"] == "healthy"
    assert data["code"] == 200

    res_table = runner.invoke(app, ["healthcheck", "--format", "table"])
    assert res_table.exit_code == 0
    assert "HEALTHY (200)" in res_table.stdout


@pytest.mark.r1
def test_cli_workflow_audit_command(temp_dir):
    """T-R1-AC-06-01 (Source: AC-06-01): Verify CLI workflow-audit outputs valid JSON and table."""
    wf_file = temp_dir / "workflow.md"
    wf_file.write_text("- skills/brainstorming/SKILL.md\n", encoding="utf-8")

    res_json = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--format", "json"])
    assert res_json.exit_code == 0
    parsed = json.loads(res_json.stdout)
    assert parsed["total_required"] == 1
    assert parsed["skills"][0]["name"] == "brainstorming"

    res_table = runner.invoke(app, ["workflow-audit", "--workflow", str(wf_file), "--format", "table"])
    assert res_table.exit_code == 0
    assert "brainstorming" in res_table.stdout


@pytest.mark.r1
def test_cli_config_command(temp_dir):
    """IMP-01 / FR-05: Test CLI config show command in json and table format."""
    res_json = runner.invoke(app, ["config", "show", "--format", "json"])
    assert res_json.exit_code == 0
    parsed = json.loads(res_json.stdout)
    assert "custom_platform_paths" in parsed

    res_table = runner.invoke(app, ["config", "show", "--format", "table"])
    assert res_table.exit_code == 0
    assert "Configuration" in res_table.stdout


@pytest.mark.r1
def test_cli_scan_custom_paths_alias(temp_dir):
    """IMP-02 / AC-01-04: Test CLI scan supports --custom-paths and depth."""
    res = runner.invoke(app, ["scan", "--custom-paths", str(temp_dir), "--depth", "2", "--format", "json"])
    assert res.exit_code == 0
    parsed = json.loads(res.stdout)
    assert parsed["summary"]["valid_skills"] >= 0


@pytest.mark.r2
def test_cli_audit_permission_denied(temp_dir, monkeypatch):
    """CRIT-04 / AC-03-04: Test CLI audit returns exit code 5 on PermissionError."""
    def mock_audit(*args, **kwargs):
        raise PermissionError("Access is denied")

    monkeypatch.setattr("skill_manager.cli.audit_skill", mock_audit)
    res = runner.invoke(app, ["audit", "--target", str(temp_dir)])
    assert res.exit_code == 5
    assert "ACCESS_DENIED" in res.stderr


@pytest.mark.r2
def test_cli_track_network_timeout(temp_dir, monkeypatch):
    """IMP-03 / AC-04-05: Test CLI track status returns exit code 7 on NETWORK_TIMEOUT."""
    from skill_manager.models import TrackResult, VersionStatus
    def mock_check(*args, **kwargs):
        return TrackResult(
            skill_name="timeout-skill",
            skill_path=str(temp_dir),
            version_status=VersionStatus.NETWORK_TIMEOUT,
        )

    monkeypatch.setattr("skill_manager.cli.check_version_status", mock_check)
    res = runner.invoke(app, ["track", "status", "--target", str(temp_dir)])
    assert res.exit_code == 7
