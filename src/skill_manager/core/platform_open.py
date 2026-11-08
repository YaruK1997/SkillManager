"""Cross-platform native file manager folder opener with security sanitization."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


def get_open_command(folder_path: Path | str, os_name: Optional[str] = None) -> list[str]:
    """Build the safe argument vector to open the file manager for the given path."""
    p_str = str(Path(folder_path).resolve())
    current_os = os_name or sys.platform

    if current_os.startswith("win"):
        # Windows explorer.exe
        return ["explorer.exe", p_str]
    elif current_os == "darwin":
        # macOS open
        return ["open", p_str]
    else:
        # Linux / FreeBSD / other POSIX xdg-open
        return ["xdg-open", p_str]


def open_folder_in_file_manager(folder_path: Path | str) -> bool:
    """
    Launch native desktop file manager pointing to folder_path.
    Uses argument array without shell=True to guarantee protection against command injection (EC-13).
    """
    p = Path(folder_path)
    if not p.exists():
        return False

    cmd = get_open_command(p)
    try:
        # Launch asynchronously in detached process so file manager doesn't block SkillManager
        subprocess.Popen(
            cmd,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:
        sys.stderr.write(f"[WARN] Failed to open folder in file manager: {exc}\n")
        return False
