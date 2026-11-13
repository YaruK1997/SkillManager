"""Typed UI and business events for SkillManager decoupling and async bus."""

from dataclasses import dataclass, field
import datetime as dt
from enum import Enum
from typing import Any, Dict, List, Optional
from skill_manager.models import (
    SkillEntity,
    AuditResult,
    TrackResult,
    SkillExecutionMode,
    GlobalPolicyMode,
)


class UIMode(str, Enum):
    """UI presentation mode."""
    CLI = "cli"
    TUI = "tui"


@dataclass
class ScanProgressEvent:
    current_path: str
    scanned_count: int
    valid_count: int


@dataclass
class SkillSelectedEvent:
    skill: SkillEntity


@dataclass
class SkillModeChangedEvent:
    skill_name: str
    platform: str
    old_mode: SkillExecutionMode
    new_mode: SkillExecutionMode
    skill_path: str = ""
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class GlobalPolicyChangedEvent:
    policy: GlobalPolicyMode
    affected_count: int
    snapshot_path: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class AuditCompleteEvent:
    skill_name: str
    audit_result: AuditResult


@dataclass
class VersionUpdateEvent:
    skill_name: str
    track_result: TrackResult


@dataclass
class LogEvent:
    level: str  # "DEBUG", "INFO", "WARNING", "ERROR", "MODE"
    message: str
    timestamp: str = field(default_factory=lambda: dt.datetime.now().strftime("%H:%M:%S"))
