"""Textual TUI Application for SkillManager (FR-10, EC-14, NFR-06)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.events import Resize
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
)

from skill_manager.config import AppConfig
from skill_manager.core.async_adapter import (
    async_audit_skill,
    async_complete_skill,
    async_scan_skills,
    async_toggle_skill_mode,
)
from skill_manager.core.platform_open import open_folder_in_file_manager
from skill_manager.models import (
    AuditResult,
    PlatformType,
    ScanResult,
    SkillEntity,
    SkillExecutionMode,
)


TUI_CSS = """
Screen {
    background: $surface;
    color: $text;
}

#size-warning {
    display: none;
    width: 100%;
    height: 100%;
    content-align: center middle;
    text-align: center;
    background: $error-darken-3;
    color: $text;
    text-style: bold;
}

#main-container {
    width: 100%;
    height: 100%;
    layout: vertical;
}

#filter-input {
    dock: top;
    margin: 0 1;
}

#content-split {
    width: 100%;
    height: 1fr;
    layout: horizontal;
}

#left-column {
    width: 35%;
    min-width: 25;
    height: 100%;
    border-right: solid $primary;
    padding: 0 1;
}

#right-column {
    width: 65%;
    height: 100%;
    layout: vertical;
    padding: 0 1;
}

#metadata-panel {
    height: 45%;
    border-bottom: solid $accent;
    overflow-y: auto;
    padding: 1;
}

#diff-panel {
    height: 55%;
    overflow-y: auto;
    padding: 1;
    background: $surface-darken-1;
}

.badge-resident {
    color: $success;
}

.badge-ondemand {
    color: $warning;
}

.badge-broken {
    color: $error;
}
"""


class SkillManagerApp(App):
    """Full-featured interactive TUI dashboard for local AI skills."""

    TITLE = "SkillManager Dashboard"
    SUB_TITLE = "v0.3.0"
    CSS = TUI_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, priority=True),
        Binding("slash", "focus_filter", "Filter", show=True),
        Binding("tab", "next_tab", "Next Tab", show=True),
        Binding("1", "select_tab('tab-skills')", "Skills", show=False),
        Binding("2", "select_tab('tab-workflows')", "Workflows", show=False),
        Binding("3", "select_tab('tab-remote')", "Remote", show=False),
        Binding("4", "select_tab('tab-audit')", "Audit/Diff", show=False),
        Binding("space", "toggle_mode", "Toggle Mode", show=True),
        Binding("m", "toggle_mode", "Toggle Mode", show=False),
        Binding("g", "global_policy", "Global Switch", show=True),
        Binding("a", "audit_skill", "Audit", show=True),
        Binding("c", "complete_skill", "Complete", show=True),
        Binding("u", "upgrade_skill", "Upgrade", show=True),
        Binding("r", "rollback_skill", "Rollback", show=False),
        Binding("o", "open_folder", "Open Folder", show=True),
    ]

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        custom_paths: Optional[List[str]] = None,
        platform: PlatformType = PlatformType.ALL,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.config = config or AppConfig()
        self.custom_paths = custom_paths
        self.platform = platform
        self.skills: List[SkillEntity] = []
        self.selected_skill: Optional[SkillEntity] = None
        self.is_screen_too_small: bool = False

    def compose(self) -> ComposeResult:
        """Compose root layout."""
        yield Header(show_clock=True)
        yield Static(
            "⚠️ Terminal size too small.\nPlease resize to at least 80x24.",
            id="size-warning",
        )
        with Container(id="main-container"):
            with TabbedContent(id="tabs"):
                with TabPane("Skills [1]", id="tab-skills"):
                    yield Input(placeholder="Search / filter skills (Press '/' to focus)...", id="filter-input")
                    with Horizontal(id="content-split"):
                        with Vertical(id="left-column"):
                            yield Label("[b]Skills List[/b]")
                            yield ListView(id="skill-list-view")
                        with Vertical(id="right-column"):
                            yield ScrollableContainer(
                                Static("[dim]Select a skill to inspect metadata...[/dim]", id="metadata-panel")
                            )
                            yield ScrollableContainer(
                                Static("[dim]Unified diff & health view...[/dim]", id="diff-panel")
                            )
                with TabPane("Workflows [2]", id="tab-workflows"):
                    yield Static("Workflow auditor view placeholder", id="workflow-panel")
                with TabPane("Remote Search [3]", id="tab-remote"):
                    yield Static("Remote search view placeholder", id="remote-panel")
                with TabPane("Audit / Diff [4]", id="tab-audit"):
                    yield Static("Batch audit & compliance report", id="batch-audit-panel")
        yield Footer()

    async def on_mount(self) -> None:
        """Mount event hook: check initial dimensions and launch background scan."""
        if self.size:
            self.check_terminal_size(self.size.width, self.size.height)
        self.run_worker(self._async_load_skills(), exclusive=True)

    def on_resize(self, event: Resize) -> None:
        """Handle screen resizing to detect sub-80x24 boundary (EC-14)."""
        self.check_terminal_size(event.size.width, event.size.height)

    def check_terminal_size(self, width: int, height: int) -> bool:
        """Verify window dimensions and trigger EC-14 size warning if needed."""
        too_small = width < 80 or height < 24
        self.is_screen_too_small = too_small
        try:
            warning = self.query_one("#size-warning", Static)
            main_box = self.query_one("#main-container", Container)
            if too_small:
                warning.display = True
                main_box.display = False
                warning.update(
                    f"⚠️ Terminal size too small ({width}x{height})!\n"
                    f"Please resize terminal to at least 80x24 to prevent layout distortion."
                )
            else:
                warning.display = False
                main_box.display = True
        except Exception:
            pass
        return too_small

    async def _async_load_skills(self) -> None:
        """Background worker to scan skills without blocking UI (NFR-06)."""
        try:
            if not self.skills:
                res: ScanResult = await async_scan_skills(
                    platform=self.platform,
                    custom_paths=self.custom_paths,
                    config=self.config,
                )
                self.skills = res.skills
            self._update_skill_list()
        except Exception as e:
            self.notify(f"Failed to scan skills: {e}", severity="error")

    def _update_skill_list(self, filter_text: str = "") -> None:
        """Populate the skill ListView with status badges."""
        try:
            list_view = self.query_one("#skill-list-view", ListView)
            list_view.clear()
            filter_lower = filter_text.strip().lower()
            filtered = [s for s in self.skills if filter_lower in s.name.lower() or filter_lower in s.id.lower()]

            for skill in filtered:
                mode_icon = "📌" if skill.execution_mode == SkillExecutionMode.RESIDENT else "⚡"
                health_icon = "🟢" if skill.has_skill_md else "🔴"
                item_label = f"{health_icon} {mode_icon} {skill.name}"
                item = ListItem(Label(item_label), id=f"skill-item-{skill.id}")
                list_view.append(item)

            if filtered:
                if not self.selected_skill or self.selected_skill not in filtered:
                    self.selected_skill = filtered[0]
                self._update_detail_panels()
        except Exception:
            pass

    def _update_detail_panels(self) -> None:
        """Update metadata panel and diff panel for selected skill."""
        if not self.selected_skill:
            return
        try:
            meta = self.query_one("#metadata-panel", Static)
            s = self.selected_skill
            mode_badge = "RESIDENT [📌 全域常駐]" if s.execution_mode == SkillExecutionMode.RESIDENT else "ON_DEMAND [⚡ 特定時機調用]"
            text = (
                f"[bold cyan]{s.name}[/bold cyan] ({s.id})\n"
                f"• Path: [dim]{s.path}[/dim]\n"
                f"• Execution Mode: [bold yellow]{mode_badge}[/bold yellow]\n"
                f"• Platform: {s.platform.value}\n"
                f"• Description: {s.description or 'No description provided.'}\n"
                f"• Health: {'Valid' if s.has_skill_md else 'Missing SKILL.md'}\n"
            )
            meta.update(text)
        except Exception:
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection in skill ListView."""
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self.skills):
            self.selected_skill = self.skills[idx]
            self._update_detail_panels()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter skills on input change."""
        if event.input.id == "filter-input":
            self._update_skill_list(filter_text=event.value)

    def action_focus_filter(self) -> None:
        """Action: Focus search filter input."""
        try:
            self.query_one("#filter-input", Input).focus()
        except Exception:
            pass

    def action_next_tab(self) -> None:
        """Action: Cycle to next tab."""
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            tab_ids = ["tab-skills", "tab-workflows", "tab-remote", "tab-audit"]
            curr = tabs.active
            if curr in tab_ids:
                next_idx = (tab_ids.index(curr) + 1) % len(tab_ids)
                tabs.active = tab_ids[next_idx]
        except Exception:
            pass

    def action_select_tab(self, tab_id: str) -> None:
        """Action: Directly select tab by ID."""
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            tabs.active = tab_id
        except Exception:
            pass

    async def action_toggle_mode(self) -> None:
        """Action: Toggle execution mode of selected skill (Space/M)."""
        if not self.selected_skill:
            self.notify("No skill selected", severity="warning")
            return
        s = self.selected_skill
        target = (
            SkillExecutionMode.ON_DEMAND
            if s.execution_mode == SkillExecutionMode.RESIDENT
            else SkillExecutionMode.RESIDENT
        )
        try:
            ev = await async_toggle_skill_mode(s.path, target)
            if ev.success:
                s.execution_mode = target
                self.notify(f"Switched {s.name} to {target.value}", severity="information")
                self._update_skill_list()
                self._update_detail_panels()
            else:
                self.notify(f"Failed to switch mode: {ev.error_message}", severity="error")
        except Exception as e:
            self.notify(f"Error toggling mode: {e}", severity="error")

    def action_open_folder(self) -> None:
        """Action: Open selected skill folder in native file manager (O key, FR-14)."""
        if not self.selected_skill:
            self.notify("No skill selected", severity="warning")
            return
        success = open_folder_in_file_manager(self.selected_skill.path)
        if success:
            self.notify(f"Opened folder: {self.selected_skill.path}", severity="information")
        else:
            self.notify("Failed to open folder", severity="error")

    async def action_audit_skill(self) -> None:
        """Action: Audit selected skill and display diff in bottom right panel."""
        if not self.selected_skill:
            self.notify("No skill selected", severity="warning")
            return
        try:
            diff_panel = self.query_one("#diff-panel", Static)
            diff_panel.update("[yellow]Auditing skill structure...[/yellow]")
            res: AuditResult = await async_audit_skill(self.selected_skill.path)
            lines = [f"[bold]Audit for {self.selected_skill.name}:[/bold]"]
            lines.append(f"Compliant: {'✅ YES' if res.is_compliant else '❌ NO'}")
            if res.missing_fields:
                lines.append(f"Missing Fields: [red]{', '.join(res.missing_fields)}[/red]")
            if res.missing_sections:
                lines.append(f"Missing Sections: [red]{', '.join(res.missing_sections)}[/red]")
            if res.missing_dirs:
                lines.append(f"Missing Dirs: [yellow]{', '.join(res.missing_dirs)}[/yellow]")
            diff_panel.update("\n".join(lines))
        except Exception as e:
            self.notify(f"Audit error: {e}", severity="error")

    async def action_complete_skill(self) -> None:
        """Action: Complete selected skill structure and show generated diff."""
        if not self.selected_skill:
            self.notify("No skill selected", severity="warning")
            return
        try:
            diff_panel = self.query_one("#diff-panel", Static)
            diff_panel.update("[yellow]Generating completion preview...[/yellow]")
            success, diff_str, files = await async_complete_skill(self.selected_skill.path, dry_run=True)
            if diff_str:
                diff_panel.update(f"[bold cyan]Preview Diff (Dry-run):[/bold cyan]\n```diff\n{diff_str}\n```")
            else:
                diff_panel.update("[green]Skill is already complete and compliant![/green]")
        except Exception as e:
            self.notify(f"Completion error: {e}", severity="error")

    def action_global_policy(self) -> None:
        """Action: Open Global Policy Switch modal."""
        self.notify("Global policy modal triggered", severity="information")

    def action_upgrade_skill(self) -> None:
        """Action: Upgrade skill."""
        self.notify("Upgrade action triggered", severity="information")

    def action_rollback_skill(self) -> None:
        """Action: Rollback skill."""
        self.notify("Rollback action triggered", severity="information")
