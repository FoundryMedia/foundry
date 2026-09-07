from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from asyncio.subprocess import Process
from pathlib import Path
from typing import AsyncIterator, Sequence

from foundry_cli.core.services.runners.base import (
    ServiceLaunchError,
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children (handles mvnw -> java on Windows).

    POSIX children are spawned with ``start_new_session=True`` (their own
    process group), so ``killpg`` targets exactly that service's tree — never
    foundry's own group.
    """
    import subprocess

    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=10.0)
        except Exception:
            pass
    else:
        try:
            pgid = os.getpgid(pid)
            if pgid == os.getpgid(0):
                # Child unexpectedly shares our group — signal just the pid.
                os.kill(pid, signal.SIGTERM)
            else:
                os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


# ── Live-child registry + emergency teardown ─────────────────────────
#
# Every spawned service process registers here so the whole set can be
# reaped when the foundry process itself dies (SIGTERM/SIGHUP, atexit).
# Without this, killing foundry left mvn/java children running against
# closed tunnels. (SIGKILL of foundry remains unfixable — nothing runs.)

_LIVE_PIDS: set[int] = set()


def _register_live_pid(pid: int) -> None:
    _LIVE_PIDS.add(pid)


def _unregister_live_pid(pid: int) -> None:
    _LIVE_PIDS.discard(pid)


def kill_all_live_children(*, force_after: float = 1.5) -> None:
    """Synchronously reap every registered child process tree.

    Safe to call from a signal handler or atexit — no asyncio involved.
    Idempotent: already-dead pids are skipped.
    """
    import subprocess
    import time

    pids = list(_LIVE_PIDS)
    if not pids:
        return

    if sys.platform == "win32":
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=10.0,
                )
            except Exception:
                pass
    else:
        groups: list[int] = []
        for pid in pids:
            try:
                pgid = os.getpgid(pid)
            except (ProcessLookupError, OSError):
                continue
            if pgid == os.getpgid(0):
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                continue
            groups.append(pgid)
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        if groups:
            time.sleep(force_after)
            for pgid in groups:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

    _LIVE_PIDS.clear()


# 8 MiB – large enough for Java stack traces, Docker JSON blobs, etc.
# The default asyncio limit is only 64 KiB; exceeding it raises
# "Separator is not found, and chunk exceed the limit".
_STREAM_READER_LIMIT = 8 * 1024 * 1024


async def _read_stream(
    service_name: str,
    stream_name: str,
    stream: asyncio.StreamReader,
    queue: "asyncio.Queue[ServiceLogEvent]",
) -> None:
    """Continuously read lines from a stream and queue them as log events."""
    try:
        while True:
            try:
                raw = await stream.readline()
            except ValueError:
                # Line exceeds even the increased limit – drain the entire
                # internal buffer so the stream can continue reading
                # subsequent lines.  Reading only a small chunk would leave
                # the oversized data in the buffer and the next readline()
                # would raise ValueError again immediately.
                try:
                    buf_len = len(stream._buffer)  # type: ignore[attr-defined]
                except Exception:
                    buf_len = _STREAM_READER_LIMIT
                raw = await stream.read(max(buf_len, 65536))
                if not raw:
                    return
                # Show first 500 chars so the log is useful but not huge.
                snippet = raw.decode(errors="replace")[:500]
                await queue.put(ServiceLogEvent(
                    service_name=service_name, stream=stream_name,
                    line=f"{snippet}... (line truncated – exceeded stream buffer limit)",
                ))
                continue
            if not raw:
                return
            line = raw.decode(errors="replace").rstrip("\r\n")
            await queue.put(ServiceLogEvent(service_name=service_name, stream=stream_name, line=line))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await queue.put(ServiceLogEvent(service_name=service_name, stream=stream_name, line=f"<stream error: {e}>"))


class ProcessBackedRunner(ServiceRunner):
    """Base class for runners backed by a subprocess."""

    def __init__(self, service, *, debug: bool = False, command: str = "dev") -> None:
        super().__init__(service, command=command)
        self._debug = debug
        self._proc: Process | None = None
        self._log_queue: asyncio.Queue[ServiceLogEvent] = asyncio.Queue()
        self._status_queue: asyncio.Queue[ServiceStatusEvent] = asyncio.Queue()
        self._reader_tasks: list[asyncio.Task[None]] = []

    async def _spawn(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> Process:
        """Spawn a subprocess and start reading its stdout/stderr."""
        if self._proc and self._proc.returncode is None:
            return self._proc

        argv_list = list(argv)
        if argv_list:
            argv_list[0] = Path(argv_list[0]).name

        await self._status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail=f"Initializing: {' '.join(argv_list)}",
                level="INFO",
            )
        )

        # Console isolation is load-bearing for the TUI. A child that inherits
        # our console's stdin handle (node and java both do this) can reset the
        # console input mode: echo comes back ON and VT mouse parsing dies —
        # the terminal then paints raw SGR mouse reports (^[[<35;x;yM ...) all
        # over the TUI and text selection stops working. DEVNULL stdin plus a
        # detached hidden console (Windows) keeps children off our console.
        spawn_kwargs: dict = {}
        if sys.platform == "win32":
            spawn_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            # Own process group/session: teardown can killpg the service's
            # whole tree (mvnw -> mvn -> java) without touching foundry's own
            # group, and the emergency sweep can reap it if foundry dies.
            spawn_kwargs["start_new_session"] = True

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd or self.cwd),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_READER_LIMIT,
                **spawn_kwargs,
            )
        except OSError as e:
            # ENOENT / EACCES / a bad cwd. This used to escape as an
            # unobserved task exception: no log line, no status, the
            # tunnels held open, and `--no-tui` never exited (a mvnw.cmd
            # exec'd on macOS sat there for 120s). Report it like any
            # other failure so the fatal-exit rule sees it.
            self._proc = None
            reason = e.strerror or str(e)
            msg = f"Cannot launch '{argv_list[0] if argv_list else '?'}': {reason}"
            await self._log_queue.put(
                ServiceLogEvent(self.name, "stderr", msg, level="ERROR")
            )
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="Process failed to launch",
                    error=msg,
                    level="ERROR",
                )
            )
            raise ServiceLaunchError(msg) from e
        _register_live_pid(self._proc.pid)

        assert self._proc.stdout is not None
        assert self._proc.stderr is not None

        self._reader_tasks = [
            asyncio.create_task(_read_stream(self.name, "stdout", self._proc.stdout, self._log_queue)),
            asyncio.create_task(_read_stream(self.name, "stderr", self._proc.stderr, self._log_queue)),
        ]

        await self._log_queue.put(
            ServiceLogEvent(self.name, "stdout", f"spawned pid={self._proc.pid} cwd={cwd or self.cwd}", level="DEBUG")
        )

        return self._proc

    async def stop(self) -> None:
        """Stop the subprocess, killing the entire process tree on Windows."""
        if not self._proc:
            return

        proc = self._proc
        pid = proc.pid
        self._proc = None

        for t in self._reader_tasks:
            t.cancel()
        await asyncio.gather(*self._reader_tasks, return_exceptions=True)
        self._reader_tasks = []

        if proc.returncode is None and pid is not None:
            if sys.platform == "win32":
                _kill_process_tree(pid)
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
            else:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    _kill_process_tree(pid)
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        pass

        if pid is not None:
            _unregister_live_pid(pid)

        # Close transport to avoid "Event loop is closed" errors on Windows
        try:
            if proc._transport is not None:
                proc._transport.close()
        except Exception:
            pass

        await asyncio.sleep(0.1)

    async def _events(self) -> AsyncIterator[ServiceLogEvent]:
        while True:
            yield await self._log_queue.get()

    def events(self) -> AsyncIterator[ServiceLogEvent]:
        return self._events()

    async def _status_events(self) -> AsyncIterator[ServiceStatusEvent]:
        while True:
            yield await self._status_queue.get()

    def status_events(self) -> AsyncIterator[ServiceStatusEvent]:
        return self._status_events()
