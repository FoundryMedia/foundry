from __future__ import annotations

from foundry_cli.core.project.service_runtime import ServiceRuntime
from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runners.base import ServiceRunner
from foundry_cli.core.services.runners.java.spring_boot.maven import SpringBootServiceRunner
from foundry_cli.core.services.runners.node.nextjs import NodeServiceRunner
from foundry_cli.core.services.runners.python.uvicorn import UvicornServiceRunner


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


def create_runner(service: DiscoveredService, *, debug: bool = False, command: str = "dev"):
    rt = service.runtime.runtime
    cfg = service.config

    # Maven / Spring Boot
    if rt == ServiceRuntime.spring_boot:
        return SpringBootServiceRunner(
            service,
            debug=debug,
            port=cfg.port or 8080,
            actuator_port=cfg.actuator_port or 9000,
            dependency_manager="maven",
            command=command,
            args=cfg.args,
            env=cfg.env,
        )

    # Next.js
    if rt == ServiceRuntime.nextjs:
        return NodeServiceRunner(
            service,
            debug=debug,
            port=cfg.port,
            command=command,
            args=cfg.args,
            env=cfg.env,
        )

    # FastAPI
    if rt == ServiceRuntime.fastapi:
        return UvicornServiceRunner(
            service,
            debug=debug,
            port=cfg.port,
            command=command,
            args=cfg.args,
            env=cfg.env,
        )

    # Fallback
    return _UnsupportedServiceRunner(service, command=command)
