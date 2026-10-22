"""Unit tests for CLI commands and output formatting (FR-05)."""

import json
from typer.testing import CliRunner
from skill_manager.cli import app

runner = CliRunner()


def test_t_r1_ac_05_01_json_format_output(sample_valid_skill, temp_dir):
    """T-R1-AC-05-01: CLI --format json produces parseable JSON with 0 ANSI color codes."""
    result = runner.invoke(app, ["scan", "--path", str(temp_dir), "--format", "json"])
    assert result.exit_code == 0

    # Ensure stdout is valid JSON
    parsed = json.loads(result.stdout)
    assert "skills" in parsed
    assert "summary" in parsed
    assert isinstance(parsed["skills"], list)


def test_t_r2_ac_05_03_unknown_subcommand():
    """T-R2-AC-05-03: Unknown subcommand returns exit code 2."""
    result = runner.invoke(app, ["nonexistent_command"])
    assert result.exit_code == 2


def test_cli_audit_and_complete_workflow(sample_incomplete_skill, sample_index_file):
    """Test CLI audit and complete execution with table format."""
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



def test_cli_healthcheck():
    """Verify healthcheck endpoint returns status healthy and code 200."""
    res_json = runner.invoke(app, ["healthcheck", "--format", "json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.stdout)
    assert data["status"] == "healthy"
    assert data["code"] == 200

    res_table = runner.invoke(app, ["healthcheck", "--format", "table"])
    assert res_table.exit_code == 0
    assert "HEALTHY (200)" in res_table.stdout
