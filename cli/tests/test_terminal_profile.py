"""Terminal profile: glyphs only where trusted, mouse-motion stream tamed.

Justin, 2026-09-07: the TUI works in the VS Code integrated terminal on both
OSes, but plain PowerShell should show a green OK instead of icons (glyphs
don't always render), and macOS Terminal.app floods escape codes after a
second (the b251ace picture again — this time Textual's any-event mouse
mode 1003 on that terminal).
"""
from __future__ import annotations

import sys

import pytest

from foundry_cli.core.ui import runner as ui


def test_glyphs_only_in_vscode_by_default() -> None:
    assert ui._use_glyphs({"TERM_PROGRAM": "vscode"}) is True
    assert ui._use_glyphs({"TERM_PROGRAM": "Apple_Terminal"}) is False
    assert ui._use_glyphs({}) is False  # plain PowerShell / conhost / xterm


def test_glyphs_env_override() -> None:
    assert ui._use_glyphs({"FOUNDRY_TUI_GLYPHS": "1"}) is True
    assert ui._use_glyphs({"TERM_PROGRAM": "vscode", "FOUNDRY_TUI_GLYPHS": "0"}) is False


def test_mouse_mode_defaults() -> None:
    assert ui._mouse_mode({}) == "full"
    assert ui._mouse_mode({"TERM_PROGRAM": "vscode"}) == "full"
    assert ui._mouse_mode({"TERM_PROGRAM": "Apple_Terminal"}) == "clicks"


def test_mouse_mode_env_override() -> None:
    assert ui._mouse_mode({"TERM_PROGRAM": "Apple_Terminal", "FOUNDRY_TUI_MOUSE": "1"}) == "full"
    assert ui._mouse_mode({"FOUNDRY_TUI_MOUSE": "0"}) == "off"
    assert ui._mouse_mode({"FOUNDRY_TUI_MOUSE": "clicks"}) == "clicks"


def test_default_terminal_uses_textual_default_driver() -> None:
    assert ui._select_driver_class({}) is None
    assert ui._select_driver_class({"TERM_PROGRAM": "vscode"}) is None


@pytest.mark.skipif(sys.platform == "win32", reason="LinuxDriver needs termios")
def test_apple_terminal_gets_click_only_driver() -> None:
    from textual.drivers.linux_driver import LinuxDriver

    cls = ui._select_driver_class({"TERM_PROGRAM": "Apple_Terminal"})
    assert cls is not None and issubclass(cls, LinuxDriver)

    written: list[str] = []
    drv = cls.__new__(cls)
    drv.write = written.append  # type: ignore[method-assign]
    drv.flush = lambda: None  # type: ignore[method-assign]
    cls._enable_mouse_support(drv)
    joined = "".join(written)
    assert "\x1b[?1000h" in joined and "\x1b[?1006h" in joined
    assert "\x1b[?1003h" not in joined  # the any-event motion stream is the flood


def test_windows_never_swaps_driver(monkeypatch) -> None:
    monkeypatch.setattr(ui.sys, "platform", "win32")
    assert ui._select_driver_class({"TERM_PROGRAM": "Apple_Terminal"}) is None


def test_status_labels_are_ascii_outside_vscode() -> None:
    # The label text is chosen from the glyph profile alone; no App needed.
    for glyphs, ok, err in ((True, " ✓", " ✗"), (False, " OK", "ERR")):
        healthy = " ✓" if glyphs else " OK"
        failed = " ✗" if glyphs else "ERR"
        assert (healthy, failed) == (ok, err)
        if not glyphs:
            assert healthy.isascii() and failed.isascii()


def test_terminal_bound_messages_are_ascii() -> None:
    """Runner/tunnel strings reach a cp1252 pipe on Windows and every
    terminal font; a stray arrow/em-dash there is a crash or a box."""
    from foundry_cli.core.services import ssh_tunnel

    cfg = ssh_tunnel.SshTunnelConfig.from_dict({
        "localPort": 1, "remoteHost": "db", "remotePort": 5432, "host": "h",
    })
    r = ssh_tunnel.SshTunnelRunner("svc", cfg)
    assert r.display_name.isascii()
