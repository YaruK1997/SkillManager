"""Unit tests for Textual TUI main app (T-S2-05-TUI-APP, FR-10, EC-14, AC-10)."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from skill_manager.tui.app import SkillManagerApp
from skill_manager.models import SkillEntity, SkillExecutionMode, PlatformType
from skill_manager.events import SkillModeChangedEvent


@pytest.fixture
def mock_app():
    return SkillManagerApp()


def test_tui_app_init(mock_app):
    assert mock_app.TITLE == "SkillManager Dashboard"
    assert mock_app.SUB_TITLE == "v0.3.0"
    binding_keys = [b.key for b in mock_app.BINDINGS]
    assert "q" in binding_keys
    assert "slash" in binding_keys
    assert "space" in binding_keys
    assert "o" in binding_keys


def test_check_terminal_size_ec14(mock_app):
    # Test boundary < 80x24 (EC-14)
    assert mock_app.check_terminal_size(79, 24) is True
    assert mock_app.is_screen_too_small is True

    assert mock_app.check_terminal_size(80, 23) is True
    assert mock_app.is_screen_too_small is True

    assert mock_app.check_terminal_size(60, 15) is True
    assert mock_app.is_screen_too_small is True

    # Test valid >= 80x24
    assert mock_app.check_terminal_size(80, 24) is False
    assert mock_app.is_screen_too_small is False

    assert mock_app.check_terminal_size(120, 40) is False
    assert mock_app.is_screen_too_small is False


@pytest.mark.anyio
async def test_tui_app_headless_run():
    app = SkillManagerApp()
    async with app.run_test(size=(100, 30)) as pilot:
        # Check components mounted
        assert app.query_one("#tabs") is not None
        assert app.query_one("#filter-input") is not None
        assert app.query_one("#metadata-panel") is not None
        assert app.query_one("#diff-panel") is not None

        # Check EC-14 warning is hidden on 100x30
        warning = app.query_one("#size-warning")
        assert warning.display is False


@pytest.mark.anyio
async def test_tui_app_filtering_and_selection(tmp_path):
    s1 = SkillEntity(
        id="skill-alpha",
        name="Skill Alpha",
        path=str(tmp_path / "alpha"),
        execution_mode=SkillExecutionMode.RESIDENT,
    )
    s2 = SkillEntity(
        id="skill-beta",
        name="Skill Beta",
        path=str(tmp_path / "beta"),
        execution_mode=SkillExecutionMode.ON_DEMAND,
    )

    app = SkillManagerApp()
    app.skills = [s1, s2]

    async with app.run_test(size=(100, 30)) as pilot:
        app._update_skill_list()
        assert app.selected_skill == s1

        # Test filter
        app._update_skill_list(filter_text="beta")
        # Ensure filtering doesn't crash and works
        app._update_detail_panels()


@pytest.mark.anyio
async def test_tui_app_toggle_mode_action(tmp_path):
    s = SkillEntity(
        id="skill-toggle",
        name="Skill Toggle",
        path=str(tmp_path / "toggle"),
        execution_mode=SkillExecutionMode.RESIDENT,
    )
    app = SkillManagerApp()
    app.skills = [s]
    app.selected_skill = s

    with patch("skill_manager.tui.app.async_toggle_skill_mode") as mock_toggle:
        mock_toggle.return_value = SkillModeChangedEvent(
            skill_name="Skill Toggle",
            platform="universal",
            old_mode=SkillExecutionMode.RESIDENT,
            new_mode=SkillExecutionMode.ON_DEMAND,
            skill_path=s.path,
            success=True,
        )

        async with app.run_test(size=(100, 30)) as pilot:
            await app.action_toggle_mode()
            assert s.execution_mode == SkillExecutionMode.ON_DEMAND


@pytest.mark.anyio
async def test_tui_app_open_folder_action(tmp_path):
    s = SkillEntity(
        id="skill-open",
        name="Skill Open",
        path=str(tmp_path / "open"),
    )
    app = SkillManagerApp()
    app.selected_skill = s

    with patch("skill_manager.tui.app.open_folder_in_file_manager") as mock_open:
        mock_open.return_value = True
        async with app.run_test(size=(100, 30)) as pilot:
            app.action_open_folder()
            mock_open.assert_called_once_with(s.path)
