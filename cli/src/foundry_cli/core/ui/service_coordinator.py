from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Label, ListItem, ListView, RichLog

from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runner import ServiceLogEvent, ServiceRunner


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

        self._logs: Dict[str, list[str]] = {s.name: [] for s in services}
        self._runners: Dict[str, ServiceRunnerState] = {}
        self._selected: Optional[str] = services[0].name if services else None

        self._focus: str = "list"  # list | log

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("Services", id="sidebar_title")
                yield Label("↑/↓ Select • Tab to Interact", id="sidebar_hint")
                lv = ListView(id="services")
                for svc in self._services:
                    safe_id = f"svc-{svc.name}".replace(" ", "-")
                    lv.append(ListItem(Label(svc.name), id=safe_id, name=svc.name))
                yield lv
            yield RichLog(id="log", highlight=True, markup=True, wrap=False)
        yield Footer()

    async def on_mount(self) -> None:
        # Start one runner per service and pump its events into the UI.
        for svc in self._services:
            runner = self._provided_runners.get(svc.name)
            if runner is None:
                continue

            start_task = asyncio.create_task(runner.start())
            pump_task = asyncio.create_task(self._pump_runner_events(runner))
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

    async def on_unmount(self) -> None:
        for st in self._runners.values():
            st.pump_task.cancel()
        await asyncio.gather(*(st.pump_task for st in self._runners.values()), return_exceptions=True)

        await asyncio.gather(*(st.start_task for st in self._runners.values()), return_exceptions=True)
        await asyncio.gather(*(st.runner.stop() for st in self._runners.values()), return_exceptions=True)

    async def _pump_runner_events(self, runner: ServiceRunner) -> None:
        async for ev in runner.events():
            self._append_event(ev)

    def _render_selected(self) -> None:
        log = self.query_one("#log", RichLog)
        log.clear()
        if not self._selected:
            return

        # Helpful banner so it's obvious which service console you're viewing.
        # (No leading blank line, so we keep this as the first write.)
        log.write(f"=== {self._selected} ===")
        for line in self._logs.get(self._selected, []):
            log.write(line)


    def _append_event(self, ev: ServiceLogEvent) -> None:
        # Keep in-memory history per service so switching shows different consoles.
        prefix = "" if ev.stream == "stdout" else "[stderr] "
        line = f"{prefix}{ev.line}"
        self._logs.setdefault(ev.service_name, []).append(line)

        if ev.service_name == self._selected:
            log = self.query_one("#log", RichLog)
            log.write(line)

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
