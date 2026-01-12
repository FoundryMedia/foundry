from __future__ import annotations

import asyncio
import sys
from asyncio.subprocess import Process
from typing import AsyncIterator

from foundry_cli.core.services.runner import ServiceLogEvent, ServiceRunner


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
        await queue.put(ServiceLogEvent(service_name=service_name, stream=stream_name, line=f"<stream error: {e}>") )


class SubprocessServiceRunner(ServiceRunner):
    """Default runner: one subprocess per service.

    For now we run a cross-platform Python stub so you get real processes,
    independent stdout streams, and realistic buffering behavior.

    Later we can swap based on `service.runtime.runtime`.
    """

    def __init__(self, service, *, debug: bool = False) -> None:
        super().__init__(service)
        self._debug = debug
        self._proc: Process | None = None
        self._queue: asyncio.Queue[ServiceLogEvent] = asyncio.Queue()
        self._reader_tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._proc and self._proc.returncode is None:
            return

        # Real subprocess per service. Stub prints periodic lines.
        code = (
            "import sys, time; "
            "name=sys.argv[1]; "
            "i=0; "
            "print(f'[{name}] process started', flush=True); "
            "\n"
            "\n"
            "\n"
            "\n"
        )
        # keep it readable
        code = (
            "import sys, time\n"
            "name=sys.argv[1]\n"
            "i=0\n"
            "print(f'[{name}] process started', flush=True)\n"
            "\n"
            "try:\n"
            "    while True:\n"
            "        i += 1\n"
            "        print(f'[{name}] hello world {i}', flush=True)\n"
            "        if i % 7 == 0:\n"
            "            print(f'[{name}] stderr sample {i}', file=sys.stderr, flush=True)\n"
            "        time.sleep(1)\n"
            "except KeyboardInterrupt:\n"
            "    pass\n"
        )

        self._proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-c",
            code,
            self.name,
            cwd=str(self.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert self._proc.stdout is not None
        assert self._proc.stderr is not None

        self._reader_tasks = [
            asyncio.create_task(_read_stream(self.name, "stdout", self._proc.stdout, self._queue)),
            asyncio.create_task(_read_stream(self.name, "stderr", self._proc.stderr, self._queue)),
        ]

        await self._queue.put(ServiceLogEvent(self.name, "stdout", f"<spawned pid={self._proc.pid} cwd={self.cwd}>") )

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
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    return
                await proc.wait()

    async def _wait_for_event(self) -> ServiceLogEvent:
        return await self._queue.get()

    async def _events(self) -> AsyncIterator[ServiceLogEvent]:
        while True:
            yield await self._wait_for_event()

    def events(self) -> AsyncIterator[ServiceLogEvent]:
        return self._events()
