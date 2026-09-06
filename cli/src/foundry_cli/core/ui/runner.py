# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual import events
from textual.theme import Theme
from textual.widgets import Label, ListItem, ListView, RichLog, Static
from rich.ansi import AnsiDecoder
from rich.markup import escape
from rich.text import Text
import webbrowser

from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runners.base import (
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)
from foundry_cli.core.services.runners.tunnel_aware import TunnelAwareRunner

from foundry_cli.core.util.logger import LogLine, format_log_line

from foundry_cli.release.versioning import get_local_version
from foundry_cli.release.update_check import check_for_updates


def _sanitize_id(name: str) -> str:
    """Sanitize a name to be a valid Textual widget ID.
    
    IDs can only contain letters, numbers, underscores, and hyphens,
    and must not start with a number.
    """
    # Replace common separators with hyphens
    result = name.replace(" ", "-").replace("/", "-").replace(".", "-")
    # Remove any remaining invalid characters
    result = re.sub(r"[^a-zA-Z0-9_-]", "", result)
    # Ensure it doesn't start with a number
    if result and result[0].isdigit():
        result = f"s-{result}"
    return result or "unknown"


def _win32_set_clipboard(text: str) -> None:
    """Set CF_UNICODETEXT via the Win32 clipboard API (no subprocess, no BOM)."""
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    # 64-bit safety: default ctypes restype is a 32-bit int — pointers truncate.
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise OSError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise OSError("GlobalAlloc failed")
        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            raise OSError("GlobalLock failed")
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise OSError("SetClipboardData failed")
        # Ownership of the handle passed to the clipboard — do not free it.
    finally:
        user32.CloseClipboard()


def _copy_text_to_clipboard(text: str) -> str | None:
    """Copy text to the system clipboard. Returns an error message, or None on success.

    Tries pyperclip if installed, then the platform's native clipboard command.
    Used instead of Textual's OSC-52 `copy_to_clipboard` because terminal
    support for OSC-52 is spotty (notably older Windows terminals).
    """
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return None
    except Exception:
        pass

    try:
        if sys.platform == "win32":
            try:
                _win32_set_clipboard(text)
                return None
            except Exception:
                # clip.exe fallback: a UTF-16 BOM makes it decode as Unicode
                # (the BOM lands in the clipboard text — acceptable for a fallback).
                subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
                return None
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return None
        for cmd in (
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                return None
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        return "no clipboard tool found (install xclip, xsel, or wl-clipboard)"
    except Exception as e:
        return str(e)


def _print_update_banner_to_log(log_list, local: str, latest: str, url: str | None) -> None:
    log_list.append(Text.from_markup("[#3B8EEA bold]-----------------------------------------------------------------------[/]"))
    line = (
        Text.from_markup("[#D670D6 bold]Update available: [/]" +
            f"[#F14C4C bold]{local}[/][#F5F536 bold] → [/][#23D18B bold]{latest}[/]")
    )
    log_list.append(line)
    if url:
        log_list.append(Text.from_markup(f"[#29B8DB]Download: {url}[/]"))
    else:
        log_list.append(Text.from_markup("[#29B8DB]Run the latest installer from GitHub Releases to upgrade.[/]"))
    log_list.append(Text.from_markup("[#3B8EEA bold]-----------------------------------------------------------------------[/]"))


@dataclass(frozen=True)
class ServiceRunnerState:
    name: str
    runner: ServiceRunner
    start_task: asyncio.Task[None]
    pump_task: asyncio.Task[None]
    status_task: asyncio.Task[None]


# The exact palette Textual 0.56.4's default dark design generated — the look
# this TUI shipped with. Registered as an explicit theme so the Textual 8.x
# upgrade (done for built-in mouse text selection) changes ZERO colors.
_LEGACY_FOOTER_BG = "#0178D4"       # 0.56 $accent (old Footer background)
_LEGACY_FOOTER_KEY_BG = "#0053AA"   # 0.56 $accent-darken-2 (footer--key)
FOUNDRY_THEME = Theme(
    name="foundry",
    primary=_LEGACY_FOOTER_BG,      # drives block-cursor (ListView highlight) = old $accent
    secondary="#004578",
    accent=_LEGACY_FOOTER_BG,       # keep 8.x's orange accent out of scrollbars/focus tints
    background="#121212",
    surface="#1E1E1E",
    panel="#24292F",
    boost="#FFFFFF0A",
    dark=True,
)


class ServicesFooter(Static):
    """Pre-0.63-style one-line key footer, rendered as a single Text.

    Textual >=0.63 rewrote Footer into composed FooterKey widgets with a
    different look; this keeps the original bar (keys bold on darker blue,
    descriptions on the accent bar) byte-identical through the 8.x upgrade.
    """

    DEFAULT_CSS = """
    ServicesFooter {
        dock: bottom;
        height: 1;
        background: #0178D4;
        color: #DDE6ED;
        text-style: bold;
    }
    """

    def render(self) -> Text:
        text = Text(no_wrap=True, overflow="ellipsis", justify="left", end="")
        for binding in self.app.BINDINGS:
            if not isinstance(binding, Binding) or not binding.show:
                continue
            key_display = binding.key_display or binding.key.upper()
            text.append_text(
                Text.assemble(
                    (f" {key_display} ", f"bold #FFFFFF on {_LEGACY_FOOTER_KEY_BG}"),
                    (f" {binding.description} ", f"bold #DDE6ED on {_LEGACY_FOOTER_BG}"),
                    meta={"@click": f"app.footer_press('{binding.key}')"},
                )
            )
        return text


class ServicesUI(App[None]):
    """TUI for running and monitoring multiple services."""

    CSS = """
    Screen {
        layout: horizontal;
    }

    #sidebar {
        width: 34;
        min-width: 24;
        border: tall $boost;
        margin-bottom: 1;
    }

    #sidebar.fullscreen {
        display: none;
    }

    #update_banner {
        padding: 1 1 0 1;
        height: auto;
    }

    #update_banner_line1 {
        height: 1;
    }

    #update_banner_link {
        height: 1;
        color: #3B8EEA;
        text-style: bold underline;
    }

    #update_banner_link:hover {
        color: #5BA8FF;
    }

    #sidebar_title {
        text-style: bold underline;
        padding: 1 1 0 1;
    }

    #sidebar_hint {
        color: $text-muted;
        padding: 0 1 1 1;
    }

    #services {
        height: 1fr;
    }

    /* Reduce "cursor" artifacts: keep list highlight on the row, not on sub-widgets.
       (Textual >=0.63 renamed the highlight class to ListItem.-highlight.) */
    #services > ListItem.-highlight {
        text-style: none;
    }

    .svc_row {
        layout: horizontal;
        height: 1;
        padding: 0 1 0 2;
    }

    .svc_icon {
        width: 5;
        min-width: 5;
        margin-right: 1;
        content-align: left middle;
    }

    .svc_name {
        width: 1fr;
        content-align: left middle;
        color: #ffffff;
    }

    #log {
        border: tall $boost;
        padding: 0 1;
        scrollbar-size-vertical: 2;
        scrollbar-size-horizontal: 1;
    }

    #log.fullscreen {
        border: none;
        padding: 0;
        scrollbar-size-vertical: 0;
        scrollbar-size-horizontal: 0;
    }

    /* VSCode terminal: no border/scrollbars for cleaner look */
    #log.vscode-terminal {
        border: none;
        scrollbar-size-vertical: 0;
        scrollbar-size-horizontal: 0;
    }

    """

    # 0.56 had no command palette; keep ctrl+p free of surprise UI.
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+c", "request_quit", "Quit", priority=True),

        # Navigation / focus
        Binding("right", "interact", "Interact", show=False),
        Binding("escape", "unfocus", "Exit", show=False),

        # Layout
        Binding("tab", "toggle_fullscreen", "Toggle Sidebar", priority=True),

        # Service control
        Binding("r", "restart", "Restart"),

        # Log copy / export
        Binding("c", "copy_log", "Copy Log"),
        Binding("e", "export_log", "Export Log"),

        # Log scrolling (when log is focused)
        Binding("u", "log_line_up", "Scroll Up"),
        Binding("d", "log_line_down", "Scroll Down"),
        Binding("t", "log_top", "Jump Top"),
        Binding("b", "log_bottom", "Jump Bottom"),
        Binding("shift+up", "log_fast_up", "Fast Up", show=False),
        Binding("shift+down", "log_fast_down", "Fast Down", show=False),
        Binding("shift+left", "log_fast_left", "Fast Left", show=False),
        Binding("shift+right", "log_fast_right", "Fast Right", show=False),
    ]

    def __init__(
        self,
        services: list[DiscoveredService],
        runners: Dict[str, ServiceRunner],
        *,
        debug: bool = False,
    ) -> None:
        super().__init__()
        # Pin the exact 0.56-era palette (see FOUNDRY_THEME) — the Textual 8.x
        # default themes would silently recolor the whole UI.
        self.register_theme(FOUNDRY_THEME)
        self.theme = "foundry"
        self._services = services
        self._provided_runners = runners
        self._debug = debug

        self._logs: Dict[str, list[Text]] = {s.name: [] for s in services}
        self._runners: Dict[str, ServiceRunnerState] = {}
        self._selected: Optional[str] = services[0].name if services else None

        self._status: Dict[str, ServiceStatus] = {s.name: ServiceStatus.starting for s in services}

        # Build display names from runners (fallback to service name if no runner)
        self._display_names: Dict[str, str] = {}
        for svc in services:
            runner = runners.get(svc.name)
            if runner:
                self._display_names[svc.name] = runner.display_name
            else:
                self._display_names[svc.name] = svc.name

        self._focus: str = "list"
        self._is_vscode = os.environ.get("TERM_PROGRAM") == "vscode"

        # Tunnel readiness events — sidecars wait for their parent's tunnel
        # before starting. The event is set when the parent emits a status
        # with "tunnel established" in the detail, or immediately if the
        # parent has no tunnel (no SSH config).
        self._tunnel_ready: Dict[str, asyncio.Event] = {}
        for svc in services:
            if "/" not in svc.name:
                # Top-level service — create an event for it
                parent_runner = runners.get(svc.name)
                evt = asyncio.Event()
                # If this service has no tunnel wrapper, it's ready immediately
                if parent_runner is None or not isinstance(parent_runner, TunnelAwareRunner):
                    evt.set()
                self._tunnel_ready[svc.name] = evt


        if self._is_vscode:
            self._spinner_frames: tuple[str, ...] = (" ⠋", " ⠙", " ⠹", " ⠸", " ⠼", " ⠴", " ⠦", " ⠧", " ⠇", " ⠏")
        else:
            self._spinner_frames: tuple[str, ...] = (" -", " \\", " |", " /")
        self._spinner_index: int = 0
        self._sidebar_visible: bool = True

        # Memoized update-check result (network call — once per session, not per service)
        self._update_info: Optional[tuple[str, Optional[str], Optional[str]]] = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("Services", id="sidebar_title")
                yield Label("↑/↓ Select • → to Interact", id="sidebar_hint")
                items = []
                for svc in self._services:
                    safe_id = f"svc-{_sanitize_id(svc.name)}"
                    display_name = self._display_names.get(svc.name, svc.name)
                    row = Horizontal(
                        Label("", id=f"icon-{safe_id}", classes="svc_icon"),
                        Label(display_name, id=f"name-{safe_id}", classes="svc_name"),
                        classes="svc_row"
                    )
                    items.append(ListItem(row, id=safe_id, name=svc.name))
                yield ListView(*items, id="services")
            yield RichLog(id="log", highlight=False, markup=False, wrap=True)
        yield ServicesFooter()


    def _update_service_label(self, service_name: str) -> None:
        safe_id = f"svc-{_sanitize_id(service_name)}"
        try:
            icon_lbl = self.query_one(f"#icon-{safe_id}", Label)
        except Exception:
            return

        st = self._status.get(service_name)
        is_selected = service_name == self._selected
        if st == ServiceStatus.starting:
            frame = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
            icon_lbl.update(frame)
            icon_lbl.styles.color = "#F5F536" if is_selected else "#3B8EEA"
        elif st == ServiceStatus.healthy:
            icon_lbl.update(" ✔︎" if self._is_vscode else "[OK]")
            icon_lbl.styles.color = "#23D18B"
        elif st == ServiceStatus.failed:
            icon_lbl.update(" ✘︎" if self._is_vscode else "[X]")
            icon_lbl.styles.color = "#F14C4C"
        else:
            icon_lbl.update("?")
            icon_lbl.styles.color = "#888888"

    def _write_banner_to_service(self, service_name: str) -> None:
        """Write the Foundry ASCII banner and update banner to a service's log buffer."""
        try:
            version = get_local_version()
        except Exception:
            version = "?.?.?"

        banner_lines = [
            "[#3B8EEA bold]       ______ ____  _    _ _   _ _____  _______     __[/]",
            "[#3B8EEA bold]      |  ____/ __ \\| |  | | \\ | |  __ \\|  __ \\ \\   / /[/]",
            "[#3B8EEA bold]      | |__ | |  | | |  | |  \\| | |  | | |__) \\ \\_/ /[/]",
            "[#3B8EEA bold]      |  __|| |  | | |  | | . ` | |  | |  _  / \\   /[/]",
            "[#3B8EEA bold]      | |   | |__| | |__| | |\\  | |__| | | \\ \\  | |[/]",
            "[#3B8EEA bold]      |_|    \\____/ \\____/|_| \\_|_____/|_|  \\_\\ |_|[/]",
            "",
            f"[#3B8EEA bold]                         v{version}[/]",
            "",
            "[#888888]Select text: click+drag, then 'c' to copy  -  'c' alone copies the whole log  -  'e' exports it[/]",
            "",
        ]

        log_list = self._logs.setdefault(service_name, [])
        for line in banner_lines:
            styled = Text.from_markup(line)
            log_list.append(styled)

        # Check for updates once per session; reuse the result for every service
        if self._update_info is None:
            self._update_info = check_for_updates()
        local, latest, url = self._update_info
        if latest:
            _print_update_banner_to_log(log_list, local, latest, url)

    async def on_mount(self) -> None:
        if self._is_vscode:
            self.query_one("#log", RichLog).add_class("vscode-terminal")

        for svc in self._services:
            self._write_banner_to_service(svc.name)

        for svc in self._services:
            runner = self._provided_runners.get(svc.name)
            if runner is None:
                continue

            # Sidecars (name = "parent/sidecar") must wait for their
            # parent service's SSH tunnel before starting.
            if "/" in svc.name:
                parent_name = svc.name.split("/", 1)[0]
                start_task = asyncio.create_task(
                    self._start_after_tunnel(parent_name, runner)
                )
            else:
                start_task = asyncio.create_task(runner.start())

            pump_task = asyncio.create_task(self._pump_runner_events(runner))
            status_task = asyncio.create_task(self._pump_runner_status_events(runner))
            self._runners[svc.name] = ServiceRunnerState(
                name=svc.name,
                runner=runner,
                start_task=start_task,
                pump_task=pump_task,
                status_task=status_task,
            )

        lv = self.query_one("#services", ListView)
        lv.focus()
        if self._services:
            try:
                lv.index = 0
            except Exception:
                pass

        if self._selected:
            self._render_selected()

        self.set_interval(0.15, self._tick_spinner)
        self._ansi_decoder = AnsiDecoder()


    def _tick_spinner(self) -> None:
        self._spinner_index += 1
        for name, st in self._status.items():
            if st == ServiceStatus.starting:
                self._update_service_label(name)

    async def on_unmount(self) -> None:
        for st in self._runners.values():
            st.pump_task.cancel()
            st.status_task.cancel()
            st.start_task.cancel()

        await asyncio.gather(
            *(st.pump_task for st in self._runners.values()),
            *(st.status_task for st in self._runners.values()),
            *(st.start_task for st in self._runners.values()),
            return_exceptions=True,
        )

        await asyncio.gather(
            *(st.runner.stop() for st in self._runners.values()),
            return_exceptions=True,
        )

    async def _pump_runner_events(self, runner: ServiceRunner) -> None:
        try:
            async for ev in runner.events():
                self._append_event(ev)
        except asyncio.CancelledError:
            return

    async def _pump_runner_status_events(self, runner: ServiceRunner) -> None:
        try:
            async for ev in runner.status_events():
                self._apply_status_event(ev)
        except asyncio.CancelledError:
            return

    async def _start_after_tunnel(self, parent_name: str, runner: ServiceRunner) -> None:
        """Wait for a parent service's SSH tunnel to be established, then start the runner."""
        evt = self._tunnel_ready.get(parent_name)
        if evt and not evt.is_set():
            await evt.wait()
        await runner.start()

    def _render_selected(self) -> None:
        log = self.query_one("#log", RichLog)
        log.clear()
        if not self._selected:
            return
        for line in self._logs.get(self._selected, []):
            log.write(line)

        for name in self._status:
            self._update_service_label(name)

    def _select_hovered_service(self) -> None:
        lv = self.query_one("#services", ListView)
        index = lv.index
        if index is None:
            return
        items = list(lv.children)
        if index < 0 or index >= len(items):
            return
        item = items[index]
        name = getattr(item, "name", None)
        if not name:
            return
        name_s = str(name)
        if name_s not in self._logs:
            return
        self._selected = name_s
        self._render_selected()


    def _append_event(self, ev: ServiceLogEvent) -> None:
        """Append runner log output, preserving ANSI colors."""

        if ev.level:
            if ev.level == "DEBUG" and not self._debug:
                return
            line = format_log_line(LogLine(timestamp=datetime.now(), level=ev.level, message=ev.line))
            styled = Text.from_markup(line)
            self._logs.setdefault(ev.service_name, []).append(styled)
            if ev.service_name == self._selected:
                try:
                    self.query_one("#log", RichLog).write(styled)
                except NoMatches:
                    return
            return

        prefix = "" if ev.stream == "stdout" else "[stderr] "
        raw = f"{prefix}{ev.line}"
        segments = list(self._ansi_decoder.decode(raw))
        if segments:
            text = Text.assemble(*segments)
        else:
            text = Text(raw)

        self._logs.setdefault(ev.service_name, []).append(text)

        if ev.service_name == self._selected:
            try:
                self.query_one("#log", RichLog).write(text)
            except NoMatches:
                return

    def _apply_status_event(self, ev: ServiceStatusEvent) -> None:
        self._status[ev.service_name] = ev.status
        self._update_service_label(ev.service_name)

        # Signal tunnel readiness for sidecar dependency tracking
        if ev.service_name in self._tunnel_ready and not self._tunnel_ready[ev.service_name].is_set():
            detail_lower = (ev.detail or "").lower()
            if "tunnel established" in detail_lower or ev.status in (ServiceStatus.healthy, ServiceStatus.failed):
                self._tunnel_ready[ev.service_name].set()

        if ev.level == "DEBUG" and not self._debug:
            return

        if ev.status == ServiceStatus.failed:
            msg = ev.error or ev.detail or "Failed"
        else:
            msg = ev.detail or ev.status

        line = format_log_line(LogLine(timestamp=datetime.now(), level=ev.level, message=msg))
        styled = Text.from_markup(line)
        self._logs.setdefault(ev.service_name, []).append(styled)
        if ev.service_name == self._selected:
            try:
                self.query_one("#log", RichLog).write(styled)
            except NoMatches:
                return

    async def on_event(self, event: events.Event) -> None:
        """Drop non-left-click mouse events and paste events before dispatch.

        Right/middle-click in some terminals (e.g. VS Code) can trigger
        @click meta actions on the footer or paste clipboard text, which
        would inadvertently fire key-bound actions like restart.
        """
        if isinstance(event, (events.MouseDown, events.MouseUp, events.Click)):
            if event.button != 1:
                return  # swallow the event entirely
        if isinstance(event, events.Paste):
            return  # swallow paste — no paste target in this TUI
        await super().on_event(event)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if item is None:
            return
        name = getattr(item, "name", None)
        if not name or str(name) not in self._logs:
            return
        self._selected = str(name)
        self._render_selected()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Auto-select service on arrow navigation."""

        item = event.item
        if item is None:
            return
        name = getattr(item, "name", None)
        if not name:
            return
        name_s = str(name)
        if name_s == self._selected:
            return
        if name_s not in self._logs:
            return

        self._selected = name_s
        self._render_selected()

    def action_interact(self) -> None:
        """Focus the log pane (Right Arrow)."""

        self._focus = "log"
        self.query_one("#log", RichLog).focus()

        try:
            self.query_one("#sidebar_hint", Label).update("[Esc] to Change Service")
        except NoMatches:
            pass

    def action_unfocus(self) -> None:
        """Return focus to the services list (Escape)."""

        self._focus = "list"
        self.query_one("#services", ListView).focus()

        try:
            self.query_one("#sidebar_hint", Label).update("↑/↓ Select • → to Interact")
        except NoMatches:
            pass

    def action_open_download(self) -> None:
        """Open the download URL in the default browser."""
        if hasattr(self, "_download_url") and self._download_url:
            webbrowser.open(self._download_url)

    def action_toggle_fullscreen(self) -> None:
        sidebar = self.query_one("#sidebar", Vertical)
        log = self.query_one("#log", RichLog)
        self._sidebar_visible = not self._sidebar_visible

        if self._sidebar_visible:
            sidebar.remove_class("fullscreen")
            log.remove_class("fullscreen")
            self.action_unfocus()
        else:
            self.action_interact()
            sidebar.add_class("fullscreen")
            log.add_class("fullscreen")

        # Re-render logs after layout updates so wrapping uses new width
        self.call_after_refresh(self._render_selected)

    def action_log_line_up(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_to(y=max(0, log.scroll_y - 1))

    def action_log_line_down(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_to(y=log.scroll_y + 1)

    def action_log_fast_up(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_to(y=max(0, log.scroll_y - 2))

    def action_log_fast_down(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_to(y=log.scroll_y + 2)

    def action_log_fast_left(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_to(x=max(0, log.scroll_x - 4))

    def action_log_fast_right(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_to(x=log.scroll_x + 4)

    def _selected_log_text(self) -> Optional[str]:
        """Plain-text dump of the selected service's log buffer."""
        if not self._selected:
            return None
        lines = self._logs.get(self._selected)
        if not lines:
            return None
        return "\n".join(t.plain for t in lines)

    def _notify_selected(self, level: str, message: str) -> None:
        """Append a status line to the selected service's log buffer + pane."""
        line = format_log_line(
            LogLine(timestamp=datetime.now(), level=level, message=escape(message))
        )
        styled = Text.from_markup(line)
        if self._selected:
            self._logs.setdefault(self._selected, []).append(styled)
        try:
            self.query_one("#log", RichLog).write(styled)
        except NoMatches:
            pass

    def action_footer_press(self, key: str) -> None:
        """Run the action bound to `key` (footer @click)."""
        for binding in self.BINDINGS:
            if isinstance(binding, Binding) and binding.key == key:
                self.call_later(self.run_action, binding.action)
                return

    def action_copy_log(self) -> None:
        """Copy mouse-selected text, else the selected service's full log ('c')."""
        selection = None
        try:
            selection = self.screen.get_selected_text()
        except Exception:
            pass
        if selection:
            err = _copy_text_to_clipboard(selection)
            if err is None:
                count = selection.count("\n") + 1
                self._notify_selected("INFO", f"Copied selection ({count} lines) to clipboard")
                self.screen.clear_selection()
            else:
                self._notify_selected("ERROR", f"Clipboard copy failed: {err}")
            return
        text = self._selected_log_text()
        if text is None:
            return
        err = _copy_text_to_clipboard(text + "\n")
        if err is None:
            count = text.count("\n") + 1
            self._notify_selected("INFO", f"Copied {count} log lines to clipboard")
        else:
            self._notify_selected("ERROR", f"Clipboard copy failed: {err}")

    def action_export_log(self) -> None:
        """Write the selected service's log to ~/.foundry/logs/ ('e')."""
        text = self._selected_log_text()
        if text is None or not self._selected:
            return
        try:
            logs_dir = Path.home() / ".foundry" / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            out = logs_dir / f"{_sanitize_id(self._selected)}-{stamp}.log"
            out.write_text(text + "\n", encoding="utf-8")
            self._notify_selected("INFO", f"Log exported: {out}")
        except Exception as e:
            self._notify_selected("ERROR", f"Log export failed: {e}")

    def action_log_top(self) -> None:
        self.query_one("#log", RichLog).scroll_to(y=0, animate=False)

    def action_log_bottom(self) -> None:
        self.query_one("#log", RichLog).scroll_end(animate=False)

    async def action_restart(self) -> None:
        """Restart the currently selected service."""
        if not self._selected:
            return
        
        name = self._selected
        state = self._runners.get(name)
        if not state:
            return
        
        # Log restart message
        restart_msg = Text.from_markup(
            f"[bold #F5F536]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/] "
            "[bold #29B8DB]INFO[/] Restarting service..."
        )
        self._logs[name].append(restart_msg)
        self._logs[name].append(Text(""))
        
        # Update status to restarting (shows spinner)
        self._status[name] = ServiceStatus.starting
        self._update_service_label(name)
        self._render_selected()
        
        # Cancel existing tasks
        state.pump_task.cancel()
        state.status_task.cancel()
        state.start_task.cancel()
        
        await asyncio.gather(
            state.pump_task,
            state.status_task,
            state.start_task,
            return_exceptions=True,
        )
        
        # Stop the runner
        try:
            await state.runner.stop()
        except Exception as e:
            error_msg = Text.from_markup(
                f"[bold #F5F536]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/] "
                f"[bold #F14C4C]ERROR[/] Failed to stop: {e}"
            )
            self._logs[name].append(error_msg)
        
        # Drain residual log/status events that the old runner may have
        # enqueued before it was fully stopped, so they don't appear after
        # the restart message (e.g. a stale "terminated unexpectedly" error).
        try:
            while not state.runner._log_queue.empty():
                state.runner._log_queue.get_nowait()
            while not state.runner._status_queue.empty():
                state.runner._status_queue.get_nowait()
        except Exception:
            pass

        # Small delay for process cleanup
        await asyncio.sleep(0.5)
        
        # Restart the runner
        start_task = asyncio.create_task(state.runner.start())
        pump_task = asyncio.create_task(self._pump_runner_events(state.runner))
        status_task = asyncio.create_task(self._pump_runner_status_events(state.runner))
        
        self._runners[name] = ServiceRunnerState(
            name=name,
            runner=state.runner,
            start_task=start_task,
            pump_task=pump_task,
            status_task=status_task,
        )
        
        self._render_selected()

    async def action_request_quit(self) -> None:
        """Gracefully shut down all services."""
        shutdown_msg = Text.from_markup(
            f"[bold #F5F536]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/] "
            "[bold #F14C4C]SHUTDOWN[/] Gracefully stopping services..."
        )
        for name in self._logs:
            self._logs[name].append(shutdown_msg)

        if self._selected:
            try:
                self.query_one("#log", RichLog).write(shutdown_msg)
            except NoMatches:
                pass

        for name in self._status:
            self._status[name] = ServiceStatus.failed  # Use failed icon temporarily
            self._update_service_label(name)

        await asyncio.sleep(0.1)
        self.exit()
