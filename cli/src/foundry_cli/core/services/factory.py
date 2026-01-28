from __future__ import annotations

from foundry_cli.core.project.service_runtime import ServiceRuntime
from foundry_cli.core.project.workspace import DiscoveredService
from foundry_cli.core.services.runners.base import ServiceRunner
from foundry_cli.core.services.runners.java.spring_boot.maven import SpringBootServiceRunner
from foundry_cli.core.services.runners.node.nextjs import NodeServiceRunner
from foundry_cli.core.services.runners.python.uvicorn import UvicornServiceRunner
from foundry_cli.core.services.runners.tunnel_aware import TunnelAwareRunner


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
    
    runner: ServiceRunner

    # Maven / Spring Boot
    if rt == ServiceRuntime.spring_boot:
        runner = SpringBootServiceRunner(
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
    elif rt == ServiceRuntime.nextjs:
        runner = NodeServiceRunner(
            service,
            debug=debug,
            port=cfg.port,
            command=command,
            args=cfg.args,
            env=cfg.env,
        )

    # FastAPI
    elif rt == ServiceRuntime.fastapi:
        runner = UvicornServiceRunner(
            service,
            debug=debug,
            port=cfg.port,
            command=command,
            args=cfg.args,
            env=cfg.env,
        )

    # Fallback
    else:
        runner = _UnsupportedServiceRunner(service, command=command)
    
    # Wrap with tunnel support if configured
    if cfg.ssh_tunnel is not None:
        # Get workspace root from service path (go up to find foundry.json)
        workspace_root = service.path
        while workspace_root.parent != workspace_root:
            if (workspace_root / "foundry.json").exists():
                break
            workspace_root = workspace_root.parent
        
        runner = TunnelAwareRunner(
            inner_runner=runner,
            tunnel_config=cfg.ssh_tunnel,
            workspace_root=workspace_root if (workspace_root / "foundry.json").exists() else None,
        )
    
    return runner
