# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Label, ListItem, ListView, RichLog
from rich.ansi import AnsiDecoder
from rich.text import Text

from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runners.base import (
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)

from foundry_cli.core.util.logger import LogLine, format_log_line


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

        preferred_actions = ["quit", "toggle_fullscreen"]
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
    """Turbo-like services UI.

    This class focuses on display + interaction.

    Service execution is handled by injected `ServiceRunner` instances.
    """

    CSS = """
    Screen {
        layout: horizontal;
    }

    #sidebar {
        width: 34;
        min-width: 24;
        border: tall $boost;
    }

    #sidebar_title {
        text-style: bold underline;
        padding: 0 1;
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
        padding: 0 1;
    }

    .svc_icon {
    width: 3;
        content-align: left middle;
    }

    .svc_name {
        width: 1fr;
        content-align: left middle;
        color: #ffffff;
    }

    #log {
        border: tall $boost;
    }

    Footer {
        /* Keep the classic Textual footer look, but make it punchier. */
        text-style: bold;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),

        # Navigation / focus
        Binding("right", "interact", "Interact"),
        Binding("escape", "unfocus", "Exit", show=False),

        # Layout
        Binding("tab", "toggle_fullscreen", "Fullscreen", priority=True),

        # Log scrolling (when log is focused)
        Binding("u", "log_line_up", "Scroll Up"),
        Binding("d", "log_line_down", "Scroll Down"),
        Binding("t", "log_top", "Top"),
        Binding("b", "log_bottom", "Bottom"),
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

        # starting | healthy | failed
        # Start in starting so the spinner shows immediately.
        self._status: Dict[str, ServiceStatus] = {s.name: ServiceStatus.starting for s in services}

        self._focus: str = "list"  # list | log

        self._spinner_frames: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        self._spinner_index: int = 0
        self._sidebar_visible: bool = True

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("Services", id="sidebar_title")
                yield Label("↑/↓ Select • → to Interact", id="sidebar_hint")
                lv = ListView(id="services")
                for svc in self._services:
                    safe_id = f"svc-{svc.name}".replace(" ", "-")
                    row = Horizontal(classes="svc_row")
                    row.mount(Label("", id=f"icon-{safe_id}", classes="svc_icon"))
                    row.mount(Label(svc.name, id=f"name-{safe_id}", classes="svc_name"))
                    lv.append(ListItem(row, id=safe_id, name=svc.name))
                yield lv
            yield RichLog(id="log", highlight=False, markup=False, wrap=False)
        yield ServicesFooter()


    def _update_service_label(self, service_name: str) -> None:
        safe_id = f"svc-{service_name}".replace(" ", "-")
        try:
            icon_lbl = self.query_one(f"#icon-{safe_id}", Label)
        except Exception:
            return

        st = self._status.get(service_name)
        if st == ServiceStatus.starting:
            frame = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
            icon_lbl.update(frame)
            icon_lbl.styles.color = "#3B8EEA"
        elif st == ServiceStatus.healthy:
            icon_lbl.update("✔")
            icon_lbl.styles.color = "#23D18B"
        elif st == ServiceStatus.failed:
            icon_lbl.update("✘")
            icon_lbl.styles.color = "#F14C4C"
        else:
            icon_lbl.update("?")
            icon_lbl.styles.color = "#888888"

    async def on_mount(self) -> None:
        # Start one runner per service and pump its events into the UI.
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

        # Default focus: list and highlight the first service.
        lv = self.query_one("#services", ListView)
        lv.focus()
        if self._services:
            # Highlight index 0 (first service item).
            try:
                lv.index = 0
            except Exception:
                pass

        if self._selected:
            self._render_selected()

        # Start the spinner refresh loop.
        self.set_interval(0.15, self._tick_spinner)

        # Rich helper for decoding ANSI-colored process output.
        self._ansi_decoder = AnsiDecoder()


    def _tick_spinner(self) -> None:
        self._spinner_index += 1
        # Re-render only labels that are currently "starting".
        for name, st in self._status.items():
            if st == ServiceStatus.starting:
                self._update_service_label(name)

    async def on_unmount(self) -> None:
        for st in self._runners.values():
            st.pump_task.cancel()
            st.status_task.cancel()
        await asyncio.gather(
            *(st.pump_task for st in self._runners.values()),
            *(st.status_task for st in self._runners.values()),
            return_exceptions=True,
        )

        await asyncio.gather(*(st.start_task for st in self._runners.values()), return_exceptions=True)
        await asyncio.gather(*(st.runner.stop() for st in self._runners.values()), return_exceptions=True)

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
            # Stored history is already fully formatted (Text or str).
            log.write(line)

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
        """Append runner output.

        Requirements:
        - Runner output should be piped through without our styling. In particular,
          Spring Boot's ANSI colors should remain intact.
        - Avoid Rich markup parsing entirely for runner output.
        """

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

        # If the process emitted ANSI, preserve it by decoding into a rich Text.
        # Otherwise, store/write as plain text.
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
        # Status lines are Foundry-generated, so we intentionally style them.
        # Convert markup into rich Text so the log widget doesn't need markup.
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
        """Auto-select on arrow-key navigation (no Enter required)."""

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
        """Focus the log pane.

        Bound to Right Arrow so we don't steal Tab (used for horizontal scrolling)
        and to avoid changing list selection when the user just wants to interact.
        """

        self._focus = "log"
        self.query_one("#log", RichLog).focus()

        # Once the log is focused, update the hint to explain how to get back.
        try:
            self.query_one("#sidebar_hint", Label).update("[Esc] to Change Service")
        except NoMatches:
            pass

    def action_unfocus(self) -> None:
        """Return focus back to the services list (and re-enable → to interact)."""

        self._focus = "list"
        self.query_one("#services", ListView).focus()

        try:
            self.query_one("#sidebar_hint", Label).update("↑/↓ Select • → to Interact")
        except NoMatches:
            pass

    def action_toggle_fullscreen(self) -> None:
        sidebar = self.query_one("#sidebar", Vertical)
        self._sidebar_visible = not self._sidebar_visible
        sidebar.styles.display = "block" if self._sidebar_visible else "none"

        log = self.query_one("#log", RichLog)
        show_scrollbars = self._sidebar_visible
        if hasattr(log, "show_vertical_scrollbar"):
            log.show_vertical_scrollbar = show_scrollbars
        if hasattr(log, "show_horizontal_scrollbar"):
            log.show_horizontal_scrollbar = show_scrollbars

        if not self._selected or self._focus != "list":
            self._select_hovered_service()

        self._focus = "log"
        log.focus()

    def action_log_line_up(self) -> None:
        # Scroll log up without changing focus.
        log = self.query_one("#log", RichLog)
        log.scroll_to(y=max(0, log.scroll_y - 1))

    def action_log_line_down(self) -> None:
        # Scroll log down without changing focus.
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
        log.scroll_to(x=max(0, log.scroll_x - 2))

    def action_log_fast_right(self) -> None:
        log = self.query_one("#log", RichLog)
        log.scroll_to(x=log.scroll_x + 2)

    def action_log_top(self) -> None:
        # Jump to top.
        self.query_one("#log", RichLog).scroll_to(y=0, animate=False)

    def action_log_bottom(self) -> None:
        # Jump to bottom.
        self.query_one("#log", RichLog).scroll_end(animate=False)
