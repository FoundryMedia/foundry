"""Sidecar service runner for generic command-based services like OPA."""
from __future__ import annotations

import asyncio
import re
import socket
import sys
from pathlib import Path

from foundry_cli.core.project.manifest import SidecarConfig
from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runners.base import ServiceStatus, ServiceStatusEvent
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
        
        # Compile ready patterns
        self._ready_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in config.ready_patterns
        ]

    @property
    def name(self) -> str:
        """Service name used for log routing - must match the service list."""
        return self.service.name

    @property
    def display_name(self) -> str:
        """Display name for the UI."""
        return self._display_name

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
        from foundry_cli.core.services.runners.base import ServiceLogEvent
        await self._log_queue.put(
            ServiceLogEvent(self.name, "stdout", f"Starting: {' '.join(cmd)}", level="DEBUG")
        )
        await self._log_queue.put(
            ServiceLogEvent(self.name, "stdout", f"Working directory: {cwd}", level="DEBUG")
        )
        
        # Merge environment
        import os
        run_env = {**os.environ, **config.env} if config.env else None

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

        # Start readiness detection
        asyncio.create_task(self._wait_for_ready(proc))

    def _build_command(self) -> list[str]:
        """Build the command to run."""
        config = self._config
        cmd = [config.command]
        
        # Add configured arguments
        if config.args:
            cmd.extend(config.args)
        
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
