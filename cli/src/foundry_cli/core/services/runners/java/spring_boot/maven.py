from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from typing import Literal

from foundry_cli.core.project.manifest import DebugConfig
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
        strict_health_ports: bool = False,
        dependency_manager: DependencyManager = "maven",
        command: str = "dev",
        args: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
        debug_config: DebugConfig | None = None,
    ) -> None:
        super().__init__(service, debug=debug, command=command)
        self._port = port
        self._actuator_port = actuator_port
        self._strict_health_ports = strict_health_ports
        self._dep = dependency_manager
        self._args = args
        self._env = env or {}
        self._debug_config = debug_config
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

        # Inject JDWP remote debug agent when debug config is present
        if self._debug_config is not None:
            suspend = "y" if self._debug_config.suspend else "n"
            jdwp_arg = (
                f"-agentlib:jdwp=transport=dt_socket,server=y,"
                f"suspend={suspend},address=*:{self._debug_config.port}"
            )
            cmd.append(f"-Dspring-boot.run.jvmArguments={jdwp_arg}")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.starting,
                    detail=f"Remote debugger listening on port {self._debug_config.port}"
                           + (" (suspend=y, waiting for debugger)" if self._debug_config.suspend else ""),
                    level="INFO",
                )
            )

        if self._args:
            # -D args are Maven system properties (e.g. -Dspring-boot.run.profiles=local)
            # — pass them directly on the command line.
            # Everything else is a Spring Boot application argument
            # — wrap in -Dspring-boot.run.arguments=.
            maven_props = [a for a in self._args if a.startswith("-D")]
            app_args = [a for a in self._args if not a.startswith("-D")]

            if self._strict_health_ports:
                # Enforce configured ports at runtime without editing application.yml.
                has_server_port_arg = any(a.startswith("--server.port=") for a in app_args)
                has_mgmt_port_arg = any(a.startswith("--management.server.port=") for a in app_args)
                if self._port is not None and not has_server_port_arg:
                    app_args.append(f"--server.port={self._port}")
                if self._actuator_port is not None and not has_mgmt_port_arg:
                    app_args.append(f"--management.server.port={self._actuator_port}")

            cmd.extend(maven_props)
            if app_args:
                cmd.append(f"-Dspring-boot.run.arguments={' '.join(app_args)}")
        elif self._strict_health_ports:
            app_args: list[str] = []
            if self._port is not None:
                app_args.append(f"--server.port={self._port}")
            if self._actuator_port is not None:
                app_args.append(f"--management.server.port={self._actuator_port}")
            if app_args:
                cmd.append(f"-Dspring-boot.run.arguments={' '.join(app_args)}")

        run_env = {**os.environ, **self._env}
        if "JAVA_HOME" not in run_env:
            # mvnw hard-requires JAVA_HOME; derive it from `java` on PATH so a
            # shell without the variable still runs.
            import shutil
            java = shutil.which("java")
            if java:
                run_env["JAVA_HOME"] = str(Path(java).parent.parent)
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
            actuator_open = _is_port_open(host, actuator_port) if actuator_port and actuator_port != port else main_open

            if not main_open:
                await asyncio.sleep(0.35)
                continue

            if self._strict_health_ports and actuator_port and actuator_port != port and not actuator_open:
                await asyncio.sleep(0.35)
                continue

            # Probe actuator port first (if configured), then fall back to app port.
            candidate_ports: list[int] = []
            if self._strict_health_ports:
                candidate_ports = [actuator_port or port]
            else:
                if actuator_port is not None:
                    candidate_ports.append(actuator_port)
                if port is not None and port not in candidate_ports:
                    candidate_ports.append(port)

            for probe_port in candidate_ports:
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

                    if (
                        actuator_port is not None
                        and actuator_port != port
                        and probe_port == port
                        and not actuator_open
                    ):
                        await self._status_queue.put(
                            ServiceStatusEvent(
                                self.name,
                                ServiceStatus.starting,
                                detail=(
                                    f"Configured actuator port {actuator_port} not reachable; "
                                    f"using app port {port} for health."
                                ),
                                level="WARN",
                            )
                        )

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