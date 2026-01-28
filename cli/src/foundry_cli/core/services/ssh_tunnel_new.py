"""SSH tunnel management for Foundry services using pure Python (paramiko/sshtunnel).

Allows services to declare SSH tunnels that must be established before
the service starts (e.g., for database access through an SSH host).

This implementation uses the `sshtunnel` library (wrapping paramiko) for
cross-platform SSH tunneling without requiring system SSH binaries.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundry_cli.core.services.runners.base import ServiceLogEvent, ServiceStatus, ServiceStatusEvent


# Suppress verbose paramiko/sshtunnel logging
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("sshtunnel").setLevel(logging.WARNING)


@dataclass(frozen=True)
class SshTunnelConfig:
    """Configuration for an SSH tunnel.
    
    Models: ssh -i <key> -N -L <local_port>:<remote_host>:<remote_port> <user>@<host>
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
    """Manages an SSH tunnel using sshtunnel (paramiko-based, pure Python).
    
    The tunnel is started before the service and kept running until the service stops.
    """

    def __init__(
        self,
        service_name: str,
        config: SshTunnelConfig,
        workspace_root: Path | None = None,
        log_queue: asyncio.Queue[ServiceLogEvent] | None = None,
    ) -> None:
        self._service_name = service_name
        self._config = config
        self._workspace_root = workspace_root
        self._log_queue = log_queue or asyncio.Queue()
        self._status_queue: asyncio.Queue[ServiceStatusEvent] = asyncio.Queue()
        self._tunnel = None  # SSHTunnelForwarder instance

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

    async def _log(self, message: str, level: str = "INFO") -> None:
        """Emit a log event."""
        await self._log_queue.put(
            ServiceLogEvent(
                service_name=self._service_name,
                stream="stdout",
                line=message,
                level=level,
            )
        )

    async def start(self) -> bool:
        """Start the SSH tunnel.
        
        Returns True if the tunnel is established successfully.
        """
        cfg = self._config
        
        # Check if tunnel is already up (port already forwarded)
        if _is_port_open("127.0.0.1", cfg.local_port, timeout=0.5):
            await self._log(f"Port {cfg.local_port} already open - tunnel may already be active")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.healthy,
                    detail=f"Port {cfg.local_port} already forwarded",
                    level="INFO",
                )
            )
            return True

        # Resolve key file
        key_file = self._resolve_password_path()
        if cfg.password and not key_file:
            await self._log(f"SSH key file not found: {cfg.password}", level="ERROR")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="SSH key file not found",
                    error=f"Could not find key file: {cfg.password}",
                    level="ERROR",
                )
            )
            return False

        await self._log(f"Connecting to {cfg.host}...")
        await self._status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail=f"Establishing tunnel to {cfg.host}",
                level="INFO",
            )
        )

        try:
            # Import here to allow graceful error if sshtunnel not installed
            from sshtunnel import SSHTunnelForwarder
            
            # Create tunnel in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            
            def create_tunnel():
                tunnel = SSHTunnelForwarder(
                    (cfg.host, 22),
                    ssh_username=cfg.user,
                    ssh_pkey=str(key_file) if key_file else None,
                    remote_bind_address=(cfg.remote_host, cfg.remote_port),
                    local_bind_address=("127.0.0.1", cfg.local_port),
                    set_keepalive=30.0,
                )
                tunnel.start()
                return tunnel
            
            self._tunnel = await loop.run_in_executor(None, create_tunnel)
            
            # Verify tunnel is active
            if self._tunnel.is_active:
                actual_port = self._tunnel.local_bind_port
                await self._log(f"Tunnel established (localhost:{actual_port} → {cfg.remote_host}:{cfg.remote_port})")
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail=f"Tunnel active on port {actual_port}",
                        level="INFO",
                    )
                )
                return True
            else:
                await self._log("Tunnel failed to start", level="ERROR")
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.failed,
                        detail="Tunnel failed to start",
                        error="SSHTunnelForwarder did not become active",
                        level="ERROR",
                    )
                )
                return False

        except ImportError:
            await self._log("sshtunnel library not installed. Run: pip install sshtunnel", level="ERROR")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="Missing dependency",
                    error="sshtunnel library not installed",
                    level="ERROR",
                )
            )
            return False
            
        except Exception as e:
            error_msg = str(e)
            # Simplify common error messages
            if "Authentication failed" in error_msg:
                error_msg = "Authentication failed - check SSH key"
            elif "Connection refused" in error_msg:
                error_msg = f"Connection refused by {cfg.host}"
            elif "timed out" in error_msg.lower():
                error_msg = f"Connection to {cfg.host} timed out"
            elif "No such file" in error_msg:
                error_msg = f"SSH key file not found"
            
            await self._log(f"SSH tunnel failed: {error_msg}", level="ERROR")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="SSH tunnel failed",
                    error=error_msg,
                    level="ERROR",
                )
            )
            return False

    async def stop(self) -> None:
        """Stop the SSH tunnel."""
        if self._tunnel:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._tunnel.stop)
                await self._log("SSH tunnel closed")
            except Exception:
                pass
            self._tunnel = None

    def events(self):
        """Yield log events."""
        async def _gen():
            while True:
                yield await self._log_queue.get()
        return _gen()

    def status_events(self):
        """Yield status events."""
        async def _gen():
            while True:
                yield await self._status_queue.get()
        return _gen()


__all__ = ["SshTunnelConfig", "SshTunnelRunner"]
