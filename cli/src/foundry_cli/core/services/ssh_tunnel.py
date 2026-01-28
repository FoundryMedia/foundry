"""SSH tunnel management for Foundry services.

Allows services to declare SSH tunnels that must be established before
the service starts (e.g., for database access through an SSH host).
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from foundry_cli.core.services.runners.base import ServiceLogEvent, ServiceStatus, ServiceStatusEvent
from foundry_cli.core.util.logger import LogLevel


@dataclass(frozen=True)
class SshTunnelConfig:
    """Configuration for an SSH tunnel.
    
    Models: ssh -i <password> -N -L <local_port>:<remote_host>:<remote_port> <user>@<host>
    """

    local_port: int
    remote_host: str
    remote_port: int
    host: str
    user: str = "ec2-user"
    password: str | None = None  # Path to private key (absolute or relative to manifest)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SshTunnelConfig":
        return cls(
            local_port=data["localPort"],
            remote_host=data["remoteHost"],
            remote_port=data["remotePort"],
            host=data["host"],
            user=data.get("user", "ec2-user"),
            password=data.get("password"),
        )
    
    @property
    def tunnel_spec(self) -> str:
        """Returns the -L argument value: local_port:remote_host:remote_port"""
        return f"{self.local_port}:{self.remote_host}:{self.remote_port}"
    
    @property
    def destination(self) -> str:
        """Returns the SSH destination: user@host"""
        return f"{self.user}@{self.host}"


def _is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class SshTunnelRunner:
    """Manages an SSH tunnel as a background process.
    
    The tunnel is started before the service and kept running until the service stops.
    """

    def __init__(
        self,
        service_name: str,
        config: SshTunnelConfig,
        workspace_root: Path | None = None,
        log_queue: asyncio.Queue[ServiceLogEvent] | None = None,
        status_queue: asyncio.Queue[ServiceStatusEvent] | None = None,
    ) -> None:
        self._service_name = service_name
        self._config = config
        self._workspace_root = workspace_root
        self._proc: asyncio.subprocess.Process | None = None
        # Use provided queues or create our own
        self._log_queue: asyncio.Queue[ServiceLogEvent] = log_queue or asyncio.Queue()
        self._status_queue: asyncio.Queue[ServiceStatusEvent] = status_queue or asyncio.Queue()
        self._reader_tasks: list[asyncio.Task[None]] = []

    @property
    def name(self) -> str:
        return f"{self._service_name}#tunnel"

    @property
    def display_name(self) -> str:
        return f"SSH Tunnel ({self._config.local_port} → {self._config.remote_host}:{self._config.remote_port})"

    def _resolve_password_path(self) -> Path | None:
        """Resolve the password (private key) file path.
        
        Resolution order:
        1. If absolute path, use as-is
        2. If relative, resolve relative to manifest (workspace_root)
        """
        if not self._config.password:
            return None
            
        path = Path(self._config.password)
        
        # If absolute, use as-is
        if path.is_absolute():
            return path if path.exists() else None
        
        # Relative paths are resolved relative to the manifest (workspace root)
        if self._workspace_root:
            manifest_relative_path = self._workspace_root / path
            if manifest_relative_path.exists():
                return manifest_relative_path
        
        return None

    async def start(self) -> bool:
        """Start the SSH tunnel.
        
        Returns True if the tunnel is established successfully.
        """
        cfg = self._config
        
        # Check if tunnel is already up (port already forwarded)
        if _is_port_open("127.0.0.1", cfg.local_port, timeout=0.5):
            await self._log_queue.put(
                ServiceLogEvent(
                    self._service_name, "stdout",
                    f"Port {cfg.local_port} already open - tunnel may already be active",
                    level="INFO"
                )
            )
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.healthy,
                    detail=f"Port {cfg.local_port} already forwarded",
                    level="INFO",
                )
            )
            return True

        # Build SSH command
        ssh_cmd = self._build_ssh_command()
        if ssh_cmd is None:
            # Check what's missing
            key_file = self._resolve_password_path()
            ssh_binary = self._find_ssh_binary()
            error_detail = []
            if not ssh_binary:
                error_detail.append("SSH binary not found")
            if cfg.password and not key_file:
                error_detail.append(f"Key file not found: {cfg.password}")
            
            await self._log_queue.put(
                ServiceLogEvent(
                    self._service_name, "stderr",
                    f"SSH tunnel setup failed: {', '.join(error_detail) or 'unknown error'}",
                    level="ERROR"
                )
            )
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="Cannot build SSH command",
                    error=', '.join(error_detail) or "SSH binary not found or identity file missing",
                    level="ERROR",
                )
            )
            return False

        # Log the command being run (mask the key path for security)
        cmd_display = ' '.join(ssh_cmd).replace(str(self._resolve_password_path() or ''), '<key>')
        await self._log_queue.put(
            ServiceLogEvent(
                self._service_name, "stdout",
                f"SSH command: {cmd_display}",
                level="DEBUG"
            )
        )

        await self._log_queue.put(
            ServiceLogEvent(
                self._service_name, "stdout",
                f"Starting SSH tunnel: localhost:{cfg.local_port} → {cfg.remote_host}:{cfg.remote_port} via {cfg.destination}",
                level="INFO"
            )
        )
        
        await self._status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail=f"Establishing tunnel to {cfg.host}",
                level="INFO",
            )
        )

        try:
            await self._log_queue.put(
                ServiceLogEvent(
                    self._service_name, "stdout",
                    f"[ssh] Spawning SSH process...",
                    level="DEBUG"
                )
            )
            
            self._proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            await self._log_queue.put(
                ServiceLogEvent(
                    self._service_name, "stdout",
                    f"[ssh] Process started with PID {self._proc.pid}",
                    level="DEBUG"
                )
            )

            # Start reading stderr for connection messages/errors
            if self._proc.stderr:
                self._reader_tasks.append(
                    asyncio.create_task(self._read_stderr(self._proc.stderr))
                )
                await self._log_queue.put(
                    ServiceLogEvent(
                        self._service_name, "stdout",
                        "[ssh] stderr reader task started",
                        level="DEBUG"
                    )
                )

            await self._log_queue.put(
                ServiceLogEvent(
                    self._service_name, "stdout",
                    f"[ssh] Waiting for port {cfg.local_port} to open (timeout: 30s)...",
                    level="DEBUG"
                )
            )
            
            # Yield to let stderr reader start processing
            await asyncio.sleep(0.1)

            # Wait for tunnel to establish (poll the local port)
            established = await self._wait_for_tunnel(timeout=30.0)
            
            if established:
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail=f"Tunnel established on port {cfg.local_port}",
                        level="INFO",
                    )
                )
                return True
            else:
                # Check if process died
                if self._proc.returncode is not None:
                    await self._status_queue.put(
                        ServiceStatusEvent(
                            self.name, ServiceStatus.failed,
                            detail=f"SSH process exited with code {self._proc.returncode}",
                            error="Check SSH credentials and network connectivity",
                            level="ERROR",
                        )
                    )
                else:
                    await self._status_queue.put(
                        ServiceStatusEvent(
                            self.name, ServiceStatus.failed,
                            detail=f"Timeout waiting for tunnel on port {cfg.local_port}",
                            error="Tunnel did not establish within 30 seconds",
                            level="ERROR",
                        )
                    )
                await self.stop()
                return False

        except FileNotFoundError as e:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="SSH binary not found",
                    error=str(e),
                    level="ERROR",
                )
            )
            return False
        except Exception as e:
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"Failed to start tunnel: {type(e).__name__}",
                    error=str(e),
                    level="ERROR",
                )
            )
            return False

    def _build_ssh_command(self) -> list[str] | None:
        """Build the SSH command arguments."""
        cfg = self._config
        
        # Find ssh binary
        ssh_binary = self._find_ssh_binary()
        if not ssh_binary:
            return None
        
        cmd = [str(ssh_binary)]
        
        # Add private key file if specified
        key_file = self._resolve_password_path()
        if cfg.password and not key_file:
            # Key file specified but not found - this is an error
            return None
        if key_file:
            cmd.extend(["-i", str(key_file)])
        
        # Standard tunnel options
        cmd.extend([
            "-N",  # Don't execute remote command
            "-o", "BatchMode=yes",  # Never prompt for password/passphrase
            "-o", "StrictHostKeyChecking=accept-new",  # Auto-accept new host keys
            "-o", "ServerAliveInterval=30",  # Keep connection alive
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",  # Exit if tunnel fails
            "-o", "ConnectTimeout=10",  # Don't wait forever to connect
            "-L", cfg.tunnel_spec,
            cfg.destination,
        ])
        
        return cmd

    def _find_ssh_binary(self) -> Path | None:
        """Find the SSH binary on the system."""
        # Common locations
        candidates = []
        
        if sys.platform == "win32":
            # Windows: check for Git Bash's ssh, OpenSSH, etc.
            candidates = [
                Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Git" / "usr" / "bin" / "ssh.exe",
                Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Git" / "usr" / "bin" / "ssh.exe",
                Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "OpenSSH" / "ssh.exe",
                Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local" / "Programs" / "Git" / "usr" / "bin" / "ssh.exe",
            ]
        else:
            candidates = [
                Path("/usr/bin/ssh"),
                Path("/usr/local/bin/ssh"),
            ]
        
        for candidate in candidates:
            if candidate.exists():
                return candidate
        
        # Fall back to PATH lookup
        import shutil
        ssh_in_path = shutil.which("ssh")
        return Path(ssh_in_path) if ssh_in_path else None

    async def _wait_for_tunnel(self, timeout: float = 30.0) -> bool:
        """Wait for the tunnel to become active by polling the local port."""
        start = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start < timeout:
            # Check if process died
            if self._proc and self._proc.returncode is not None:
                return False
            
            if _is_port_open("127.0.0.1", self._config.local_port, timeout=0.5):
                return True
            
            await asyncio.sleep(0.5)
        
        return False

    async def _read_stderr(self, stream: asyncio.StreamReader) -> None:
        """Read stderr and emit as log events.
        
        SSH output goes to stderr. We filter out verbose debug messages and only
        show meaningful messages to the user.
        """
        try:
            while True:
                raw = await stream.readline()
                if not raw:
                    return  # Stream ended, no need to log this
                line = raw.decode(errors="replace").rstrip("\r\n")
                if not line:
                    continue
                
                # Skip SSH debug messages entirely - they're noise
                if line.startswith("debug1:") or line.startswith("debug2:") or line.startswith("debug3:"):
                    continue
                
                # Determine log level based on content
                line_lower = line.lower()
                
                # Real errors
                if any(x in line_lower for x in ["permission denied", "connection refused", "no route", "timeout", "failed", "error:"]):
                    level = "ERROR"
                elif any(x in line_lower for x in ["warning", "could not"]):
                    level = "WARN"
                else:
                    # Don't spam with SSH internal messages
                    continue
                
                await self._log_queue.put(
                    ServiceLogEvent(
                        self._service_name, "stderr", f"[ssh] {line}",
                        level=level
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def stop(self) -> None:
        """Stop the SSH tunnel."""
        for task in self._reader_tasks:
            task.cancel()
        await asyncio.gather(*self._reader_tasks, return_exceptions=True)
        self._reader_tasks = []

        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    self._proc.kill()
                    await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                except Exception:
                    pass
            except Exception:
                pass
            
        self._proc = None
        
        await self._log_queue.put(
            ServiceLogEvent(
                self._service_name, "stdout",
                f"SSH tunnel stopped (port {self._config.local_port})",
                level="INFO"
            )
        )

    def events(self) -> AsyncIterator[ServiceLogEvent]:
        """Yield log events."""
        async def _gen() -> AsyncIterator[ServiceLogEvent]:
            while True:
                yield await self._log_queue.get()
        return _gen()

    def status_events(self) -> AsyncIterator[ServiceStatusEvent]:
        """Yield status events."""
        async def _gen() -> AsyncIterator[ServiceStatusEvent]:
            while True:
                yield await self._status_queue.get()
        return _gen()


__all__ = ["SshTunnelConfig", "SshTunnelRunner"]
