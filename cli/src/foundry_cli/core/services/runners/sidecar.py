"""Sidecar service runner for generic command-based services like OPA."""
from __future__ import annotations

import asyncio
import re
import socket
import subprocess
import sys
from pathlib import Path

from foundry_cli.core.project.manifest import SidecarConfig
from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runners.base import ServiceLogEvent, ServiceStatus, ServiceStatusEvent
from foundry_cli.core.services.runners.process import ProcessBackedRunner


STARTUP_TIMEOUT_S = 30.0


def _is_port_open(host: str, port: int) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


class SidecarRunner(ProcessBackedRunner):
    """Runs a sidecar service via a generic command.

    Supports:
    - Arbitrary commands with arguments
    - Port-based health checks
    - Log pattern-based readiness detection
    """

    def __init__(
        self,
        service: DiscoveredService,
        config: SidecarConfig,
        workspace_root: Path,
        *,
        debug: bool = False,
        sidecar_name: str | None = None,
        display_name: str | None = None,
    ) -> None:
        super().__init__(service, debug=debug, command="sidecar")
        self._config = config
        self._workspace_root = workspace_root
        self._sidecar_name = sidecar_name or service.name
        self._display_name = display_name or f"{self._sidecar_name}#sidecar"
        self._process_monitor_task: asyncio.Task | None = None
        self._ready_event: asyncio.Event = asyncio.Event()
        self._docker_container_id: str | None = None

        # Deterministic container name for reliable cleanup.
        # Sanitise the service name so it's a valid Docker name.
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", service.name)
        self._docker_container_name: str = f"foundry-{safe}"
        
        # Compile ready patterns
        self._ready_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in config.ready_patterns
        ]

    @property
    def _is_docker(self) -> bool:
        """Return True if this sidecar runs via `docker run`."""
        return self._config.command == "docker" and len(self._config.args) > 0 and self._config.args[0] == "run"

    @property
    def name(self) -> str:
        """Service name used for log routing - must match the service list."""
        return self.service.name

    @property
    def display_name(self) -> str:
        """Display name for the UI."""
        return self._display_name

    def _find_docker_container_id(self) -> str | None:
        """Find a running Docker container by name, falling back to port filter.

        Prefers the deterministic ``--name`` assigned in ``_build_command``;
        falls back to a ``publish=<port>`` filter for containers that were
        started before naming was added.
        """
        # 1. Try by container name (most reliable).
        try:
            result = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"name=^/{self._docker_container_name}$"],
                capture_output=True, text=True, timeout=5.0,
            )
            cid = result.stdout.strip().split("\n")[0].strip()
            if cid:
                return cid
        except Exception:
            pass

        # 2. Fallback: filter by published port.
        port = self._config.port
        if port is None:
            return None
        try:
            result = subprocess.run(
                ["docker", "ps", "-q", "--filter", f"publish={port}"],
                capture_output=True, text=True, timeout=5.0,
            )
            cid = result.stdout.strip().split("\n")[0].strip()
            return cid if cid else None
        except Exception:
            return None

    async def _remove_docker_container(self, ref: str) -> None:
        """Force-remove a Docker container by *ref* (name or ID)."""
        await self._log_queue.put(
            ServiceLogEvent(self.name, "stdout",
                            f"Removing Docker container {ref}...",
                            level="DEBUG")
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", ref,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **(
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if sys.platform == "win32"
                    else {}
                ),
            )
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        except Exception:
            pass

    async def stop(self) -> None:
        """Stop the sidecar, ensuring Docker containers are properly removed.

        Killing the ``docker run`` CLI process does **not** stop the
        container itself — the Docker daemon keeps it running.  We must
        explicitly ``docker rm -f`` the container so that the port is
        released before a restart attempt.
        """
        # Capture the container ID *before* killing the CLI process, because
        # the container is still running at this point.
        container_id = self._docker_container_id
        if container_id is None and self._is_docker:
            container_id = self._find_docker_container_id()

        # Cancel the process-monitor task so it doesn't emit a spurious
        # "failed" status when we tear down the process.
        if self._process_monitor_task is not None:
            self._process_monitor_task.cancel()
            try:
                await self._process_monitor_task
            except (asyncio.CancelledError, Exception):
                pass
            self._process_monitor_task = None

        # Drain any residual status events that the monitor may have
        # emitted between being cancelled and actually stopping, so they
        # don't leak into the next start cycle.
        while not self._status_queue.empty():
            try:
                self._status_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Let ProcessBackedRunner kill the docker CLI process & reader tasks.
        await super().stop()

        # Now forcibly remove the Docker container to free the port.
        # Prefer the deterministic name (always available) over the cached
        # container ID which may be stale.
        if self._is_docker:
            await self._remove_docker_container(self._docker_container_name)
            # Also remove by ID in case the name didn't match (e.g. the
            # container was started before naming was introduced).
            if container_id:
                await self._remove_docker_container(container_id)

            # Give the OS a moment to fully release the port binding.
            await asyncio.sleep(0.5)

        # Reset readiness state so the next start() goes through the full
        # readiness-check cycle again.
        self._ready_event.clear()
        self._docker_container_id = None

    async def start(self) -> None:
        config = self._config
        
        # Resolve working directory
        if config.cwd:
            cwd = self._workspace_root / config.cwd
        else:
            cwd = self._workspace_root
        
        if not cwd.exists():
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"Working directory does not exist: {cwd}",
                    error=f"Sidecar cwd '{config.cwd}' not found.",
                    level="ERROR",
                )
            )
            return

        # Build command
        cmd = self._build_command()
        
        # Log what we're about to run
        await self._log_queue.put(
            ServiceLogEvent(self.name, "stdout", f"Starting: {' '.join(cmd)}", level="DEBUG")
        )
        await self._log_queue.put(
            ServiceLogEvent(self.name, "stdout", f"Working directory: {cwd}", level="DEBUG")
        )
        
        # Merge environment
        import os
        run_env = {**os.environ, **config.env} if config.env else None

        # Pre-clean any orphaned container from a previous run so the port
        # is free.  This handles the case where the CLI process died without
        # a graceful stop (e.g. stream error, crash, user kill).
        if self._is_docker:
            await self._remove_docker_container(self._docker_container_name)
            await asyncio.sleep(0.3)

        try:
            proc = await self._spawn(cmd, cwd=cwd, env=run_env)
        except FileNotFoundError as e:
            await self._log_queue.put(
                ServiceLogEvent(self.name, "stderr", f"Command not found: {cmd[0]}", level="ERROR")
            )
            await self._log_queue.put(
                ServiceLogEvent(self.name, "stderr", f"Make sure '{config.command}' is installed and in your PATH", level="ERROR")
            )
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"Command not found: {cmd[0]}",
                    error=str(e),
                    level="ERROR",
                )
            )
            return
        except Exception as e:
            await self._log_queue.put(
                ServiceLogEvent(self.name, "stderr", f"Failed to start: {e}", level="ERROR")
            )
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"Failed to start sidecar",
                    error=str(e),
                    level="ERROR",
                )
            )
            return

        # Start monitor
        self._process_monitor_task = asyncio.create_task(self._monitor_process_health(proc))

        # Wait for readiness
        await asyncio.sleep(0.25)
        if proc.returncode is not None:
            return  # Monitor handles status

        # Capture the Docker container ID so we can force-remove it on stop.
        if self._is_docker:
            self._docker_container_id = self._find_docker_container_id()

        # Start readiness detection
        asyncio.create_task(self._wait_for_ready(proc))

    def _build_command(self) -> list[str]:
        """Build the command to run.

        For Docker containers, a deterministic ``--name`` flag is injected
        right after ``run`` so that we can reliably look up and force-remove
        the container during ``stop()``.
        """
        config = self._config
        cmd = [config.command]

        if config.args:
            args = list(config.args)

            # Inject --name for docker run commands (right after 'run').
            if self._is_docker and "--name" not in args:
                run_idx = args.index("run")
                args.insert(run_idx + 1, f"--name={self._docker_container_name}")

            cmd.extend(args)

        return cmd

    async def _wait_for_ready(self, proc) -> None:
        """Wait for the service to become ready."""
        config = self._config
        start_time = asyncio.get_event_loop().time()
        
        # Initial delay to let the process bind its port
        await asyncio.sleep(0.5)
        
        while proc.returncode is None:
            elapsed = asyncio.get_event_loop().time() - start_time
            
            # Check if ready via log patterns (set by events() processing)
            if self._ready_event.is_set():
                await self._emit_healthy()
                return
            
            # Check port if configured
            if config.port:
                port_open = _is_port_open("127.0.0.1", config.port)
                if port_open:
                    # If health path is configured, check it
                    if config.health_path:
                        if await self._check_http_health(config.port, config.health_path):
                            await self._emit_healthy()
                            return
                    else:
                        # Port is open, no health check needed
                        await self._emit_healthy()
                        return
            
            # Timeout check
            if elapsed > STARTUP_TIMEOUT_S:
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.failed,
                        detail=f"Startup timeout after {STARTUP_TIMEOUT_S}s",
                        error="Sidecar did not become ready in time.",
                        level="ERROR",
                    )
                )
                return
            
            await asyncio.sleep(0.5)

    async def _emit_healthy(self) -> None:
        """Emit healthy status."""
        config = self._config
        detail = "Ready"
        if config.port:
            detail = f"Ready on port {config.port}"
        
        await self._status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.healthy,
                detail=detail,
                level="INFO",
            )
        )

    async def _check_http_health(self, port: int, path: str) -> bool:
        """Check HTTP health endpoint."""
        try:
            import aiohttp
        except ImportError:
            # aiohttp not available, fall back to port-only check
            return True
        
        url = f"http://127.0.0.1:{port}{path}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def _monitor_process_health(self, proc) -> None:
        """Monitor process for unexpected exit."""
        await proc.wait()
        code = proc.returncode
        
        if code != 0:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"Process exited with code {code}",
                    error=f"Sidecar process terminated unexpectedly (exit code {code}).",
                    level="ERROR",
                )
            )

    def events(self):
        """Override to detect ready patterns in logs."""
        original_events = super().events()
        
        async def _wrapped_events():
            async for event in original_events:
                # Check for ready patterns
                if self._ready_patterns:
                    for pattern in self._ready_patterns:
                        if pattern.search(event.line):
                            self._ready_event.set()
                            break
                yield event
        
        return _wrapped_events()
