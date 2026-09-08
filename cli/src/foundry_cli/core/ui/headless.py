"""Headless (no-TUI) driver for `foundry run` — plain-text stream output.

Used when `--no-tui` is passed, `FOUNDRY_NO_TUI` is set, or stdout is not a
TTY (CI, pipes). Prints full untruncated log lines, one per row, and exits
with a nonzero status when every service fails — so a wrapping script fails
fast instead of hanging on a full-screen UI.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime
from typing import Dict

from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runners.base import (
    ServiceLaunchError,
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)
from foundry_cli.core.services.runners.tunnel_aware import TunnelAwareRunner


def headless_mode_requested(no_tui_flag: bool) -> bool:
    """True when the run should skip the TUI entirely."""
    import os

    if no_tui_flag:
        return True
    if os.environ.get("FOUNDRY_NO_TUI", "").strip().lower() in ("1", "true", "yes"):
        return True
    try:
        return not sys.stdout.isatty()
    except Exception:
        return False


class HeadlessServicesRunner:
    """Start every runner, stream events as plain text, exit on fatal failure.

    Exit codes: 0 = graceful shutdown (Ctrl+C/SIGTERM), 1 = every service
    ended up failed (startup misconfiguration, crash, tunnel failure).
    """

    def __init__(
        self,
        services: list[DiscoveredService],
        runners: Dict[str, ServiceRunner],
        *,
        debug: bool = False,
    ) -> None:
        self._services = services
        self._runners = runners
        self._debug = debug
        self._status: Dict[str, ServiceStatus] = {
            s.name: ServiceStatus.starting for s in services if s.name in runners
        }
        self._stop_event: asyncio.Event | None = None
        self._fatal = False
        # Sidecars wait for their parent's tunnel — mirror of the TUI logic.
        self._tunnel_ready: Dict[str, asyncio.Event] = {}

    # ── output ────────────────────────────────────────────────────────

    def _emit(self, service: str, text: str, level: str | None = None) -> None:
        if level == "DEBUG" and not self._debug:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        tag = f" {level}" if level else ""
        print(f"{stamp} [{service}]{tag} {text}", flush=True)

    # ── event pumps ───────────────────────────────────────────────────

    async def _pump_logs(self, runner: ServiceRunner) -> None:
        try:
            async for ev in runner.events():
                self._on_log(ev)
        except asyncio.CancelledError:
            return

    def _on_log(self, ev: ServiceLogEvent) -> None:
        prefix = "" if ev.stream == "stdout" else "[stderr] "
        self._emit(ev.service_name, f"{prefix}{ev.line}", ev.level)

    async def _pump_status(self, runner: ServiceRunner) -> None:
        try:
            async for ev in runner.status_events():
                self._on_status(ev)
        except asyncio.CancelledError:
            return

    def _on_status(self, ev: ServiceStatusEvent) -> None:
        self._status[ev.service_name] = ev.status

        # Parent tunnel readiness for waiting sidecars.
        evt = self._tunnel_ready.get(ev.service_name)
        if evt is not None and not evt.is_set():
            detail_lower = (ev.detail or "").lower()
            if "tunnel established" in detail_lower or ev.status in (
                ServiceStatus.healthy,
                ServiceStatus.failed,
            ):
                evt.set()

        if ev.status == ServiceStatus.failed:
            msg = ev.error or ev.detail or "Failed"
        else:
            msg = ev.detail or str(ev.status)
        self._emit(ev.service_name, msg, ev.level)

        self._check_fatal()

    def _check_fatal(self) -> None:
        """All top-level services failed → tear down and exit nonzero."""
        top = {n: s for n, s in self._status.items() if "/" not in n}
        if top and all(s == ServiceStatus.failed for s in top.values()):
            self._fatal = True
            if self._stop_event is not None:
                self._stop_event.set()

    # ── lifecycle ─────────────────────────────────────────────────────

    async def _guarded_start(self, runner: ServiceRunner) -> None:
        """Run start(); an exception is a FAILED service, never a silent hang.

        A runner that cannot spawn already emitted its own specific failed
        status (ServiceLaunchError); anything else gets a generic one so the
        all-failed exit rule can fire.
        """
        try:
            await runner.start()
        except ServiceLaunchError:
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — any start failure must surface
            self._on_status(
                ServiceStatusEvent(
                    runner.name, ServiceStatus.failed,
                    detail="Start failed",
                    error=f"Start failed: {type(e).__name__}: {e}",
                    level="ERROR",
                )
            )

    async def _start_after_tunnel(self, parent_name: str, runner: ServiceRunner) -> None:
        evt = self._tunnel_ready.get(parent_name)
        if evt is not None and not evt.is_set():
            await evt.wait()
        await self._guarded_start(runner)

    async def _main(self) -> int:
        self._stop_event = asyncio.Event()

        loop = asyncio.get_running_loop()
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self._stop_event.set)
                except (NotImplementedError, RuntimeError):
                    pass

        for svc in self._services:
            if "/" not in svc.name:
                runner = self._runners.get(svc.name)
                evt = asyncio.Event()
                if runner is None or not isinstance(runner, TunnelAwareRunner):
                    evt.set()
                self._tunnel_ready[svc.name] = evt

        tasks: list[asyncio.Task] = []
        started: list[ServiceRunner] = []
        for svc in self._services:
            runner = self._runners.get(svc.name)
            if runner is None:
                continue
            started.append(runner)
            if "/" in svc.name:
                parent = svc.name.split("/", 1)[0]
                tasks.append(asyncio.create_task(self._start_after_tunnel(parent, runner)))
            else:
                tasks.append(asyncio.create_task(self._guarded_start(runner)))
            tasks.append(asyncio.create_task(self._pump_logs(runner)))
            tasks.append(asyncio.create_task(self._pump_status(runner)))

        self._emit("foundry", f"running {len(started)} service(s) headless - Ctrl+C to stop")

        try:
            await self._stop_event.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            reason = "all services failed" if self._fatal else "shutting down"
            self._emit("foundry", f"{reason} - stopping services and tunnels")
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(
                *(r.stop() for r in started), return_exceptions=True
            )

        if self._fatal:
            self._emit("foundry", "exit 1 - every service failed to run", "ERROR")
            return 1
        self._emit("foundry", "shutdown complete")
        return 0

    def run(self) -> int:
        # A piped stdout on Windows is cp1252: one unencodable character in a
        # service's output would raise UnicodeEncodeError and kill the run.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            return asyncio.run(self._main())
        except KeyboardInterrupt:
            # Windows path (no add_signal_handler): children are reaped by
            # the emergency atexit/signal sweep in commands/run.py.
            return 0


__all__ = ["HeadlessServicesRunner", "headless_mode_requested"]
