"""Core data models for SkillManager."""

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class VersionStatus(str, Enum):
    """Skill version control and synchronization status."""
    UP_TO_DATE = "UP_TO_DATE"
    BEHIND = "BEHIND"
    AHEAD = "AHEAD"
    DIVERGED = "DIVERGED"
    UNTRACKED = "UNTRACKED"
    CHECK_FAILED = "CHECK_FAILED"


class PlatformType(str, Enum):
    """Supported agent/assistant platforms."""
    CLAUDE = "claude"
    ANTIGRAVITY = "antigravity"
    CODEX = "codex"
    CURSOR = "cursor"
    UNIVERSAL = "universal"
    ALL = "all"


class SkillEntity(BaseModel):
    """Represents a discovered or managed skill."""
    id: str = Field(..., description="Unique skill identifier, typically dirname or namespaced")
    name: str = Field(..., description="Human-readable name parsed from metadata or directory")
    description: Optional[str] = Field(default="", description="Skill description from YAML frontmatter or index")
    platform: PlatformType = Field(default=PlatformType.UNIVERSAL, description="Target platform ecosystem")
    path: str = Field(..., description="Absolute path to the skill directory")
    has_skill_md: bool = Field(default=False, description="Whether SKILL.md exists in root")
    has_scripts: bool = Field(default=False, description="Whether scripts/ directory exists")
    has_references: bool = Field(default=False, description="Whether references/ directory exists")
    yaml_metadata: Dict[str, Any] = Field(default_factory=dict, description="Parsed YAML frontmatter")
    version_status: VersionStatus = Field(default=VersionStatus.UNTRACKED, description="Current sync status")
    commit_sha: Optional[str] = Field(default=None, description="Local Git commit SHA if git repository")
    upstream_url: Optional[str] = Field(default=None, description="Upstream Git or HuggingFace remote URL")


class ScanSummary(BaseModel):
    """Summary statistics for a scanning operation."""
    total_scanned: int = 0
    valid_skills: int = 0
    invalid_skills: int = 0


class ScanResult(BaseModel):
    """Structured result returned by the scanner module."""
    skills: List[SkillEntity] = Field(default_factory=list)
    summary: ScanSummary = Field(default_factory=ScanSummary)


class SearchItem(BaseModel):
    """Single item retrieved from remote repository search."""
    source: str = Field(..., description="'github' or 'huggingface'")
    repo_id: str = Field(..., description="Repository full name, e.g. owner/repo or HF space id")
    url: str = Field(..., description="Web URL to repository")
    description: Optional[str] = Field(default="", description="Repository brief description")
    stars_or_downloads: int = Field(default=0, description="Stars (GitHub) or downloads/likes (HF)")
    updated_at: Optional[str] = Field(default=None, description="ISO timestamp of last update")
    tags: List[str] = Field(default_factory=list, description="Repository tags/topics")


class SearchResult(BaseModel):
    """Paginated search response for remote skills."""
    items: List[SearchItem] = Field(default_factory=list)
    total_count: int = 0
    current_page: int = 1
    limit: int = 20


class AuditResult(BaseModel):
    """Outcome of checking a skill directory against index.md specifications."""
    is_compliant: bool = False
    missing_fields: List[str] = Field(default_factory=list)
    missing_sections: List[str] = Field(default_factory=list)
    missing_dirs: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)
    diff_content: Optional[str] = Field(default=None, description="Unified diff if modifications suggested")


class TrackResult(BaseModel):
    """Version tracking details for an individual skill."""
    skill_name: str
    skill_path: str
    version_status: VersionStatus
    local_commit: Optional[str] = None
    remote_commit: Optional[str] = None
    behind_count: int = 0
    diff_summary: Optional[str] = None


class WorkflowSkillStatus(str, Enum):
    """Readiness status of a required workflow skill."""
    INSTALLED = "INSTALLED"
    MISSING = "MISSING"
    INCOMPLETE = "INCOMPLETE"


class WorkflowSkillRequirement(BaseModel):
    """Represents a skill requirement declared in workflow documentation."""
    name: str = Field(..., description="Unique skill name or identifier")
    status: WorkflowSkillStatus = Field(default=WorkflowSkillStatus.MISSING, description="Current installation readiness")
    installed_path: Optional[str] = Field(default=None, description="Absolute local path if installed")
    source_path: Optional[str] = Field(default=None, description="Path where skill was restored/copied from")
    missing_sections: List[str] = Field(default_factory=list, description="Missing sections in SKILL.md if incomplete")
    missing_dirs: List[str] = Field(default_factory=list, description="Missing subdirectories if incomplete")
    description: Optional[str] = Field(default="", description="Skill purpose or workflow context")


class WorkflowCompleteResult(BaseModel):
    """Result of an automated workflow skills completion operation."""
    success: bool = True
    dry_run: bool = True
    completed_skills: List[str] = Field(default_factory=list, description="Names of skills completed or installed")
    created_skeletons: List[str] = Field(default_factory=list, description="Names of skills generated from indexer skeleton")
    modified_files: List[str] = Field(default_factory=list, description="List of all files created or updated")
    diff_summary: Optional[str] = Field(default=None, description="Consolidated unified diff of all changes")


class WorkflowAuditResult(BaseModel):
    """Comprehensive audit report comparing workflow requirements against local installation."""
    workflow_path: str = Field(..., description="Path of the audited workflow document")
    total_required: int = 0
    installed_count: int = 0
    missing_count: int = 0
    incomplete_count: int = 0
    is_fully_satisfied: bool = False
    skills: List[WorkflowSkillRequirement] = Field(default_factory=list)
    completion_result: Optional[WorkflowCompleteResult] = Field(default=None)


