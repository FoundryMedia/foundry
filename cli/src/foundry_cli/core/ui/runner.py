# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Label, ListItem, ListView, RichLog
from rich.ansi import AnsiDecoder
from rich.text import Text

from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.service_runner import (
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)

from foundry_cli.core.ui.logger import LogLine, format_log_line


@dataclass(frozen=True)
class ServiceRunnerState:
    name: str
    runner: ServiceRunner
    start_task: asyncio.Task[None]
    pump_task: asyncio.Task[None]


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
        ("ctrl+c", "quit", "Quit"),
        ("tab", "toggle_focus", "Focus Log"),
        ("u", "log_line_up", "Scroll Up"),
        ("d", "log_line_down", "Scroll Down"),
        ("t", "log_top", "Top"),
        ("b", "log_bottom", "Bottom"),
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

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("Services", id="sidebar_title")
                yield Label("↑/↓ Select • Tab to Interact", id="sidebar_hint")
                lv = ListView(id="services")
                for svc in self._services:
                    safe_id = f"svc-{svc.name}".replace(" ", "-")
                    row = Horizontal(classes="svc_row")
                    row.mount(Label("", id=f"icon-{safe_id}", classes="svc_icon"))
                    row.mount(Label(svc.name, id=f"name-{safe_id}", classes="svc_name"))
                    lv.append(ListItem(row, id=safe_id, name=svc.name))
                yield lv
            yield RichLog(id="log", highlight=False, markup=False, wrap=False)
        yield Footer()

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
            asyncio.create_task(self._pump_runner_status_events(runner))
            self._runners[svc.name] = ServiceRunnerState(
                name=svc.name,
                runner=runner,
                start_task=start_task,
                pump_task=pump_task,
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
        await asyncio.gather(*(st.pump_task for st in self._runners.values()), return_exceptions=True)

        await asyncio.gather(*(st.start_task for st in self._runners.values()), return_exceptions=True)
        await asyncio.gather(*(st.runner.stop() for st in self._runners.values()), return_exceptions=True)

    async def _pump_runner_events(self, runner: ServiceRunner) -> None:
        async for ev in runner.events():
            self._append_event(ev)

    async def _pump_runner_status_events(self, runner: ServiceRunner) -> None:
        async for ev in runner.status_events():
            self._apply_status_event(ev)

    def _render_selected(self) -> None:
        log = self.query_one("#log", RichLog)
        log.clear()
        if not self._selected:
            return
        for line in self._logs.get(self._selected, []):
            # Stored history is already fully formatted (Text or str).
            log.write(line)


    def _append_event(self, ev: ServiceLogEvent) -> None:
        """Append runner output.

        Requirements:
        - Runner output should be piped through without our styling. In particular,
          Spring Boot's ANSI colors should remain intact.
        - Avoid Rich markup parsing entirely for runner output.
        """

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
            self.query_one("#log", RichLog).write(text)

    def _apply_status_event(self, ev: ServiceStatusEvent) -> None:
        self._status[ev.service_name] = ev.status
        self._update_service_label(ev.service_name)

        # Status transitions are noisy; only mirror them into logs in debug mode.
        if not self._debug:
            return

        if ev.status == ServiceStatus.starting:
            lvl = "INFO"
            msg = ev.detail or "Starting"
        elif ev.status == ServiceStatus.healthy:
            lvl = "INFO"
            msg = ev.detail or "Healthy"
        else:
            lvl = "ERROR"
            msg = ev.error or ev.detail or "Failed"

        line = format_log_line(LogLine(timestamp=datetime.now(), level=lvl, message=msg))
        # Status lines are Foundry-generated, so we intentionally style them.
        # Convert markup into rich Text so the log widget doesn't need markup.
        styled = Text.from_markup(line)
        self._logs.setdefault(ev.service_name, []).append(styled)
        if ev.service_name == self._selected:
            self.query_one("#log", RichLog).write(styled)

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

    def action_toggle_focus(self) -> None:
        self._focus = "log"
        self.query_one("#log", RichLog).focus()

    def action_log_line_up(self) -> None:
    # Scroll log up without changing focus.
        log = self.query_one("#log", RichLog)
        log.scroll_to(y=max(0, log.scroll_y - 1))

    def action_log_line_down(self) -> None:
    # Scroll log down without changing focus.
        log = self.query_one("#log", RichLog)
        log.scroll_to(y=log.scroll_y + 1)

    def action_log_top(self) -> None:
    # Jump to top.
        self.query_one("#log", RichLog).scroll_to(y=0)

    def action_log_bottom(self) -> None:
    # Jump to bottom.
        self.query_one("#log", RichLog).scroll_end(animate=False)
