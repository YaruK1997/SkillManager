"""Unit tests for async adapter module (T-S2-04-ASYNC)."""

import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from skill_manager.models import (
    PlatformType,
    SkillEntity,
    SkillExecutionMode,
    GlobalPolicyMode,
    VersionStatus,
    ScanResult,
    ScanSummary,
    AuditResult,
    TrackResult,
)
from skill_manager.core.async_adapter import (
    async_scan_skills,
    async_audit_skill,
    async_complete_skill,
    async_check_version,
    async_toggle_skill_mode,
    async_apply_global_policy,
    async_search_remote,
    async_audit_workflow,
)


@pytest.mark.anyio
async def test_async_scan_skills_with_progress(tmp_path):
    s1 = tmp_path / "skill-1"
    s1.mkdir()
    (s1 / "SKILL.md").write_text("---\nname: skill-1\n---\n# S1\n", encoding="utf-8")

    progress_events = []

    def on_prog(ev):
        progress_events.append(ev)

    res = await async_scan_skills(
        platform=PlatformType.UNIVERSAL,
        custom_paths=[str(tmp_path)],
        on_progress=on_prog,
    )
    assert isinstance(res, ScanResult)
    assert len(res.skills) == 1
    assert len(progress_events) == 1
    assert progress_events[0].valid_count == 1


@pytest.mark.anyio
async def test_async_audit_and_complete(tmp_path):
    s = tmp_path / "skill-audit"
    s.mkdir()
    (s / "SKILL.md").write_text("# Invalid markdown without frontmatter", encoding="utf-8")

    audit_res = await async_audit_skill(s)
    assert isinstance(audit_res, AuditResult)

    success, diff_text, files = await async_complete_skill(s, dry_run=True)
    assert success is True
    assert "SKILL.md" in diff_text
    assert len(files) == 1


@pytest.mark.anyio
async def test_async_check_version_timeout(tmp_path):
    # Simulate a hanging check_version_status
    with patch("skill_manager.core.async_adapter.check_version_status") as mock_check:
        import time

        def slow_check(path):
            time.sleep(0.3)
            return TrackResult(skill_name="slow", skill_path=str(path), version_status=VersionStatus.UP_TO_DATE)

        mock_check.side_effect = slow_check

        # Fast timeout should trigger NETWORK_TIMEOUT
        res = await async_check_version(tmp_path, timeout=0.05)
        assert res.version_status == VersionStatus.NETWORK_TIMEOUT


@pytest.mark.anyio
async def test_async_toggle_and_policy(tmp_path):
    s = tmp_path / "skill-m"
    s.mkdir()
    (s / "SKILL.md").write_text("---\nname: skill-m\nactivation: on_demand\n---\n# M\n", encoding="utf-8")
    cfg = tmp_path / "config.toml"

    ev = await async_toggle_skill_mode(s, SkillExecutionMode.RESIDENT, config_path=cfg)
    assert ev.success is True
    assert ev.new_mode == SkillExecutionMode.RESIDENT

    skills = [SkillEntity(id="skill-m", name="skill-m", path=str(s))]
    ev_pol = await async_apply_global_policy(GlobalPolicyMode.ALL_ON_DEMAND, skills, config_path=cfg)
    assert ev_pol.success is True


@pytest.mark.anyio
async def test_async_search_remote_timeout():
    with patch("skill_manager.core.async_adapter.search_remote_skills") as mock_search:
        import time

        def slow_search(*args, **kwargs):
            time.sleep(0.3)
            return None

        mock_search.side_effect = slow_search

        res = await async_search_remote("test", timeout=0.05)
        assert res.items == []
        assert res.total_count == 0
