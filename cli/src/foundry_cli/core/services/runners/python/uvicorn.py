from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from foundry_cli.core.services.runners.base import (
    ServiceLogEvent,
    ServiceStatus,
    ServiceStatusEvent,
)
from foundry_cli.core.services.runners.process import ProcessBackedRunner


STARTUP_TIMEOUT_S = 120.0  # Longer timeout for pip install + uvicorn startup


def _get_python_cmd() -> str:
    """Get the python command for this platform."""
    if sys.platform == "win32":
        return "python"
    return "python3"


def _get_pip_cmd() -> str:
    """Get the pip command for this platform."""
    if sys.platform == "win32":
        return "pip"
    return "pip3"


class UvicornServiceRunner(ProcessBackedRunner):
    """Runs a FastAPI/Uvicorn service.
    
    Handles:
    - Installing dependencies from requirements.txt
    - Running uvicorn from the src directory
    - Readiness detection via stdout patterns
    """

    # Patterns that indicate the service is ready
    READY_PATTERNS = [
        re.compile(r"Uvicorn running on", re.I),
        re.compile(r"Application startup complete", re.I),
        re.compile(r"Started server process", re.I),
    ]

    def __init__(
        self,
        service,
        *,
        debug: bool = False,
        port: int | None = None,
        host: str = "0.0.0.0",
        command: str = "dev",
        args: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(service, debug=debug, command=command)
        self._port = port or 8000
        self._host = host
        self._args = args
        self._env = env or {}
        self._process_monitor_task: asyncio.Task | None = None
        self._ready_event: asyncio.Event = asyncio.Event()

    async def start(self) -> None:
        # Check for requirements.txt
        requirements_txt = self.cwd / "requirements.txt"
        
        # Determine the src directory (where main.py lives)
        src_dir = self.cwd / "src"
        if not src_dir.exists():
            src_dir = self.cwd  # Fall back to service root
        
        main_py = src_dir / "main.py"
        if not main_py.exists():
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="No main.py found",
                    error=f"Expected main.py in {src_dir}",
                    level="ERROR",
                )
            )
            return

        # Install dependencies if requirements.txt exists
        if requirements_txt.exists():
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.starting,
                    detail="Installing dependencies from requirements.txt",
                    level="INFO",
                )
            )
            
            pip_cmd = _get_pip_cmd()
            # Run pip without -q so we can see progress
            install_proc = await asyncio.create_subprocess_exec(
                pip_cmd, "install", "-r", str(requirements_txt),
                cwd=str(self.cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Merge stderr into stdout
            )
            
            # Stream pip output to logs
            assert install_proc.stdout is not None
            while True:
                line = await install_proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip("\r\n")
                if text:
                    await self._log_queue.put(
                        ServiceLogEvent(self.name, "stdout", f"[pip] {text}")
                    )
            
            await install_proc.wait()
            
            if install_proc.returncode != 0:
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.failed,
                        detail="Failed to install dependencies",
                        error=f"pip install exited with code {install_proc.returncode}",
                        level="ERROR",
                    )
                )
                return

        # Build uvicorn command
        cmd = self._build_uvicorn_command()
        
        # Build environment:
        # - UTF-8 encoding for proper Unicode support
        # - Unbuffered output so print() statements appear immediately
        run_env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
            **self._env,
        }
        
        proc = await self._spawn(cmd, cwd=src_dir, env=run_env)

        # Start monitor for process exit
        self._process_monitor_task = asyncio.create_task(self._monitor_process_health(proc))

        # Quick check for immediate failures
        await asyncio.sleep(0.5)
        if proc.returncode is not None:
            return  # Monitor handles status

        await self._status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail=f"Waiting for uvicorn to be ready on port {self._port}",
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
                        detail=f"Timed out waiting for uvicorn on port {self._port}",
                        error=f"Service didn't become healthy within {STARTUP_TIMEOUT_S:.0f}s.",
                        level="ERROR",
                    )
                )

    def _build_uvicorn_command(self) -> list[str]:
        """Build the uvicorn command."""
        python_cmd = _get_python_cmd()
        
        cmd = [
            python_cmd, "-m", "uvicorn",
            "main:app",
            "--host", self._host,
            "--port", str(self._port),
            "--log-level", "debug",
        ]
        
        if self._args:
            cmd.extend(self._args)
        
        return cmd

    async def _wait_for_ready(self, proc) -> None:
        """Wait for ready signal from stdout."""
        while True:
            if proc.returncode is not None:
                return  # Process exited, monitor handles status
            
            if self._ready_event.is_set():
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail=f"Listening on {self._host}:{self._port}",
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
        """Stop service and cancel monitor."""
        if self._process_monitor_task is not None:
            self._process_monitor_task.cancel()
            try:
                await self._process_monitor_task
            except asyncio.CancelledError:
                pass
            self._process_monitor_task = None
        await super().stop()
