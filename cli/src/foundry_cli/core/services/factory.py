from __future__ import annotations

from foundry_cli.core.project.service_runtime import ServiceRuntime
from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.spring_boot_runner import SpringBootServiceRunner
from foundry_cli.core.services.node_runner import NodeServiceRunner
from foundry_cli.core.services.uvicorn_runner import UvicornServiceRunner
from foundry_cli.core.services.service_runner import ServiceRunner


class _UnsupportedServiceRunner(ServiceRunner):
    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    def events(self):
        async def _empty():
            if False:
                yield None
        return _empty()


def create_runner(service: DiscoveredService, *, debug: bool = False):
    rt = service.runtime.runtime

    # Maven / Spring Boot
    if rt == ServiceRuntime.spring_boot:
        # TODO: infer port, or read from manifest/config.
        return SpringBootServiceRunner(
            service,
            debug=debug,
            port=8080,
            actuator_port=9000,
            dependency_manager="maven",
        )

    # Next.js
    if rt == ServiceRuntime.nextjs:
        return NodeServiceRunner(service, debug=debug)

    # FastAPI
    if rt == ServiceRuntime.fastapi:
        return UvicornServiceRunner(service, debug=debug)

    # Fallback
    return _UnsupportedServiceRunner(service)
