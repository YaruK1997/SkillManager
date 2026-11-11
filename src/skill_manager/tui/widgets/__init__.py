"""TUI Widgets package for SkillManager."""

from skill_manager.tui.widgets.skill_tree import SkillTree
from skill_manager.tui.widgets.diff_viewer import DiffViewer
from skill_manager.tui.widgets.global_switch_modal import GlobalSwitchModal
from skill_manager.tui.widgets.workflow_view import WorkflowView
from skill_manager.tui.widgets.remote_search_view import RemoteSearchView

__all__ = [
    "SkillTree",
    "DiffViewer",
    "GlobalSwitchModal",
    "WorkflowView",
    "RemoteSearchView",
]
