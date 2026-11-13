"""Unit tests for platform_open module (T-S2-07-PLATFORM-OPEN)."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from skill_manager.core.platform_open import get_open_command, open_folder_in_file_manager


def test_get_open_command_windows():
    cmd = get_open_command("/tmp/skill", os_name="win32")
    assert cmd[0] == "explorer.exe"
    assert "/tmp/skill" in cmd[1]


def test_get_open_command_macos():
    cmd = get_open_command("/tmp/skill", os_name="darwin")
    assert cmd[0] == "open"
    assert "/tmp/skill" in cmd[1]


def test_get_open_command_linux():
    cmd = get_open_command("/tmp/skill", os_name="linux")
    assert cmd[0] == "xdg-open"
    assert "/tmp/skill" in cmd[1]


def test_open_folder_nonexistent():
    assert open_folder_in_file_manager("/definitely/nonexistent/path/12345") is False


@patch("subprocess.Popen")
def test_t_r2_ec_13_open_folder_command_injection_safeguard(mock_popen, tmp_path):
    """EC-13: Command injection guard with no shell=True."""
    mock_proc = MagicMock()
    mock_popen.return_value = mock_proc

    success = open_folder_in_file_manager(tmp_path)
    assert success is True
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert kwargs.get("shell") is False
