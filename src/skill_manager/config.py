"""Configuration management and cross-platform path resolution."""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from skill_manager.models import PlatformType


class AppConfig(BaseModel):
    """Runtime configuration for SkillManager."""
    custom_platform_paths: Dict[str, List[str]] = Field(default_factory=dict)
    github_token: Optional[str] = Field(default=None)
    hf_token: Optional[str] = Field(default=None)
    default_format: str = Field(default="table")
    max_scan_depth: int = Field(default=3)


def get_default_platform_paths() -> Dict[PlatformType, List[Path]]:
    """Determine standard global skill directories per platform across Windows, macOS, and Linux."""
    home = Path.home()

    return {
        PlatformType.CLAUDE: [
            home / ".claude" / "skills",
            home / ".claude" / "plugins",
        ],
        PlatformType.ANTIGRAVITY: [
            home / ".gemini" / "antigravity" / "skills",
            home / ".gemini" / "antigravity" / "builtin" / "skills",
        ],
        PlatformType.CODEX: [
            home / ".codex" / "skills",
            home / ".copilot" / "skills",
        ],
        PlatformType.CURSOR: [
            home / ".cursor" / "skills",
        ],
    }


def resolve_platform_paths(
    platform: PlatformType = PlatformType.ALL,
    custom_paths: Optional[List[str]] = None,
    config: Optional[AppConfig] = None,
) -> List[Path]:
    """Resolve and expand directory paths to inspect, combining defaults and custom overrides."""
    resolved_paths: List[Path] = []
    defaults = get_default_platform_paths()

    # Determine which platform paths to check
    targets = [
        PlatformType.CLAUDE,
        PlatformType.ANTIGRAVITY,
        PlatformType.CODEX,
        PlatformType.CURSOR,
    ] if platform == PlatformType.ALL else [platform]

    for p in targets:
        # Check custom configuration override first if configured
        if config and p.value in config.custom_platform_paths:
            for custom_p in config.custom_platform_paths[p.value]:
                resolved_paths.append(Path(os.path.expandvars(custom_p)).expanduser().resolve())
        elif p in defaults:
            for default_p in defaults[p]:
                resolved_paths.append(default_p.resolve())

    # Add extra arbitrary user-supplied custom paths
    if custom_paths:
        for extra in custom_paths:
            resolved_paths.append(Path(os.path.expandvars(extra)).expanduser().resolve())

    # Deduplicate while preserving order
    seen = set()
    deduped: List[Path] = []
    for path in resolved_paths:
        if path not in seen:
            seen.add(path)
            deduped.append(path)

    return deduped


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from TOML file or environment variables."""
    cfg = AppConfig()

    # Check environment variable tokens
    cfg.github_token = os.environ.get("GITHUB_TOKEN")
    cfg.hf_token = os.environ.get("HF_TOKEN")

    path_to_try = Path(config_path) if config_path else Path.home() / ".config" / "skill-manager" / "config.toml"
    if path_to_try.exists() and path_to_try.is_file():
        try:
            import tomllib  # Python standard library since 3.11
            with open(path_to_try, "rb") as f:
                data = tomllib.load(f)
                return AppConfig(**data)
        except Exception:
            pass

    return cfg

