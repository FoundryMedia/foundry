# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Label, ListItem, ListView, RichLog, Static
from rich.ansi import AnsiDecoder
from rich.text import Text
import webbrowser

from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runners.base import (
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)

from foundry_cli.core.util.logger import LogLine, format_log_line

from foundry_cli.release.versioning import get_local_version


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
from foundry_cli.release.update_check import check_for_updates

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
from foundry_cli.release.update_check import check_for_updates



@dataclass(frozen=True)
class ServiceRunnerState:
    name: str
    runner: ServiceRunner
    start_task: asyncio.Task[None]
    pump_task: asyncio.Task[None]
    status_task: asyncio.Task[None]


class ServicesFooter(Footer):
    def _make_key_text(self) -> Text:
        base_style = self.rich_style
        text = Text(
            style=self.rich_style,
            no_wrap=True,
            overflow="ellipsis",
            justify="left",
            end="",
        )
        highlight_style = self.get_component_rich_style("footer--highlight")
        highlight_key_style = self.get_component_rich_style("footer--highlight-key")
        key_style = self.get_component_rich_style("footer--key")
        description_style = self.get_component_rich_style("footer--description")

        bindings = [
            binding
            for (_, binding) in self.app.namespace_bindings.values()
            if binding.show
        ]

        action_to_bindings = defaultdict(list)
        for binding in bindings:
            action_to_bindings[binding.action].append(binding)

        preferred_actions = ["request_quit", "toggle_fullscreen"]
        ordered_actions = [
            *[action for action in preferred_actions if action in action_to_bindings],
            *[
                action
                for action in action_to_bindings.keys()
                if action not in preferred_actions
            ],
        ]

        for action in ordered_actions:
            binding = action_to_bindings[action][0]
            if binding.key_display is None:
                key_display = self.app.get_key_display(binding.key)
                if key_display is None:
                    key_display = binding.key.upper()
            else:
                key_display = binding.key_display
            hovered = self.highlight_key == binding.key
            key_text = Text.assemble(
                (f" {key_display} ", highlight_key_style if hovered else key_style),
                (
                    f" {binding.description} ",
                    highlight_style if hovered else base_style + description_style,
                ),
                meta={
                    "@click": f"app.check_bindings('{binding.key}')",
                    "key": binding.key,
                },
            )
            text.append_text(key_text)
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

    /* Reduce "cursor" artifacts: keep list highlight on the row, not on sub-widgets. */
    #services:focus .listview--highlight {
        text-style: none;
    }

    .svc_row {
        layout: horizontal;
        height: 1;
        padding: 0 1 0 2;
    }

    .svc_icon {
        width: 4;
        min-width: 4;
        margin-right: 1;
        content-align: left middle;
    }

    /* Wider icon column for ASCII status indicators in non-VSCode terminals */
    .svc_icon.ascii-mode {
        width: 5;
        min-width: 5;
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

    Footer {
        text-style: bold;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "request_quit", "Quit", priority=True),

        # Navigation / focus
        Binding("right", "interact", "Interact", show=False),
        Binding("escape", "unfocus", "Exit", show=False),

        # Layout
        Binding("tab", "toggle_fullscreen", "Toggle Sidebar", priority=True),

        # Service control
        Binding("r", "restart", "Restart"),

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


        if self._is_vscode:
            self._spinner_frames: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        else:
            self._spinner_frames: tuple[str, ...] = (" -", " \\", " |", " /")
        self._spinner_index: int = 0
        self._sidebar_visible: bool = True

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
            icon_lbl.update("✔" if self._is_vscode else "[OK]")
            icon_lbl.styles.color = "#23D18B"
        elif st == ServiceStatus.failed:
            icon_lbl.update("✘" if self._is_vscode else "[X]")
            icon_lbl.styles.color = "#F14C4C"
        else:
            icon_lbl.update("?")
            icon_lbl.styles.color = "#888888"

    def _print_update_banner_to_log(log_list, local: str, latest: str, url: str | None) -> None:
        log_list.append(Text.from_markup("[#3B8EEA bold]-----------------------------------------------------------------------[/]"))
        line = (
            Text.from_markup("[magenta bold]Update available: [/]" +
                f"[red bold]{local}[/][yellow bold] → [/][green bold]{latest}[/]")
        )
        log_list.append(line)
        if url:
            log_list.append(Text.from_markup(f"[cyan]Download: {url}[/]"))
        else:
            log_list.append(Text.from_markup("[cyan]Run the latest installer from GitHub Releases to upgrade.[/]"))
        log_list.append(Text.from_markup("[#3B8EEA bold]-----------------------------------------------------------------------[/]"))

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
        ]

        log_list = self._logs.setdefault(service_name, [])
        for line in banner_lines:
            styled = Text.from_markup(line)
            log_list.append(styled)

        # Check for updates and print update banner if needed
        local, latest, url = check_for_updates()
        if latest:
            _print_update_banner_to_log(log_list, local, latest, url)

    async def on_mount(self) -> None:
        if self._is_vscode:
            self.query_one("#log", RichLog).add_class("vscode-terminal")
        else:
            for svc in self._services:
                safe_id = f"svc-{_sanitize_id(svc.name)}"
                try:
                    self.query_one(f"#icon-{safe_id}", Label).add_class("ascii-mode")
                except Exception:
                    pass

        for svc in self._services:
            self._write_banner_to_service(svc.name)

        for svc in self._services:
            runner = self._provided_runners.get(svc.name)
            if runner is None:
                continue

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
