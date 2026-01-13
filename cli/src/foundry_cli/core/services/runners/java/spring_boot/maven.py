from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from typing import Literal

from foundry_cli.core.services.health import HealthCheckConfig, wait_for_http_healthy
from foundry_cli.core.services.runners.base import ServiceStatus, ServiceStatusEvent
from foundry_cli.core.services.runners.process import ProcessBackedRunner


DependencyManager = Literal["maven", "gradle"]
STARTUP_TIMEOUT_S = 60.0


def _find_mvnw(service_dir: Path) -> Path | None:
    """Find Maven wrapper in the service directory."""
    for name in ("mvnw.cmd", "mvnw"):
        p = service_dir / name
        if p.exists():
            return p
    return None


def _is_port_open(host: str, port: int) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


class SpringBootServiceRunner(ProcessBackedRunner):
    """Runs a Spring Boot service via Maven wrapper.
    
    Uses HTTP health checks (actuator preferred) to determine readiness.
    A background monitor watches for process exit and marks service as failed.
    """

    def __init__(
        self,
        service,
        *,
        debug: bool = False,
        port: int | None = 8080,
        actuator_port: int | None = 9000,
        dependency_manager: DependencyManager = "maven",
        args: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(service, debug=debug)
        self._port = port
        self._actuator_port = actuator_port
        self._dep = dependency_manager
        self._args = args
        self._env = env or {}
        self._process_monitor_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._dep != "maven":
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"Unsupported dependency manager: {self._dep}",
                    error="Only Maven is supported right now.",
                    level="ERROR",
                )
            )
            return

        mvnw = _find_mvnw(self.cwd)
        if mvnw is None:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="No Maven wrapper found",
                    error="Expected mvnw.cmd (Windows) or mvnw in this service directory.",
                    level="ERROR",
                )
            )
            return

        if not (self.cwd / "pom.xml").exists():
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="No pom.xml",
                    error="Expected pom.xml in this service directory.",
                    level="ERROR",
                )
            )
            return

        cmd = [str(mvnw), "-q", "spring-boot:run"]
        if self._args:
            args_str = ",".join(self._args)
            cmd.append(f"-Dspring-boot.run.arguments={args_str}")

        run_env = {**os.environ, **self._env} if self._env else None
        proc = await self._spawn(cmd, cwd=self.cwd, env=run_env)

        # Start monitor immediately - emits "failed" if process ever exits
        self._process_monitor_task = asyncio.create_task(self._monitor_process_health(proc))

        # Quick check for immediate failures (missing deps, compile errors)
        await asyncio.sleep(0.25)
        if proc.returncode is not None:
            return  # Monitor handles status

        if self._port is not None:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.starting,
                    detail=f"Waiting for health (app:{self._port}, actuator:{self._actuator_port or self._port})",
                    level="DEBUG",
                )
            )
            try:
                await asyncio.wait_for(self._wait_for_ready(proc), timeout=STARTUP_TIMEOUT_S)
            except asyncio.TimeoutError:
                if proc.returncode is None:  # Only timeout if still running
                    await self._status_queue.put(
                        ServiceStatusEvent(
                            self.name, ServiceStatus.failed,
                            detail=f"Timed out waiting for readiness on port {self._port}",
                            error=f"Service didn't become healthy within {STARTUP_TIMEOUT_S:.0f}s.",
                            level="ERROR",
                        )
                    )
        else:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.starting,
                    detail="Process running; no port configured for health check",
                    level="DEBUG",
                )
            )

    async def _wait_for_ready(self, proc) -> None:
        """Poll HTTP health endpoints until service is ready. Exits if process dies."""
        host = "127.0.0.1"
        port = self._port
        actuator_port = self._actuator_port

        await asyncio.sleep(10.0)  # Give Spring Boot time to start

        while True:
            if proc.returncode is not None:
                return  # Process exited, monitor handles status

            main_open = _is_port_open(host, port)
            actuator_open = _is_port_open(host, actuator_port) if actuator_port and actuator_port != port else True

            if not main_open or (actuator_port and not actuator_open):
                await asyncio.sleep(0.35)
                continue

            probe_port = actuator_port or port
            for url, require_up in (
                (f"http://{host}:{probe_port}/actuator/health", True),
                (f"http://{host}:{probe_port}/health", True),
                (f"http://{host}:{probe_port}/", False),
            ):
                try:
                    await wait_for_http_healthy(
                        HealthCheckConfig(
                            url=url, timeout_s=5.0, interval_s=1.0,
                            startup_timeout_s=10.0, require_up_status=require_up,
                        )
                    )
                except Exception:
                    continue

                if proc.returncode is not None:
                    return  # Process died during check

                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail=f"Healthy: {url}",
                        level="INFO",
                    )
                )
                return

            await asyncio.sleep(0.35)

    async def _monitor_process_health(self, proc) -> None:
        """Background task that emits failed status when process exits."""
        try:
            await proc.wait()
            exit_code = proc.returncode
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"Process exited (code {exit_code})",
                    error="Process terminated unexpectedly." if exit_code == 0
                          else f"Process exited with code {exit_code}. Check logs.",
                    level="ERROR",
                )
            )
        except asyncio.CancelledError:
            pass  # Normal shutdown

    async def stop(self) -> None:
        """Stop service and cancel monitor to prevent spurious failure status."""
        if self._process_monitor_task is not None:
            self._process_monitor_task.cancel()
            try:
                await self._process_monitor_task
            except asyncio.CancelledError:
                pass
            self._process_monitor_task = None
        await super().stop()