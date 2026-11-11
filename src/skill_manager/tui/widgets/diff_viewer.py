"""DiffViewer widget with colorized unified diff rendering."""

from __future__ import annotations

from typing import Optional
from textual.containers import ScrollableContainer
from textual.widgets import Static
from rich.text import Text


class DiffViewer(ScrollableContainer):
    """Scrollable container rendering unified diff with Rich syntax highlighting."""

    DEFAULT_CSS = """
    DiffViewer {
        background: $surface-darken-1;
        border: solid $accent;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._content_widget = Static(id="diff-text-content")

    def compose(self):
        yield self._content_widget

    def show_diff(self, diff_text: str, title: Optional[str] = None) -> None:
        """Render diff lines with color styling."""
        if not diff_text.strip():
            self._content_widget.update("[dim italic]No diff changes to display.[/dim italic]")
            return

        rich_text = Text()
        if title:
            rich_text.append(f"--- {title} ---\n", style="bold yellow")

        for line in diff_text.splitlines(keepends=True):
            if line.startswith("+++ ") or line.startswith("--- "):
                rich_text.append(line, style="bold magenta")
            elif line.startswith("@@"):
                rich_text.append(line, style="bold cyan")
            elif line.startswith("+"):
                rich_text.append(line, style="green")
            elif line.startswith("-"):
                rich_text.append(line, style="red")
            else:
                rich_text.append(line, style="dim")

        self._content_widget.update(rich_text)

    def clear(self) -> None:
        """Clear current diff."""
        self._content_widget.update("")
