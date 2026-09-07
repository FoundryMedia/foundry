"""Composite runner that manages SSH tunnels alongside services.

When a service has SSH tunnels configured, this runner:
1. Starts ALL tunnels first (in parallel)
2. Waits for every tunnel to establish — any failure fails the service
3. Starts the actual service
4. When stopping, stops both service and tunnels
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

    All tunnels are started (in parallel) before the service and kept alive
    until stop() is called. Fail-closed: if ANY tunnel fails to establish,
    already-open tunnels are closed and the service never starts.
    """

    def __init__(
        self,
        inner_runner: ServiceRunner,
        tunnel_configs: dict[str, ManifestTunnelConfig],
        workspace_root: Path | None = None,
        injected_env_keys: tuple[str, ...] = (),
    ) -> None:
        # Don't call super().__init__ since we're wrapping another runner
        self._inner = inner_runner
        # Convert from manifest config to ssh_tunnel config (which has extra properties)
        self._tunnel_configs: dict[str, SshTunnelConfig] = {
            name: SshTunnelConfig(
                local_port=tc.local_port,
                remote_host=tc.remote_host,
                remote_port=tc.remote_port,
                host=tc.host,
                user=tc.user,
                password=tc.password,
                bind_address=tc.bind_address,
            )
            for name, tc in tunnel_configs.items()
        }
        self._workspace_root = workspace_root
        self._injected_env_keys = tuple(injected_env_keys)
        self._tunnels: dict[str, SshTunnelRunner] = {}
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

    def _tunnel_label(self, tunnel_name: str) -> str:
        # The lone legacy tunnel keeps the historical bare "[tunnel]" label.
        if tunnel_name == "default" and len(self._tunnel_configs) == 1:
            return "[tunnel]"
        return f"[tunnel:{tunnel_name}]"

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
        """Start all tunnels first, then the service."""
        for tunnel_name, cfg in self._tunnel_configs.items():
            await self._log(
                f"{self._tunnel_label(tunnel_name)} Configuring SSH tunnel: "
                f"{cfg.bind_display}:{cfg.local_port} → {cfg.remote_host}:{cfg.remote_port} "
                f"via {cfg.user}@{cfg.host}",
                "INFO",
            )
        if self._injected_env_keys:
            await self._log(
                "[tunnel] dev target = PROD — service env carries: "
                + ", ".join(self._injected_env_keys)
                + " (values never logged)",
                "INFO",
            )

        # Emit starting status
        hosts = ", ".join(sorted({c.host for c in self._tunnel_configs.values()}))
        await self._combined_status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail=f"Establishing {len(self._tunnel_configs)} SSH tunnel(s) to {hosts}",
                level="INFO",
            )
        )

        # Create the tunnel runners - pass our combined queue directly
        # so SSH logs go straight to the output without forwarding
        self._tunnels = {
            tunnel_name: SshTunnelRunner(
                service_name=self.name,
                config=cfg,
                workspace_root=self._workspace_root,
                log_queue=self._combined_log_queue,
                tunnel_name=tunnel_name,
            )
            for tunnel_name, cfg in self._tunnel_configs.items()
        }

        await self._log("[tunnel] Starting SSH connection(s)...", "DEBUG")

        results = await asyncio.gather(
            *(t.start() for t in self._tunnels.values()), return_exceptions=True
        )
        failed = [
            tunnel_name
            for tunnel_name, ok in zip(self._tunnels.keys(), results)
            if ok is not True
        ]

        # Give time for any pending log messages
        await asyncio.sleep(0.2)

        if failed:
            await self._log(
                f"[tunnel] SSH tunnel(s) failed to establish: {', '.join(failed)}",
                "ERROR",
            )
            # Close whatever DID open — never leave half a tunnel set up.
            await asyncio.gather(
                *(t.stop() for t in self._tunnels.values()), return_exceptions=True
            )
            await self._combined_status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"SSH tunnel(s) failed: {', '.join(failed)}",
                    error="Cannot start service without all tunnels. Check SSH config, key file, and network.",
                    level="ERROR",
                )
            )
            return

        await self._log("[tunnel] All SSH tunnels established successfully", "INFO")
        await self._combined_status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail="SSH tunnels established, starting service...",
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
        """Stop both the service and the tunnels."""
        # Cancel forwarding tasks
        if self._inner_log_task:
            self._inner_log_task.cancel()
        if self._inner_status_task:
            self._inner_status_task.cancel()

        # Stop service first
        await self._inner.stop()

        # Then stop tunnels
        if self._tunnels:
            await asyncio.gather(
                *(t.stop() for t in self._tunnels.values()), return_exceptions=True
            )

        await self._log("[tunnel] SSH tunnel(s) closed", "INFO")

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
