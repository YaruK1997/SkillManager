"""Unit tests for TUI Widgets (T-S2-06-TUI-WIDGETS, FR-10, FR-11, FR-12, AC-10, AC-11, AC-12, EC-12)."""

import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from textual.app import App, ComposeResult
from textual.widgets import SelectionList

from skill_manager.models import (
    PlatformType,
    SkillEntity,
    SkillExecutionMode,
    GlobalPolicyMode,
    SearchItem,
    SearchResult,
    WorkflowAuditResult,
    WorkflowSkillRequirement,
    WorkflowSkillStatus,
)
from skill_manager.tui.widgets.skill_tree import SkillTree
from skill_manager.tui.widgets.diff_viewer import DiffViewer
from skill_manager.tui.widgets.global_switch_modal import GlobalSwitchModal
from skill_manager.tui.widgets.workflow_view import WorkflowView
from skill_manager.tui.widgets.remote_search_view import RemoteSearchView


# ---------------------------------------------------------------------------
# 1. SkillTree Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_skill_tree_badges_and_grouping(tmp_path):
    class TreeTestApp(App):
        def compose(self) -> ComposeResult:
            yield SkillTree(id="test-tree")

    s1 = SkillEntity(
        id="s1",
        name="Skill 1",
        platform=PlatformType.CLAUDE,
        path=str(tmp_path / "s1"),
        has_skill_md=True,
        execution_mode=SkillExecutionMode.RESIDENT,
    )
    s2 = SkillEntity(
        id="s2",
        name="Skill 2",
        platform=PlatformType.ANTIGRAVITY,
        path=str(tmp_path / "s2"),
        has_skill_md=False,
        execution_mode=SkillExecutionMode.ON_DEMAND,
    )

    app = TreeTestApp()
    async with app.run_test() as pilot:
        tree = app.query_one("#test-tree", SkillTree)
        tree.populate([s1, s2])

        # Verify root children (platforms Claude and Gemini)
        assert len(tree.root.children) == 2
        claude_node = [c for c in tree.root.children if "Claude" in str(c.label)][0]
        assert len(claude_node.children) == 1
        leaf = claude_node.children[0]
        assert "📌" in str(leaf.label)  # Resident badge
        assert "🟢" in str(leaf.label)  # Health valid badge

        antigravity_node = [c for c in tree.root.children if "Antigravity" in str(c.label)][0]
        leaf2 = antigravity_node.children[0]
        assert "⚡" in str(leaf2.label)  # On demand badge
        assert "🔴" in str(leaf2.label)  # Health broken badge


# ---------------------------------------------------------------------------
# 2. DiffViewer Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_diff_viewer_render():
    class DiffTestApp(App):
        def compose(self) -> ComposeResult:
            yield DiffViewer(id="test-diff")

    app = DiffTestApp()
    async with app.run_test() as pilot:
        diff_widget = app.query_one("#test-diff", DiffViewer)
        diff_content = (
            "--- SKILL.md (orig)\n"
            "+++ SKILL.md (comp)\n"
            "@@ -1,3 +1,5 @@\n"
            "-old text\n"
            "+new text\n"
            " context line\n"
        )
        diff_widget.show_diff(diff_content, title="SKILL.md")
        rendered = str(diff_widget._content_widget.render())
        assert "new text" in rendered

        diff_widget.clear()
        assert str(diff_widget._content_widget.render()) == ""


# ---------------------------------------------------------------------------
# 3. GlobalSwitchModal Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_global_switch_modal():
    modal = GlobalSwitchModal()

    class ModalHostApp(App):
        def compose(self) -> ComposeResult:
            yield modal

    app = ModalHostApp()
    async with app.run_test() as pilot:
        assert app.query_one("#modal-dialog") is not None
        assert app.query_one("#radio-resident") is not None
        assert app.query_one("#radio-ondemand") is not None
        assert app.query_one("#radio-restore") is not None


# ---------------------------------------------------------------------------
# 4. WorkflowView Tests (FR-11, AC-11)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_workflow_view_selective_completion():
    items = [
        WorkflowSkillRequirement(name="skill-a", status=WorkflowSkillStatus.INSTALLED),
        WorkflowSkillRequirement(name="skill-b", status=WorkflowSkillStatus.MISSING),
        WorkflowSkillRequirement(name="skill-c", status=WorkflowSkillStatus.MISSING),
        WorkflowSkillRequirement(name="skill-d", status=WorkflowSkillStatus.INCOMPLETE),
        WorkflowSkillRequirement(name="skill-e", status=WorkflowSkillStatus.INSTALLED),
    ]
    audit_res = WorkflowAuditResult(
        workflow_path="workflow.md",
        total_required=5,
        installed_count=2,
        missing_count=2,
        incomplete_count=1,
        skills=items,
    )

    messages = []

    class WorkflowHostApp(App):
        def compose(self) -> ComposeResult:
            yield WorkflowView(audit_result=audit_res, id="wf-view")

        def on_workflow_view_selective_completion_requested(
            self, event: WorkflowView.SelectiveCompletionRequested
        ) -> None:
            messages.append(event.selected_skill_names)

    app = WorkflowHostApp()
    async with app.run_test() as pilot:
        wf = app.query_one("#wf-view", WorkflowView)
        sel_list = wf.query_one("#workflow-selection-list", SelectionList)

        # Deselect all, then selectively select only 'skill-b' (AC-11)
        sel_list.deselect_all()
        sel_list.select("skill-b")

        assert wf.get_selected_skill_names() == ["skill-b"]

        # Trigger complete button
        btn = wf.query_one("#btn-complete-selected")
        btn.press()
        await pilot.pause()

        assert len(messages) == 1
        assert messages[0] == ["skill-b"]

        # Dynamic status update to INSTALLED (AC-11)
        wf.update_item_status("skill-b", WorkflowSkillStatus.INSTALLED)
        updated_item = [it for it in wf._items if it.name == "skill-b"][0]
        assert updated_item.status == WorkflowSkillStatus.INSTALLED


# ---------------------------------------------------------------------------
# 5. RemoteSearchView Tests (FR-12, AC-12, EC-12)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_remote_search_view_debounce_and_timeout():
    class RemoteHostApp(App):
        def compose(self) -> ComposeResult:
            yield RemoteSearchView(debounce_ms=50, id="remote-view")

    app = RemoteHostApp()
    with patch("skill_manager.tui.widgets.remote_search_view.async_search_remote") as mock_search:
        mock_search.return_value = SearchResult(
            items=[
                SearchItem(
                    source="github",
                    repo_id="user/skill-foo",
                    url="https://github.com/user/skill-foo",
                    stars_or_downloads=120,
                    description="Awesome skill",
                ),
            ],
            total_count=1,
            current_page=1,
            limit=20,
        )

        async with app.run_test() as pilot:
            rview = app.query_one("#remote-view", RemoteSearchView)
            input_box = rview.query_one("#remote-search-input")

            # Simulate typing
            input_box.value = "skill-foo"
            # Wait for 50ms debounce
            await asyncio.sleep(0.1)
            await pilot.pause()

            # Verify search was performed
            assert mock_search.called

            # Test EC-12: Simulated timeout exception
            mock_search.side_effect = TimeoutError("HTTP Connection timed out")
            input_box.value = "skill-bar"
            await asyncio.sleep(0.1)
            await pilot.pause()

            status_lbl = rview.query_one("#remote-status-bar")
            assert "timeout" in str(status_lbl.render()).lower() or "error" in str(status_lbl.render()).lower()
