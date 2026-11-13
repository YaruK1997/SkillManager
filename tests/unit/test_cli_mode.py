"""Unit tests for CLI mode and tui commands (T-S2-08-CLI-MODE, FR-13, AC-13, EC-11)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from typer.testing import CliRunner

from skill_manager.cli import app
from skill_manager.models import SkillExecutionMode, GlobalPolicyMode

runner = CliRunner()


# ---------------------------------------------------------------------------
# 1. CLI Mode Command Tests
# ---------------------------------------------------------------------------

def test_cli_mode_toggle_single_skill(tmp_path):
    s = tmp_path / "skill-test"
    s.mkdir()
    (s / "SKILL.md").write_text("---\nname: skill-test\nactivation: on_demand\n---\n# Test\n", encoding="utf-8")

    result = runner.invoke(app, ["mode", str(s), "--set", "resident"])
    assert result.exit_code == 0
    assert "resident" in result.stdout

    # Verify disk content updated
    content = (s / "SKILL.md").read_text(encoding="utf-8")
    assert "activation: resident" in content


def test_cli_mode_toggle_invalid_mode(tmp_path):
    s = tmp_path / "skill-test"
    s.mkdir()
    result = runner.invoke(app, ["mode", str(s), "--set", "invalid_mode"])
    assert result.exit_code == 2
    assert "VALIDATION_ERROR" in result.stdout or "VALIDATION_ERROR" in result.stderr


def test_cli_mode_global_policy(tmp_path):
    s1 = tmp_path / "skill-1"
    s1.mkdir()
    (s1 / "SKILL.md").write_text("---\nname: skill-1\nactivation: resident\n---\n", encoding="utf-8")

    result = runner.invoke(app, ["mode", "--policy", "all_on_demand", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "all_on_demand" in result.stdout

    content = (s1 / "SKILL.md").read_text(encoding="utf-8")
    assert "activation: on_demand" in content


def test_cli_mode_list_json(tmp_path):
    s = tmp_path / "skill-json"
    s.mkdir()
    (s / "SKILL.md").write_text("---\nname: skill-json\nactivation: resident\n---\n", encoding="utf-8")

    result = runner.invoke(app, ["mode", "--path", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "skills" in data
    assert len(data["skills"]) >= 1


# ---------------------------------------------------------------------------
# 2. CLI TUI and Non-TTY Fallback Tests (FR-13, AC-13, EC-11)
# ---------------------------------------------------------------------------

def test_cli_tui_fallback_with_flag():
    # AC-13: Invoking `tui --no-tui` safely outputs help without launching Textual
    result = runner.invoke(app, ["tui", "--no-tui"])
    assert result.exit_code == 0
    assert "Non-interactive environment or --no-tui specified" in result.stdout


def test_cli_tui_fallback_non_tty():
    # EC-11: Environment with sys.stdin.isatty() == False (Docker background / pipes)
    with patch("sys.stdin.isatty", return_value=False):
        result = runner.invoke(app, ["tui"])
        assert result.exit_code == 0
        assert "Non-interactive environment or --no-tui specified" in result.stdout


def test_cli_root_entry_non_tty_fallback():
    # Direct execution of `skill-manager` in non-TTY falls back to CLI help
    with patch("sys.stdin.isatty", return_value=False):
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Usage" in result.stdout or "Options" in result.stdout


def test_cli_root_entry_no_tui_flag():
    # Execution with --no-tui flag falls back to help
    result = runner.invoke(app, ["--no-tui"])
    assert result.exit_code == 0
    assert "Usage" in result.stdout or "Options" in result.stdout
