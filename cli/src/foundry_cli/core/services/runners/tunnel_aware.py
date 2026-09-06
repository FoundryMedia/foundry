"""Composite runner that manages SSH tunnels alongside services.

When a service has an SSH tunnel configured, this runner:
1. Starts the SSH tunnel first
2. Waits for the tunnel to establish
3. Starts the actual service
4. When stopping, stops both service and tunnel
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

from foundry_cli.core.project.manifest import SshTunnelConfig as ManifestTunnelConfig
from foundry_cli.core.services.runners.base import (
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)
from foundry_cli.core.services.ssh_tunnel import SshTunnelRunner, SshTunnelConfig


class TunnelAwareRunner(ServiceRunner):
    """Wraps a service runner with SSH tunnel management.
    
    The tunnel is started before the service and kept alive until stop() is called.
    """

    def __init__(
        self,
        inner_runner: ServiceRunner,
        tunnel_config: ManifestTunnelConfig,
        workspace_root: Path | None = None,
        injected_env_keys: tuple[str, ...] = (),
    ) -> None:
        # Don't call super().__init__ since we're wrapping another runner
        self._inner = inner_runner
        # Convert from manifest config to ssh_tunnel config (which has extra properties)
        self._tunnel_config = SshTunnelConfig(
            local_port=tunnel_config.local_port,
            remote_host=tunnel_config.remote_host,
            remote_port=tunnel_config.remote_port,
            host=tunnel_config.host,
            user=tunnel_config.user,
            password=tunnel_config.password,
        )
        self._workspace_root = workspace_root
        self._injected_env_keys = tuple(injected_env_keys)
        self._tunnel: SshTunnelRunner | None = None
        self._inner_log_task: asyncio.Task | None = None
        self._inner_status_task: asyncio.Task | None = None
        self._combined_log_queue: asyncio.Queue[ServiceLogEvent] = asyncio.Queue()
        self._combined_status_queue: asyncio.Queue[ServiceStatusEvent] = asyncio.Queue()

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def display_name(self) -> str:
        return self._inner.display_name

    @property
    def cwd(self) -> Path:
        return self._inner.cwd

    @property
    def service(self):
        return self._inner.service

    async def _log(self, message: str, level: str = "DEBUG") -> None:
        """Helper to emit a log message."""
        await self._combined_log_queue.put(
            ServiceLogEvent(
                service_name=self.name,
                stream="stdout",
                line=message,
                level=level,
            )
        )

    async def start(self) -> None:
        """Start tunnel first, then the service."""
        cfg = self._tunnel_config
        
        await self._log(f"[tunnel] Configuring SSH tunnel: 0.0.0.0:{cfg.local_port} → {cfg.remote_host}:{cfg.remote_port} via {cfg.user}@{cfg.host}", "INFO")
        if self._injected_env_keys:
            await self._log(
                "[tunnel] dev target = PROD — service env carries: "
                + ", ".join(self._injected_env_keys)
                + " (values never logged)",
                "INFO",
            )
        
        # Emit starting status
        await self._combined_status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail=f"Establishing SSH tunnel to {cfg.host}",
                level="INFO",
            )
        )

        # Create the tunnel runner - pass our combined queue directly
        # so SSH logs go straight to the output without forwarding
        self._tunnel = SshTunnelRunner(
            service_name=self.name,
            config=cfg,
            workspace_root=self._workspace_root,
            log_queue=self._combined_log_queue,
        )
        
        # Start tunnel and wait for it to establish
        await self._log("[tunnel] Starting SSH connection...", "DEBUG")
        
        tunnel_ok = await self._tunnel.start()
        
        # Give time for any pending log messages
        await asyncio.sleep(0.2)
        
        if not tunnel_ok:
            await self._log("[tunnel] SSH tunnel failed to establish", "ERROR")
            await self._combined_status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="SSH tunnel failed to establish",
                    error="Cannot start service without tunnel. Check SSH config, key file, and network.",
                    level="ERROR",
                )
            )
            return

        await self._log("[tunnel] SSH tunnel established successfully", "INFO")
        await self._combined_status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail="SSH tunnel established, starting service...",
                level="INFO",
            )
        )

        # Start forwarding inner runner's events BEFORE starting the service
        # so we see logs in real-time as the service starts up
        self._inner_log_task = asyncio.create_task(self._forward_inner_logs())
        self._inner_status_task = asyncio.create_task(self._forward_inner_status())

        # Now start the actual service
        await self._inner.start()

    async def stop(self) -> None:
        """Stop both the service and the tunnel."""
        # Cancel forwarding tasks
        if self._inner_log_task:
            self._inner_log_task.cancel()
        if self._inner_status_task:
            self._inner_status_task.cancel()

        # Stop service first
        await self._inner.stop()
        
        # Then stop tunnel
        if self._tunnel:
            await self._tunnel.stop()
        
        await self._log("[tunnel] SSH tunnel closed", "INFO")

    async def _forward_inner_logs(self) -> None:
        """Forward inner runner's log events to combined queue."""
        try:
            async for event in self._inner.events():
                await self._combined_log_queue.put(event)
        except asyncio.CancelledError:
            pass

    async def _forward_inner_status(self) -> None:
        """Forward inner runner's status events to combined queue."""
        try:
            async for event in self._inner.status_events():
                await self._combined_status_queue.put(event)
        except asyncio.CancelledError:
            pass

    def events(self) -> AsyncIterator[ServiceLogEvent]:
        async def _gen() -> AsyncIterator[ServiceLogEvent]:
            while True:
                yield await self._combined_log_queue.get()
        return _gen()

    def status_events(self) -> AsyncIterator[ServiceStatusEvent]:
        async def _gen() -> AsyncIterator[ServiceStatusEvent]:
            while True:
                yield await self._combined_status_queue.get()
        return _gen()


__all__ = ["TunnelAwareRunner"]
