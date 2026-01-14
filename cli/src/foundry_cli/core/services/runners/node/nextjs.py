from __future__ import annotations

import asyncio
import json
import os
import re
import socket
from pathlib import Path
from typing import Literal

from foundry_cli.core.services.runners.base import ServiceStatus, ServiceStatusEvent
from foundry_cli.core.services.runners.process import ProcessBackedRunner


import sys


PackageManager = Literal["pnpm", "npm", "yarn"]
STARTUP_TIMEOUT_S = 90.0


def _get_package_manager_cmd(pm: PackageManager) -> str:
    """Get the correct command for the package manager on this platform."""
    if sys.platform == "win32":
        # On Windows, we need to use .cmd versions
        return f"{pm}.cmd"
    return pm


def _detect_package_manager(service_dir: Path) -> PackageManager:
    """Detect package manager from lockfile presence."""
    if (service_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (service_dir / "yarn.lock").exists():
        return "yarn"
    # Walk up to find workspace root lockfile
    cur = service_dir.parent
    while cur.parent != cur:
        if (cur / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (cur / "yarn.lock").exists():
            return "yarn"
        cur = cur.parent
    return "npm"


def _find_workspace_root(service_dir: Path) -> Path | None:
    """Find the monorepo workspace root (pnpm-workspace.yaml or package.json with workspaces)."""
    cur = service_dir
    while cur.parent != cur:
        if (cur / "pnpm-workspace.yaml").exists():
            return cur
        pkg = cur / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                if "workspaces" in data:
                    return cur
            except Exception:
                pass
        cur = cur.parent
    return None


def _get_package_scripts(package_json: Path) -> dict[str, str]:
    """Read scripts from a package.json file."""
    if not package_json.exists():
        return {}
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
        return data.get("scripts", {})
    except Exception:
        return {}


def _has_script(package_json: Path, script_name: str) -> bool:
    """Check if a package.json has a specific script."""
    scripts = _get_package_scripts(package_json)
    return script_name in scripts


def _is_port_open(host: str, port: int) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _extract_port_from_script(script: str) -> int | None:
    """Try to extract port from a script command like 'next dev --port 3000'."""
    # Match --port 3000, --port=3000, -p 3000, -p=3000
    patterns = [
        r"--port[=\s]+(\d+)",
        r"-p[=\s]+(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, script)
        if match:
            return int(match.group(1))
    return None


class NodeServiceRunner(ProcessBackedRunner):
    """Runs a Node.js service via pnpm/npm/yarn.

    Supports monorepo workspaces by running scripts from package.json.
    Uses HTTP readiness checks for web services.
    """

    # Patterns that indicate the service is ready
    READY_PATTERNS = [
        re.compile(r"✓ Ready in"),              # Next.js "✓ Ready in 1552ms"
        re.compile(r"ready in \d+", re.I),      # Vite "ready in 500ms"
        re.compile(r"Local:\s+http"),           # Generic dev server "Local: http://localhost:3000"
        re.compile(r"listening on", re.I),      # Express-style "Listening on port 3000"
        re.compile(r"started server on", re.I), # Next.js older versions
        re.compile(r"Watching for file changes"),  # tsc --watch
        re.compile(r"Found 0 errors\. Watching"),  # tsc --watch success
    ]

    def __init__(
        self,
        service,
        *,
        debug: bool = False,
        port: int | None = None,
        command: str = "dev",
        args: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(service, debug=debug, command=command)
        self._port = port
        self._args = args
        self._env = env or {}
        self._package_manager: PackageManager = "pnpm"
        self._workspace_root: Path | None = None
        self._process_monitor_task: asyncio.Task | None = None
        self._ready_event: asyncio.Event = asyncio.Event()

    async def start(self) -> None:
        package_json = self.cwd / "package.json"

        if not package_json.exists():
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="No package.json found",
                    error="Expected package.json in this service directory.",
                    level="ERROR",
                )
            )
            return

        # Check if the requested script exists
        if not _has_script(package_json, self._command):
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"No '{self._command}' script in package.json",
                    error=f"package.json does not have a '{self._command}' script.",
                    level="ERROR",
                )
            )
            return

        # Detect package manager and workspace root
        self._package_manager = _detect_package_manager(self.cwd)
        self._workspace_root = _find_workspace_root(self.cwd)

        # Try to extract port from script if not configured
        if self._port is None:
            scripts = _get_package_scripts(package_json)
            script_content = scripts.get(self._command, "")
            self._port = _extract_port_from_script(script_content)

        # Build the command
        if self._package_manager == "pnpm":
            cmd = self._build_pnpm_command()
        elif self._package_manager == "yarn":
            cmd = self._build_yarn_command()
        else:
            cmd = self._build_npm_command()

        run_env = {**os.environ, **self._env} if self._env else None
        
        # Run from workspace root if we have one and using pnpm
        cwd = self._workspace_root if self._workspace_root and self._package_manager == "pnpm" else self.cwd
        
        proc = await self._spawn(cmd, cwd=cwd, env=run_env)

        # Start monitor immediately - emits "failed" if process ever exits
        self._process_monitor_task = asyncio.create_task(self._monitor_process_health(proc))

        # Quick check for immediate failures
        await asyncio.sleep(0.25)
        if proc.returncode is not None:
            return  # Monitor handles status

        if self._port is not None:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.starting,
                    detail=f"Waiting for port {self._port} to be ready",
                    level="DEBUG",
                )
            )
            try:
                await asyncio.wait_for(self._wait_for_ready(proc), timeout=STARTUP_TIMEOUT_S)
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    await self._status_queue.put(
                        ServiceStatusEvent(
                            self.name, ServiceStatus.failed,
                            detail=f"Timed out waiting for readiness on port {self._port}",
                            error=f"Service didn't become healthy within {STARTUP_TIMEOUT_S:.0f}s.",
                            level="ERROR",
                        )
                    )
        else:
            # No port configured - wait for ready pattern in stdout
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.starting,
                    detail="Waiting for ready signal in output",
                    level="DEBUG",
                )
            )
            try:
                await asyncio.wait_for(self._wait_for_ready_no_port(proc), timeout=STARTUP_TIMEOUT_S)
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    # Timed out but process still running - consider it healthy
                    await self._status_queue.put(
                        ServiceStatusEvent(
                            self.name, ServiceStatus.healthy,
                            detail="Process running (no ready signal detected)",
                            level="INFO",
                        )
                    )

    def _build_pnpm_command(self) -> list[str]:
        """Build pnpm run command, using filter for monorepo."""
        pkg_name = self._get_package_name()
        pnpm_cmd = _get_package_manager_cmd("pnpm")
        
        if self._workspace_root and pkg_name:
            # Run from workspace root with filter
            cmd = [pnpm_cmd, "--filter", pkg_name, "run", self._command]
        else:
            # Run directly in service directory
            cmd = [pnpm_cmd, "run", self._command]
        
        if self._args:
            cmd.extend(["--", *self._args])
        return cmd

    def _build_npm_command(self) -> list[str]:
        """Build npm run command."""
        npm_cmd = _get_package_manager_cmd("npm")
        cmd = [npm_cmd, "run", self._command]
        if self._args:
            cmd.extend(["--", *self._args])
        return cmd

    def _build_yarn_command(self) -> list[str]:
        """Build yarn run command."""
        yarn_cmd = _get_package_manager_cmd("yarn")
        cmd = [yarn_cmd, self._command]
        if self._args:
            cmd.extend(self._args)
        return cmd

    def _get_package_name(self) -> str | None:
        """Get the package name from package.json."""
        package_json = self.cwd / "package.json"
        if not package_json.exists():
            return None
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            return data.get("name")
        except Exception:
            return None

    async def _wait_for_ready(self, proc) -> None:
        """Wait for ready signal from stdout or port availability as fallback."""
        host = "127.0.0.1"
        port = self._port
        
        # Primary: wait for "Ready" message in stdout (set by log watcher)
        # Secondary: poll for port as fallback
        while True:
            if proc.returncode is not None:
                return  # Process exited, monitor handles status
            
            # Check if ready event was set by log watcher
            if self._ready_event.is_set():
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail=f"Listening on port {port}",
                        level="INFO",
                    )
                )
                return

            await asyncio.sleep(0.25)

    async def _wait_for_ready_no_port(self, proc) -> None:
        """Wait for ready signal from stdout when no port is configured."""
        while True:
            if proc.returncode is not None:
                return  # Process exited, monitor handles status
            
            if self._ready_event.is_set():
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail="Ready",
                        level="INFO",
                    )
                )
                return

            await asyncio.sleep(0.25)

    def _check_ready_pattern(self, line: str) -> bool:
        """Check if a log line matches any ready pattern."""
        for pattern in self.READY_PATTERNS:
            if pattern.search(line):
                return True
        return False

    def events(self):
        """Yield log events, checking for ready patterns."""
        return self._events_with_ready_check()

    async def _events_with_ready_check(self):
        """Wrap parent events() to check for ready patterns."""
        async for event in super().events():
            # Check if this log line indicates the service is ready
            if not self._ready_event.is_set() and self._check_ready_pattern(event.line):
                self._ready_event.set()
            yield event

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
