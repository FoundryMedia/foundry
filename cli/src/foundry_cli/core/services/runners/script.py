"""Generic runner: launch a manifest-declared ``run.script`` VERBATIM.

Used for services whose runtime Foundry cannot detect (no pom.xml, no
package.json, no recognized framework evidence) but which declare how to
start themselves. Readiness is a TCP probe on ``run.port`` when configured;
otherwise a process that survives its first seconds is reported running.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import socket
import sys

from foundry_cli.core.services.runners.base import ServiceStatus, ServiceStatusEvent
from foundry_cli.core.services.runners.process import ProcessBackedRunner

STARTUP_TIMEOUT_S = 90.0
_NO_PORT_GRACE_S = 3.0


def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


class ScriptServiceRunner(ProcessBackedRunner):
    """Spawn ``run.script`` (+ ``run.args``) in the service directory."""

    def __init__(
        self,
        service,
        *,
        debug: bool = False,
        command: str = "dev",
        script: str,
        port: int | None = None,
        args: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(service, debug=debug, command=command)
        self._script = script
        self._port = port
        self._args = args
        self._env = env or {}
        self._process_monitor_task: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            cmd = shlex.split(self._script, posix=(sys.platform != "win32"))
        except ValueError as e:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="Invalid run.script",
                    error=f"Could not parse run.script: {e}",
                    level="ERROR",
                )
            )
            return
        if not cmd:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="Empty run.script",
                    error="run.script is empty.",
                    level="ERROR",
                )
            )
            return
        cmd.extend(self._args)

        run_env = {**os.environ, **self._env}
        proc = await self._spawn(cmd, cwd=self.cwd, env=run_env)
        self._process_monitor_task = asyncio.create_task(self._monitor_process_health(proc))

        await asyncio.sleep(0.25)
        if proc.returncode is not None:
            return  # monitor reports the exit

        if self._port is not None:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.starting,
                    detail=f"Waiting for port {self._port}",
                    level="DEBUG",
                )
            )
            try:
                await asyncio.wait_for(self._wait_for_port(proc), timeout=STARTUP_TIMEOUT_S)
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    await self._status_queue.put(
                        ServiceStatusEvent(
                            self.name, ServiceStatus.failed,
                            detail=f"Timed out waiting for port {self._port}",
                            error=f"Service didn't open port {self._port} within {STARTUP_TIMEOUT_S:.0f}s.",
                            level="ERROR",
                        )
                    )
        else:
            await asyncio.sleep(_NO_PORT_GRACE_S)
            if proc.returncode is None:
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail="Process running (no run.port configured to probe)",
                        level="INFO",
                    )
                )

    async def _wait_for_port(self, proc) -> None:
        while True:
            if proc.returncode is not None:
                return
            if _is_port_open("127.0.0.1", self._port):
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail=f"Listening on :{self._port}",
                        level="INFO",
                    )
                )
                return
            await asyncio.sleep(0.35)

    async def _monitor_process_health(self, proc) -> None:
        try:
            await proc.wait()
            code = proc.returncode
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"Process exited (code {code})",
                    error="Process terminated unexpectedly." if code == 0
                          else f"Process exited with code {code}. Check logs.",
                    level="ERROR",
                )
            )
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        if self._process_monitor_task is not None:
            self._process_monitor_task.cancel()
            try:
                await self._process_monitor_task
            except asyncio.CancelledError:
                pass
            self._process_monitor_task = None
        await super().stop()


__all__ = ["ScriptServiceRunner"]
