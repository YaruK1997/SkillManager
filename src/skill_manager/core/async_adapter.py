"""Asynchronous core adapter and worker bridge for non-blocking TUI interactions."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Callable, Coroutine, List, Optional, Tuple

from skill_manager.config import AppConfig
from skill_manager.core.scanner import scan_skills
from skill_manager.core.indexer import audit_skill, complete_skill
from skill_manager.core.versioning import check_version_status, upgrade_skill, rollback_skill
from skill_manager.core.remote_search import search_remote_skills
from skill_manager.core.workflow_auditor import audit_workflow_skills, complete_workflow_skills
from skill_manager.core.mode_controller import toggle_skill_mode, apply_global_policy
from skill_manager.models import (
    AuditResult,
    GlobalPolicyMode,
    PlatformType,
    ScanResult,
    SearchResult,
    SkillEntity,
    SkillExecutionMode,
    TrackResult,
    WorkflowAuditResult,
    WorkflowCompleteResult,
)
from skill_manager.events import (
    ScanProgressEvent,
    SkillModeChangedEvent,
    GlobalPolicyChangedEvent,
)


async def async_scan_skills(
    platform: PlatformType = PlatformType.ALL,
    custom_paths: Optional[List[str]] = None,
    config: Optional[AppConfig] = None,
    max_depth: int = 3,
    on_progress: Optional[Callable[[ScanProgressEvent], Any]] = None,
) -> ScanResult:
    """Run scan_skills asynchronously without blocking the event loop."""
    loop = asyncio.get_running_loop()
    result: ScanResult = await loop.run_in_executor(
        None,
        lambda: scan_skills(
            platform=platform,
            custom_paths=custom_paths,
            config=config,
            max_depth=max_depth,
        ),
    )
    if on_progress:
        ev = ScanProgressEvent(
            current_path=custom_paths[0] if custom_paths else "all",
            scanned_count=result.summary.total_scanned,
            valid_count=result.summary.valid_skills,
        )
        if inspect.iscoroutinefunction(on_progress):
            await on_progress(ev)
        else:
            on_progress(ev)
    return result


async def async_audit_skill(skill_dir: Path | str, allow_empty: bool = False) -> AuditResult:
    """Run audit_skill asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: audit_skill(Path(skill_dir), allow_empty=allow_empty))


async def async_complete_skill(skill_dir: Path | str, dry_run: bool = True) -> Tuple[bool, str, List[str]]:
    """Run complete_skill asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: complete_skill(Path(skill_dir), dry_run=dry_run))


async def async_check_version(skill_path: Path | str, timeout: float = 5.0) -> TrackResult:
    """
    Run check_skill_version asynchronously with timeout guard against network freezes (EC-12).
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: check_version_status(Path(skill_path))),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        from skill_manager.models import VersionStatus
        p = Path(skill_path)
        return TrackResult(
            skill_name=p.name,
            skill_path=str(p.resolve()),
            version_status=VersionStatus.NETWORK_TIMEOUT,
            diff_summary="Network request timed out",
        )


async def async_upgrade_skill(skill_path: Path | str, force: bool = False) -> TrackResult:
    """Run upgrade_skill asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: upgrade_skill(skill_path, force=force))


async def async_rollback_skill(skill_path: Path | str, target_tag: Optional[str] = None) -> TrackResult:
    """Run rollback_skill asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: rollback_skill(skill_path, target_tag=target_tag))


async def async_toggle_skill_mode(
    skill_path: Path | str,
    target_mode: SkillExecutionMode | str,
    config_path: Optional[Path | str] = None,
) -> SkillModeChangedEvent:
    """Run toggle_skill_mode asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: toggle_skill_mode(skill_path, target_mode, config_path=config_path),
    )


async def async_apply_global_policy(
    policy: GlobalPolicyMode | str,
    skills: List[SkillEntity],
    platform: Optional[PlatformType | str] = None,
    config_path: Optional[Path | str] = None,
) -> GlobalPolicyChangedEvent:
    """Run apply_global_policy asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: apply_global_policy(policy, skills, platform=platform, config_path=config_path),
    )


async def async_search_remote(
    query: str,
    source: str = "all",
    limit: int = 20,
    page: int = 1,
    timeout: float = 10.0,
) -> SearchResult:
    """Search remote skills asynchronously with timeout handling."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: search_remote_skills(query=query, source=source, limit=limit, page=page),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return SearchResult(items=[], total_count=0, current_page=page, limit=limit)


async def async_audit_workflow(
    workflow_path: Optional[Path | str] = None,
    platform: PlatformType = PlatformType.ALL,
    skill_sources: Optional[List[str]] = None,
    custom_paths: Optional[List[str]] = None,
) -> WorkflowAuditResult:
    """Run audit_workflow_skills asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: audit_workflow_skills(
            workflow_path=workflow_path,
            platform=platform,
            skill_sources=skill_sources,
            custom_paths=custom_paths,
        ),
    )


async def async_complete_workflow(
    workflow_path: Optional[Path | str] = None,
    platform: PlatformType = PlatformType.ALL,
    skill_sources: Optional[List[str]] = None,
    custom_paths: Optional[List[str]] = None,
    dry_run: bool = True,
) -> WorkflowCompleteResult:
    """Run complete_workflow_skills asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: complete_workflow_skills(
            workflow_path=workflow_path,
            platform=platform,
            skill_sources=skill_sources,
            custom_paths=custom_paths,
            dry_run=dry_run,
        ),
    )
