"""Unit tests for configuration and path resolution."""

import os
from pathlib import Path
from skill_manager.config import AppConfig, get_default_platform_paths, resolve_platform_paths
from skill_manager.models import PlatformType


def test_default_platform_paths_structure():
    paths = get_default_platform_paths()
    assert PlatformType.CLAUDE in paths
    assert PlatformType.ANTIGRAVITY in paths
    assert PlatformType.CODEX in paths
    assert PlatformType.CURSOR in paths

    for p_type, p_list in paths.items():
        assert len(p_list) > 0
        for p in p_list:
            assert isinstance(p, Path)


def test_resolve_platform_paths_all():
    resolved = resolve_platform_paths(PlatformType.ALL)
    assert len(resolved) > 0
    # Check deduplication
    assert len(resolved) == len(set(resolved))


def test_resolve_platform_paths_single():
    resolved = resolve_platform_paths(PlatformType.CLAUDE)
    assert len(resolved) > 0
    for p in resolved:
        assert ".claude" in str(p).lower()


def test_resolve_custom_paths(temp_dir):
    custom_sub = temp_dir / "custom_skills"
    custom_sub.mkdir()
    resolved = resolve_platform_paths(PlatformType.UNIVERSAL, custom_paths=[str(custom_sub)])
    assert custom_sub.resolve() in resolved


def test_config_override_paths(temp_dir):
    override_dir = temp_dir / "custom_claude"
    override_dir.mkdir()
    cfg = AppConfig(custom_platform_paths={"claude": [str(override_dir)]})
    resolved = resolve_platform_paths(PlatformType.CLAUDE, config=cfg)
    assert override_dir.resolve() in resolved

