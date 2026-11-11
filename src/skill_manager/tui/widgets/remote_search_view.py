"""Remote skills marketplace search widget with debounce and timeout handling (FR-12, AC-12, EC-12)."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    LoadingIndicator,
    Select,
    Static,
)

from skill_manager.core.async_adapter import async_search_remote
from skill_manager.models import SearchItem, SearchResult


class RemoteSearchView(Container):
    """Remote skills search interface with 300ms debounce and non-blocking worker."""

    DEFAULT_CSS = """
    RemoteSearchView {
        width: 100%;
        height: 100%;
        layout: vertical;
        padding: 1;
    }

    #search-bar {
        height: auto;
        layout: horizontal;
        margin-bottom: 1;
    }

    #remote-search-input {
        width: 70%;
    }

    #remote-source-select {
        width: 30%;
        margin-left: 1;
    }

    #remote-data-table {
        height: 1fr;
        border: solid $accent;
    }

    #remote-status-bar {
        height: 1;
        dock: bottom;
        color: $text-muted;
    }

    #remote-loading {
        display: none;
        height: 1;
    }
    """

    class InstallSkillRequested(Message):
        """Emitted when user wants to install a selected remote skill."""

        def __init__(self, item: SearchItem) -> None:
            super().__init__()
            self.item = item

    def __init__(self, debounce_ms: int = 300, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self.debounce_seconds = debounce_ms / 1000.0
        self._search_timer: Optional[asyncio.TimerHandle] = None
        self._current_items: List[SearchItem] = []
        self._search_count: int = 0

    def compose(self) -> ComposeResult:
        yield Label("🌐 遠端技能市集 (Remote Marketplace)", id="remote-header")
        with Horizontal(id="search-bar"):
            yield Input(placeholder="Search GitHub & HuggingFace skills...", id="remote-search-input")
            yield Select(
                [("All Sources", "all"), ("GitHub", "github"), ("HuggingFace", "huggingface")],
                value="all",
                id="remote-source-select",
                allow_blank=False,
            )
        yield LoadingIndicator(id="remote-loading")
        yield DataTable(id="remote-data-table")
        yield Label("[dim]Ready to search.[/dim]", id="remote-status-bar")

    def on_mount(self) -> None:
        table = self.query_one("#remote-data-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Source", "Repo / ID", "Stars", "Description")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounced input trigger (300ms, NFR-07, AC-12)."""
        if event.input.id == "remote-search-input":
            query = event.value.strip()
            if len(query) < 2:
                return

            # Cancel previous debounce timer if pending
            if self._search_timer:
                self._search_timer.cancel()

            loop = asyncio.get_event_loop()
            self._search_timer = loop.call_later(
                self.debounce_seconds,
                lambda: self.run_worker(self._perform_search(query), exclusive=True),
            )

    async def _perform_search(self, query: str) -> None:
        """Worker that executes remote search with timeout guard (EC-12)."""
        loading = self.query_one("#remote-loading", LoadingIndicator)
        status_lbl = self.query_one("#remote-status-bar", Label)
        table = self.query_one("#remote-data-table", DataTable)

        source_select = self.query_one("#remote-source-select", Select)
        source = str(source_select.value) if source_select.value else "all"

        loading.display = True
        status_lbl.update(f"Searching for '{query}'...")

        try:
            res: SearchResult = await async_search_remote(
                query=query,
                source=source,
                limit=20,
                timeout=5.0,
            )
            self._current_items = res.items
            table.clear()

            for it in res.items:
                source_badge = "🐙 GH" if it.source == "github" else "🤗 HF"
                table.add_row(
                    source_badge,
                    it.repo_id,
                    f"⭐ {it.stars_or_downloads}",
                    it.description[:60] if it.description else "",
                    key=it.repo_id,
                )

            status_lbl.update(f"Found {len(res.items)} skills matching '{query}'.")
        except Exception as e:
            # EC-12: Handle timeout or network failure without freezing
            status_lbl.update(f"⚠️ Search error or network timeout: {e}")
        finally:
            loading.display = False

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection to trigger install."""
        idx = event.cursor_row
        if 0 <= idx < len(self._current_items):
            self.post_message(self.InstallSkillRequested(self._current_items[idx]))
