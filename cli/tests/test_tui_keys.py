"""TUI key semantics: ESC backs out one level, Ctrl+C is copy-or-terminal.

Justin, 2026-09-14: ESC was closing the whole TUI from anywhere; it should do
what Left does (back to the sidebar) and only quit once you are already there.
Ctrl+C keeps copying a selection on Windows, and mashing it should close the
program like any terminal app. On macOS Cmd+C is the copy key - but a terminal
never forwards Cmd+C to the program, so the mac path is select-to-copy on
release; Ctrl+C there only carries its terminal meaning.

The decisions are pure functions so they are pinned here without Textual.
"""
from __future__ import annotations

from textual.binding import Binding
from textual.message import Message

from foundry_cli.core.ui import runner as ui


# ── ESC ────────────────────────────────────────────────────────────────


def test_escape_in_log_goes_back_to_sidebar() -> None:
    assert ui._escape_verdict("log", sidebar_visible=True) == "back"


def test_escape_in_fullscreen_log_restores_sidebar_first() -> None:
    assert ui._escape_verdict("log", sidebar_visible=False) == "exit_fullscreen"


def test_escape_on_sidebar_quits() -> None:
    assert ui._escape_verdict("list", sidebar_visible=True) == "quit"


# ── Ctrl+C ─────────────────────────────────────────────────────────────


def test_ctrl_c_copies_whenever_something_is_selected() -> None:
    assert ui._ctrl_c_verdict("log", True, None) == "copy"
    assert ui._ctrl_c_verdict("list", True, None) == "copy"
    # even a rapid second press copies rather than quits when text is selected
    assert ui._ctrl_c_verdict("log", True, 0.2) == "copy"


def test_ctrl_c_on_sidebar_quits_on_a_single_press() -> None:
    assert ui._ctrl_c_verdict("list", False, None) == "quit"


def test_ctrl_c_in_log_hints_first_then_quits_on_a_quick_second_press() -> None:
    assert ui._ctrl_c_verdict("log", False, None) == "hint"
    assert ui._ctrl_c_verdict("log", False, ui.CTRL_C_QUIT_WINDOW) == "quit"
    assert ui._ctrl_c_verdict("log", False, ui.CTRL_C_QUIT_WINDOW + 0.1) == "hint"


# ── platform defaults + overrides ──────────────────────────────────────


def test_select_to_copy_defaults_to_macos_only() -> None:
    assert ui._copy_on_select({}, "darwin") is True
    assert ui._copy_on_select({}, "win32") is False
    assert ui._copy_on_select({}, "linux") is False


def test_select_to_copy_env_override() -> None:
    assert ui._copy_on_select({"FOUNDRY_TUI_COPY_ON_SELECT": "1"}, "win32") is True
    assert ui._copy_on_select({"FOUNDRY_TUI_COPY_ON_SELECT": "0"}, "darwin") is False
    assert ui._copy_on_select({"FOUNDRY_TUI_COPY_ON_SELECT": "garbage"}, "darwin") is True


def test_ctrl_c_is_the_copy_key_everywhere_but_macos() -> None:
    assert ui._ctrl_c_copies({}, "win32") is True
    assert ui._ctrl_c_copies({}, "linux") is True
    assert ui._ctrl_c_copies({}, "darwin") is False


def test_ctrl_c_meaning_env_override() -> None:
    assert ui._ctrl_c_copies({"FOUNDRY_TUI_CTRL_C": "copy"}, "darwin") is True
    assert ui._ctrl_c_copies({"FOUNDRY_TUI_CTRL_C": "quit"}, "win32") is False


# ── wiring ─────────────────────────────────────────────────────────────


def _binding(key: str) -> Binding:
    for b in ui.ServicesUI.BINDINGS:
        if isinstance(b, Binding) and b.key == key:
            return b
    raise AssertionError(f"no binding for {key}")


def test_escape_and_ctrl_c_are_routed_through_the_verdict_actions() -> None:
    esc = _binding("escape")
    assert esc.action == "escape" and esc.priority and esc.description == "Back / Quit"
    ctrl_c = _binding("ctrl+c")
    assert ctrl_c.action == "ctrl_c" and ctrl_c.priority
    # the footer tells the truth for THIS host
    assert ctrl_c.description == ("Copy / Quit" if ui._ctrl_c_copies() else "Quit")


def test_left_arrow_and_escape_share_the_back_action() -> None:
    assert _binding("left").action == "unfocus"
    assert hasattr(ui.ServicesUI, "action_unfocus")
    assert hasattr(ui.ServicesUI, "action_escape")


def test_drag_release_is_announced_as_a_message() -> None:
    assert issubclass(ui.SelectableRichLog.DragSelected, Message)
    assert hasattr(ui.ServicesUI, "on_selectable_rich_log_drag_selected")
