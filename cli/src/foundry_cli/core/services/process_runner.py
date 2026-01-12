from __future__ import annotations

import asyncio
from asyncio.subprocess import Process
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Sequence

from foundry_cli.core.services.service_runner import (
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)


async def _read_stream(
    service_name: str,
    stream_name: str,
    stream: asyncio.StreamReader,
    queue: "asyncio.Queue[ServiceLogEvent]",
) -> None:
    try:
        while True:
            raw = await stream.readline()
            if not raw:
                return
            line = raw.decode(errors="replace").rstrip("\r\n")
            await queue.put(ServiceLogEvent(service_name=service_name, stream=stream_name, line=line))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await queue.put(
            ServiceLogEvent(
                service_name=service_name,
                stream=stream_name,  # type: ignore[arg-type]
                line=f"<stream error: {e}>",
            )
        )


class ProcessBackedRunner(ServiceRunner):
    """Base class for runners that are backed by a single long-running subprocess."""

    def __init__(self, service, *, debug: bool = False) -> None:
        super().__init__(service)
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
        if self._proc and self._proc.returncode is None:
            return self._proc

        await self._status_queue.put(
            ServiceStatusEvent(self.name, ServiceStatus.starting, detail=f"Starting: {' '.join(argv)}")
        )

        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd or self.cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert self._proc.stdout is not None
        assert self._proc.stderr is not None

        self._reader_tasks = [
            asyncio.create_task(_read_stream(self.name, "stdout", self._proc.stdout, self._log_queue)),
            asyncio.create_task(_read_stream(self.name, "stderr", self._proc.stderr, self._log_queue)),
        ]

        if self._debug:
            # Emit as a plain line; the UI will decide how to style it.
            await self._log_queue.put(
                ServiceLogEvent(
                    self.name,
                    "stdout",
                    f"spawned pid={self._proc.pid} cwd={cwd or self.cwd}",
                )
            )

        return self._proc

    async def stop(self) -> None:
        if not self._proc:
            return

        proc = self._proc
        self._proc = None

        for t in self._reader_tasks:
            t.cancel()
        await asyncio.gather(*self._reader_tasks, return_exceptions=True)
        self._reader_tasks = []

        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                return

            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    return
                await proc.wait()

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
