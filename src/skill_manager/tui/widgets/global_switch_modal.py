"""Modal dialog for global execution policy switching (FR-08, AC-08)."""

from __future__ import annotations

from typing import Optional
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet

from skill_manager.models import GlobalPolicyMode


class GlobalSwitchModal(ModalScreen[Optional[GlobalPolicyMode]]):
    """Modal screen allowing the user to select and apply a global policy mode."""

    DEFAULT_CSS = """
    GlobalSwitchModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }

    #modal-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #dialog-buttons {
        margin-top: 1;
        align: right middle;
    }

    #dialog-buttons Button {
        margin-left: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label("🌐 全域技能執行模式切換 (Global Switch)", id="dialog-title")
            yield Label("請選擇欲套用至所有技能之全域策略：", id="dialog-desc")
            with RadioSet(id="policy-radios"):
                yield RadioButton(
                    "📌 全域常駐執行 (ALL_RESIDENT)",
                    value=True,
                    id="radio-resident",
                )
                yield RadioButton(
                    "⚡ 特定時機調用 (ALL_ON_DEMAND)",
                    id="radio-ondemand",
                )
                yield RadioButton(
                    "🔄 還原前次快照 (RESTORE_LAST)",
                    id="radio-restore",
                )
            with Horizontal(id="dialog-buttons"):
                yield Button("取消 (Cancel)", variant="default", id="btn-cancel")
                yield Button("確認套用 (Apply)", variant="primary", id="btn-apply")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return

        radios = self.query_one("#policy-radios", RadioSet)
        idx = radios.pressed_index
        if idx == 0:
            selected_policy = GlobalPolicyMode.ALL_RESIDENT
        elif idx == 1:
            selected_policy = GlobalPolicyMode.ALL_ON_DEMAND
        elif idx == 2:
            selected_policy = GlobalPolicyMode.RESTORE_LAST
        else:
            selected_policy = GlobalPolicyMode.ALL_RESIDENT

        self.dismiss(selected_policy)
