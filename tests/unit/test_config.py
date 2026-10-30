"""Unit tests for configuration and path resolution (FR-01, FR-05)."""

import os
from pathlib import Path
import pytest
from skill_manager.config import (
    AppConfig,
    detect_system_os,
    get_default_platform_paths,
    get_host_os,
    resolve_platform_paths,
)
from skill_manager.models import PlatformType


@pytest.mark.r1
def test_default_platform_paths_structure():
    """T-R1-AC-01-03 (Source: AC-01-03): Validate cross-platform default directory structure."""
    paths = get_default_platform_paths()
    assert PlatformType.CLAUDE in paths
    assert PlatformType.ANTIGRAVITY in paths
    assert PlatformType.CODEX in paths
    assert PlatformType.CURSOR in paths

    for p_type, p_list in paths.items():
        assert len(p_list) > 0
        for p in p_list:
            assert isinstance(p, Path)


@pytest.mark.r1
def test_resolve_platform_paths_all():
    """T-R1-AC-01-02 (Source: AC-01-02): Resolve and deduplicate all platform paths."""
    resolved = resolve_platform_paths(PlatformType.ALL)
    assert len(resolved) > 0
    # Check deduplication
    assert len(resolved) == len(set(resolved))


@pytest.mark.r1
def test_resolve_platform_paths_single():
    """T-R1-AC-01-02 (Source: AC-01-02): Resolve single platform path for Claude."""
    resolved = resolve_platform_paths(PlatformType.CLAUDE)
    assert len(resolved) > 0
    for p in resolved:
        assert ".claude" in str(p).lower()


@pytest.mark.r1
def test_resolve_custom_paths(temp_dir):
    """T-R1-AC-01-01 (Source: AC-01-01): Resolve custom directory path."""
    custom_sub = temp_dir / "custom_skills"
    custom_sub.mkdir()
    resolved = resolve_platform_paths(PlatformType.UNIVERSAL, custom_paths=[str(custom_sub)])
    assert custom_sub.resolve() in resolved


@pytest.mark.r1
def test_config_override_paths(temp_dir):
    """T-R1-AC-05-02 (Source: AC-05-02): Custom platform path in config overrides system defaults."""
    override_dir = temp_dir / "custom_claude"
    override_dir.mkdir()
    cfg = AppConfig(custom_platform_paths={"claude": [str(override_dir)]})
    resolved = resolve_platform_paths(PlatformType.CLAUDE, config=cfg)
    assert override_dir.resolve() in resolved


@pytest.mark.r1
def test_load_config_from_toml_file(temp_dir):
    """T-R1-AC-05-02: Load AppConfig from custom TOML file."""
    from skill_manager.config import load_config
    cfg_file = temp_dir / "test_config.toml"
    cfg_file.write_text('github_token = "gh_sample_123"\nhf_token = "hf_sample_456"\n', encoding="utf-8")
    loaded = load_config(str(cfg_file))
    assert loaded.github_token == "gh_sample_123"
    assert loaded.hf_token == "hf_sample_456"


@pytest.mark.r1
def test_detect_system_os(monkeypatch):
    """Validate system OS detection across platforms."""
    monkeypatch.setattr("sys.platform", "win32")
    assert detect_system_os() == "Windows"

    monkeypatch.setattr("sys.platform", "darwin")
    assert detect_system_os() == "macOS"

    monkeypatch.setattr("sys.platform", "linux")
    assert detect_system_os() == "Linux"


@pytest.mark.r1
def test_get_host_os_from_env(monkeypatch):
    """Validate host OS resolution from HOST_OS environment variable with fallback."""
    # When HOST_OS is provided
    monkeypatch.setenv("HOST_OS", "macOS")
    assert get_host_os() == "macOS"

    monkeypatch.setenv("HOST_OS", "Windows")
    assert get_host_os() == "Windows"

    monkeypatch.setenv("HOST_OS", "Linux")
    assert get_host_os() == "Linux"

    # Fallback to system detection when HOST_OS is not set
    monkeypatch.delenv("HOST_OS", raising=False)
    monkeypatch.setattr("sys.platform", "darwin")
    assert get_host_os() == "macOS"


