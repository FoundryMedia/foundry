from __future__ import annotations

import asyncio

from foundry_cli.core.services.service_runner import (
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)


class NodeServiceRunner(ServiceRunner):
    """Placeholder for Next.js / Node-based services."""

    def __init__(self, service, *, debug: bool = False) -> None:
        super().__init__(service)
        self._debug = debug
        self._status_timeout_s = 60.0

    async def start(self) -> None:
        # TODO: implement (pnpm/npm install, dev server, readiness checks)
        return

    async def stop(self) -> None:
        return

    def events(self):
        async def _empty():
            if False:
                yield None
        return _empty()

    def status_events(self):
        async def _one_shot():
            yield ServiceStatusEvent(
                self.name,
                ServiceStatus.starting,
                detail="Initializing (runner not implemented)",
            )
            await asyncio.sleep(self._status_timeout_s)
            yield ServiceStatusEvent(
                self.name,
                ServiceStatus.failed,
                detail="Timed out during initialization",
                error=(
                    "Next.js/Node runner not implemented yet, so readiness couldn't be confirmed. "
                    f"Timed out after {self._status_timeout_s:.0f}s."
                ),
            )
        return _one_shot()
