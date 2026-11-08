"""Unit tests for models extension and events system (T-S2-01-MODEL)."""

import pytest
from skill_manager.models import (
    SkillEntity,
    SkillExecutionMode,
    GlobalPolicyMode,
    PlatformType,
    AuditResult,
    TrackResult,
    VersionStatus,
)
from skill_manager.events import (
    UIMode,
    ScanProgressEvent,
    SkillSelectedEvent,
    SkillModeChangedEvent,
    GlobalPolicyChangedEvent,
    AuditCompleteEvent,
    VersionUpdateEvent,
    LogEvent,
)


def test_skill_execution_mode_enums():
    assert SkillExecutionMode.RESIDENT.value == "resident"
    assert SkillExecutionMode.ON_DEMAND.value == "on_demand"

    assert GlobalPolicyMode.ALL_RESIDENT.value == "all_resident"
    assert GlobalPolicyMode.ALL_ON_DEMAND.value == "all_on_demand"
    assert GlobalPolicyMode.CUSTOM.value == "custom"


def test_skill_entity_execution_mode_default():
    entity = SkillEntity(
        id="test-skill",
        name="Test Skill",
        path="/tmp/test-skill",
    )
    assert entity.execution_mode == SkillExecutionMode.ON_DEMAND

    resident_entity = SkillEntity(
        id="test-resident",
        name="Test Resident",
        path="/tmp/test-resident",
        execution_mode=SkillExecutionMode.RESIDENT,
    )
    assert resident_entity.execution_mode == SkillExecutionMode.RESIDENT


def test_events_instantiation():
    entity = SkillEntity(id="s1", name="S1", path="/tmp/s1")
    sel_event = SkillSelectedEvent(skill=entity)
    assert sel_event.skill.id == "s1"

    prog_event = ScanProgressEvent(current_path="/tmp", scanned_count=10, valid_count=8)
    assert prog_event.scanned_count == 10

    mode_event = SkillModeChangedEvent(
        skill_name="s1",
        platform="claude",
        old_mode=SkillExecutionMode.RESIDENT,
        new_mode=SkillExecutionMode.ON_DEMAND,
        skill_path="/tmp/s1",
        success=True,
    )
    assert mode_event.old_mode == SkillExecutionMode.RESIDENT
    assert mode_event.new_mode == SkillExecutionMode.ON_DEMAND
    assert mode_event.success is True

    policy_event = GlobalPolicyChangedEvent(
        policy=GlobalPolicyMode.ALL_ON_DEMAND,
        affected_count=5,
        snapshot_path="/tmp/snapshot.toml",
    )
    assert policy_event.policy == GlobalPolicyMode.ALL_ON_DEMAND
    assert policy_event.affected_count == 5

    audit_res = AuditResult(is_compliant=True)
    audit_event = AuditCompleteEvent(skill_name="s1", audit_result=audit_res)
    assert audit_event.audit_result.is_compliant is True

    track_res = TrackResult(
        skill_name="s1",
        skill_path="/tmp/s1",
        version_status=VersionStatus.UP_TO_DATE,
    )
    version_event = VersionUpdateEvent(skill_name="s1", track_result=track_res)
    assert version_event.track_result.version_status == VersionStatus.UP_TO_DATE

    log_event = LogEvent(level="INFO", message="Test message")
    assert log_event.level == "INFO"
    assert len(log_event.timestamp) > 0
