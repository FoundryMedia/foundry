from __future__ import annotations

import asyncio
import socket
from pathlib import Path

from typing import Literal

from foundry_cli.core.services.health import HealthCheckConfig, wait_for_http_healthy
from foundry_cli.core.services.runners.base import ServiceStatus, ServiceStatusEvent
from foundry_cli.core.services.runners.process import ProcessBackedRunner


DependencyManager = Literal["maven", "gradle"]


def _find_mvnw(service_dir: Path) -> Path | None:
    for name in ("mvnw.cmd", "mvnw"):
        p = service_dir / name
        if p.exists():
            return p
    return None


def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


STARTUP_TIMEOUT_S = 60.0


class SpringBootServiceRunner(ProcessBackedRunner):
    """Runs a Spring Boot (Maven) service.

    Current readiness strategy:
    - If a port can be determined, wait for it to accept TCP connections.
    - Otherwise, mark healthy once the process is running.

    Notes:
    - This is intentionally conservative and works without requiring actuator.
    - Next iteration can read `server.port` from env/config and/or call an HTTP health endpoint.
    """

    def __init__(
        self,
        service,
        *,
        debug: bool = False,
        port: int | None = 8080,
        actuator_port: int | None = 9000,
        dependency_manager: DependencyManager = "maven",
    ) -> None:
        super().__init__(service, debug=debug)
        self._port = port
        self._actuator_port = actuator_port
        self._dep = dependency_manager

    async def start(self) -> None:
        if self._dep != "maven":
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name,
                    ServiceStatus.failed,
                    detail=f"Unsupported dependency manager: {self._dep}",
                    error="Only Maven is supported right now.",
                )
            )
            return

        mvnw = _find_mvnw(self.cwd)
        if mvnw is None:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name,
                    ServiceStatus.failed,
                    detail="No Maven wrapper found",
                    error="Expected mvnw.cmd (Windows) or mvnw in this service directory.",
                )
            )
            return

        pom = self.cwd / "pom.xml"
        if not pom.exists():
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name,
                    ServiceStatus.failed,
                    detail="No pom.xml",
                    error="Expected pom.xml in this service directory.",
                )
            )
            return

        proc = await self._spawn([str(mvnw), "-q", "spring-boot:run"], cwd=self.cwd)

        # If Maven fails quickly (missing deps, compilation failure), reflect that.
        await asyncio.sleep(0.25)
        if proc.returncode is not None and proc.returncode != 0:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name,
                    ServiceStatus.failed,
                    detail=f"Maven exited ({proc.returncode})",
                    error="mvn spring-boot:run failed. See logs above.",
                )
            )
            return

        # Readiness check strategy:
        # - If we know the port, prefer an HTTP health ping (Actuator if available).
        # - Always fail if the process exits before we confirm readiness.
        if self._port is not None:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name,
                    ServiceStatus.starting,
                    detail=f"Waiting for health (app:{self._port}, actuator:{self._actuator_port or self._port})",
                )
            )

            try:
                await asyncio.wait_for(
                    self._wait_for_ready(
                        proc,
                        host="127.0.0.1",
                        port=self._port,
                        actuator_port=self._actuator_port,
                    ),
                    timeout=STARTUP_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name,
                        ServiceStatus.failed,
                        detail=f"Timed out waiting for readiness on port {self._port}",
                        error=f"Service didn't become reachable/healthy within {STARTUP_TIMEOUT_S:.0f}s.",
                    )
                )
                return
            except RuntimeError as e:
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name,
                        ServiceStatus.failed,
                        detail="Process exited before ready",
                        error=str(e),
                    )
                )
                return

        # If we don't know the port yet, we can't do a real health check.
        # Keep it "starting" until we implement port discovery.
        await self._status_queue.put(
            ServiceStatusEvent(
                self.name,
                ServiceStatus.starting,
                detail="Process running; waiting for health check (port unknown)",
            )
        )

    async def _wait_for_port(self, host: str, port: int) -> None:
        while True:
            if _is_port_open(host, port):
                return
            await asyncio.sleep(0.25)

    async def _wait_for_ready(self, proc, *, host: str, port: int, actuator_port: int | None) -> None:
        """Wait for the service to become ready, or raise if the process exits."""

        while True:
            if proc.returncode is not None:
                raise RuntimeError(f"Service process exited with code {proc.returncode}.")

            # Prefer Spring Boot Actuator health if present.
            probe_port = actuator_port or port
            if _is_port_open(host, probe_port):
                for url in (
                    f"http://{host}:{probe_port}/actuator/health",
                    f"http://{host}:{probe_port}/health",
                    f"http://{host}:{probe_port}/",
                ):
                    try:
                        await wait_for_http_healthy(
                            HealthCheckConfig(
                                url=url,
                                timeout_s=0.75,
                                interval_s=0.35,
                                startup_timeout_s=0.75,
                            )
                        )
                        await self._status_queue.put(
                            ServiceStatusEvent(self.name, ServiceStatus.healthy, detail=f"Healthy: {url}")
                        )
                        return
                    except Exception:
                        # Try the next URL.
                        pass

            await asyncio.sleep(0.35)
