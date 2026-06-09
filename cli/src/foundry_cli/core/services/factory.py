from __future__ import annotations

from pathlib import Path

from foundry_cli.core.project.service_runtime import ServiceRuntime
from foundry_cli.core.project.workspace import DiscoveredService, DiscoveredSidecar
from foundry_cli.core.services.runners.base import ServiceRunner
from foundry_cli.core.services.runners.java.spring_boot.maven import SpringBootServiceRunner
from foundry_cli.core.services.runners.node.nextjs import NodeServiceRunner
from foundry_cli.core.services.runners.python.uvicorn import UvicornServiceRunner
from foundry_cli.core.services.runners.sidecar import SidecarRunner
from foundry_cli.core.services.runners.tunnel_aware import TunnelAwareRunner
from foundry_cli.core.services.runners.migration import MigrationAwareRunner


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


def create_runner(service: DiscoveredService, *, debug: bool = False, command: str = "dev", migrate_db: bool = False):
    rt = service.runtime.runtime
    cfg = service.config
    
    runner: ServiceRunner

    strict_health_ports = False
    if cfg.strict_mode_enabled is True:
        # Strict mode enables strict checks by default unless explicitly disabled.
        strict_health_ports = cfg.strict_health_ports is not False
    elif cfg.strict_health_ports is True:
        # Explicit opt-in even when strict mode is off.
        strict_health_ports = True

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
            strict_health_ports=strict_health_ports,
            debug_config=cfg.debug,
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

    # Uvicorn (FastAPI, Starlette, etc.)
    elif rt == ServiceRuntime.uvicorn:
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
    
    # Wrap with migration support if --migrate-db and database config exists
    if migrate_db and cfg.database_config:
        from foundry_cli.core.project.manifest import DatabaseConfig as DC
        db_cfg = DC.from_dict(cfg.database_config)

        # Determine tunnel local port for host override
        tunnel_local_port = cfg.ssh_tunnel.local_port if cfg.ssh_tunnel else None

        # Get workspace root for resolving relative paths
        workspace_root = service.path
        while workspace_root.parent != workspace_root:
            if (workspace_root / "foundry.json").exists():
                break
            workspace_root = workspace_root.parent

        runner = MigrationAwareRunner(
            inner_runner=runner,
            db_config=db_cfg,
            workspace_root=workspace_root if (workspace_root / "foundry.json").exists() else service.path,
            tunnel_local_port=tunnel_local_port,
        )

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


def create_sidecar_runner(
    sidecar: DiscoveredSidecar,
    workspace_root: Path,
    *,
    debug: bool = False,
    sidecar_id: str | None = None,
    display_name: str | None = None,
) -> ServiceRunner:
    """Create a runner for a sidecar service.
    
    Sidecars are tied to their parent service and start alongside them.
    They use the SidecarRunner which handles generic commands.
    
    Args:
        sidecar: The discovered sidecar configuration
        workspace_root: Root directory of the workspace
        debug: Enable debug output
        sidecar_id: The unique ID for this sidecar (e.g., "parent/name") - used for lookups
        display_name: Optional display name (e.g., with indent for UI hierarchy)
    """
    from foundry_cli.core.project.manifest import ServiceConfig
    from foundry_cli.core.project.service_runtime import RuntimeMatch, ServiceRuntime
    
    # Build the sidecar ID if not provided
    if sidecar_id is None:
        sidecar_id = f"{sidecar.parent_service}/{sidecar.name}"
    
    # Create a pseudo DiscoveredService for the sidecar
    # (so it integrates with the existing UI and runner infrastructure)
    # IMPORTANT: name must match the key used in the runners dict for log routing
    pseudo_service = DiscoveredService(
        name=sidecar_id,  # Must match the runners dict key for lookups
        path=workspace_root,  # Sidecars run from workspace root by default
        runtime=RuntimeMatch(ServiceRuntime.unknown, f"sidecar: {sidecar.config.command}"),
        kind="sidecar",  # type: ignore
        config=ServiceConfig(),  # Sidecars have their own config
    )
    
    return SidecarRunner(
        pseudo_service,
        sidecar.config,
        workspace_root,
        debug=debug,
        sidecar_name=sidecar.name,
        display_name=display_name,
    )
