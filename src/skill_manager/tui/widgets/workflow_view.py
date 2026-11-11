"""Workflow matrix interactive selective audit and skeleton completion widget (FR-11, AC-11)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.message import Message
from textual.widgets import Button, Label, SelectionList, Static
from textual.widgets.selection_list import Selection

from skill_manager.models import (
    WorkflowAuditResult,
    WorkflowSkillRequirement,
    WorkflowSkillStatus,
)


class WorkflowView(Container):
    """Interactive matrix for inspecting and selectively completing workflow skills."""

    DEFAULT_CSS = """
    WorkflowView {
        width: 100%;
        height: 100%;
        layout: vertical;
        padding: 1;
    }

    #workflow-header {
        text-style: bold;
        margin-bottom: 1;
    }

    #workflow-selection-list {
        height: 1fr;
        border: solid $primary;
        margin-bottom: 1;
    }

    #workflow-actions {
        height: auto;
        align: right middle;
    }

    #workflow-actions Button {
        margin-left: 1;
    }

    #workflow-status-label {
        dock: bottom;
        height: 1;
        color: $accent;
    }
    """

    class SelectiveCompletionRequested(Message):
        """Emitted when user requests completion of checked skills."""

        def __init__(self, selected_skill_names: List[str]) -> None:
            super().__init__()
            self.selected_skill_names = selected_skill_names

    def __init__(
        self,
        audit_result: Optional[WorkflowAuditResult] = None,
        workflow_path: Optional[Path | str] = None,
        id: Optional[str] = None,
    ) -> None:
        super().__init__(id=id)
        self.audit_result = audit_result
        self.workflow_path = workflow_path
        self._items: List[WorkflowSkillRequirement] = audit_result.skills if audit_result else []

    def compose(self) -> ComposeResult:
        yield Label("📋 工作流技能依賴矩陣 (Workflow Skills Matrix)", id="workflow-header")
        yield SelectionList[str](id="workflow-selection-list")
        with Horizontal(id="workflow-actions"):
            yield Button("全選 (Select All)", variant="default", id="btn-select-all")
            yield Button("全不選 (Deselect All)", variant="default", id="btn-deselect-all")
            yield Button("補全所選項目 [C]", variant="primary", id="btn-complete-selected")
        yield Label("", id="workflow-status-label")

    def on_mount(self) -> None:
        if self._items:
            self.populate_items(self._items)

    def populate_items(self, items: List[WorkflowSkillRequirement]) -> None:
        """Populate the SelectionList with workflow audit items."""
        self._items = items
        try:
            sel_list = self.query_one("#workflow-selection-list", SelectionList)
            sel_list.clear_options()

            for it in items:
                # Icon according to status
                if it.status == WorkflowSkillStatus.INSTALLED:
                    icon = "🟢 [INSTALLED]"
                    initial_state = False
                elif it.status == WorkflowSkillStatus.INCOMPLETE:
                    icon = "🟡 [INCOMPLETE]"
                    initial_state = True
                elif it.status == WorkflowSkillStatus.MISSING:
                    icon = "🔴 [MISSING]"
                    initial_state = True
                else:
                    icon = "⚪ [UNKNOWN]"
                    initial_state = False

                label = f"{icon} {it.name}"
                sel_list.add_option(Selection(label, it.name, initial_state))
        except Exception:
            pass

    def get_selected_skill_names(self) -> List[str]:
        """Return list of currently checked skill names."""
        try:
            sel_list = self.query_one("#workflow-selection-list", SelectionList)
            return list(sel_list.selected)
        except Exception:
            return []

    def on_button_pressed(self, event: Button.Pressed) -> None:
        sel_list = self.query_one("#workflow-selection-list", SelectionList)
        if event.button.id == "btn-select-all":
            sel_list.select_all()
        elif event.button.id == "btn-deselect-all":
            sel_list.deselect_all()
        elif event.button.id == "btn-complete-selected":
            selected = self.get_selected_skill_names()
            self.post_message(self.SelectiveCompletionRequested(selected))

    def update_item_status(self, skill_name: str, new_status: WorkflowSkillStatus) -> None:
        """Dynamically update an item's status in the list."""
        for it in self._items:
            if it.name == skill_name:
                it.status = new_status
        self.populate_items(self._items)
