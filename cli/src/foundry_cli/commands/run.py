from __future__ import annotations

import sys
import click

from foundry_cli.core.cli import FoundryGroup
from foundry_cli.core.project.workspace import load_workspace, filter_services, DiscoveredService, ServiceKind
from foundry_cli.core.project.service_runtime import RuntimeMatch, ServiceRuntime
from foundry_cli.core.project.manifest import ServiceConfig
from foundry_cli.core.ui.runner import ServicesUI
from foundry_cli.core.services.factory import create_runner, create_sidecar_runner
from foundry_cli.core.logging import (
    suppress_async_cleanup_warnings,
    write_crash_log,
)


@click.group(cls=FoundryGroup, invoke_without_command=False)
@click.option("-d", "--debug", is_flag=True, default=False, help="Show debug output (must appear before the subcommand; aliases will hoist it).")
@click.pass_context
def run(ctx: click.Context, debug: bool) -> None:
    """Start Foundry services locally."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    return


run.help_tip = "VSCode users, in Settings set terminal.integrated.stickyScroll.enabled to false"


def _run_services_ui(command: str, *, filter_svc: str | None = None, migrate_db: bool = False) -> None:
    """Common logic for running services with the UI."""
    import click
    ctx = click.get_current_context()
    workspace, services_root, services, sidecars = load_workspace(command=command)
    debug = bool((ctx.obj or {}).get("debug"))

    # Apply service filter if specified
    if filter_svc:
        filter_names = [s.strip() for s in filter_svc.split(",") if s.strip()]
        if filter_names:
            known = {s.name for s in services}
            unknown = [n for n in filter_names if n not in known]
            if unknown:
                click.echo(click.style(
                    f"Warning: unknown service(s) in --filter: {', '.join(unknown)}",
                    fg="yellow",
                ))
                click.echo(f"  Available: {', '.join(sorted(known))}")
            services, sidecars = filter_services(services, sidecars, filter_names, workspace.root)

    if debug:
        project_name = workspace.manifests[0].name or "Unnamed Project"
        print(f"Project: {project_name}")
        print(f"Services root: {services_root}")
        print(f"Command: {command}")

    # Build list of services with their sidecars inserted right after them
    # Sidecars should appear as sub-items under their parent service
    all_services = []
    
    for svc in services:
        all_services.append(svc)
        
        # Add sidecars for this service right after it
        service_sidecars = [s for s in sidecars if s.parent_service == svc.name]
        for sidecar in service_sidecars:
            # Use a clean ID-safe name: parent/sidecar format
            sidecar_id = f"{svc.name}/{sidecar.name}"
            pseudo_service = DiscoveredService(
                name=sidecar_id,  # Clean ID for internal use
                path=workspace.root,
                runtime=RuntimeMatch(ServiceRuntime.unknown, f"sidecar: {sidecar.config.command}"),
                kind=ServiceKind.sidecar,
                config=ServiceConfig(),
            )
            all_services.append(pseudo_service)

    if not all_services:
        if debug:
            print("No services found.")
        return

    if debug:
        print("Discovered services:")
        for svc in services:
            print(f"  - {svc.name} ({svc.kind}) [{svc.runtime.runtime}] ({svc.runtime.evidence})")
            print(f"    {svc.path}")
            service_sidecars = [s for s in sidecars if s.parent_service == svc.name]
            for sidecar in service_sidecars:
                print(f"      +-- {sidecar.name} (sidecar: {sidecar.config.command})")

    # Create runners: sidecars use create_sidecar_runner, services use create_runner
    runners = {}
    for sidecar in sidecars:
        # Use parent/sidecar format as the key to match all_services
        sidecar_id = f"{sidecar.parent_service}/{sidecar.name}"
        # Display name shows tree hierarchy: └─ name#sidecar
        display_name = f"└─ {sidecar.name}#sidecar"
        runners[sidecar_id] = create_sidecar_runner(
            sidecar, workspace.root, debug=debug, sidecar_id=sidecar_id, display_name=display_name
        )
    for svc in services:
        runners[svc.name] = create_runner(
            svc, debug=debug, command=command, migrate_db=migrate_db,
            workspace_root=workspace.root,
        )

    app = ServicesUI(all_services, runners, debug=debug)
    
    # Suppress the asyncio cleanup warnings that happen on Windows
    suppress_async_cleanup_warnings()
    
    try:
        app.run()
    except KeyboardInterrupt:
        # User spammed Ctrl+C during shutdown - suppress the traceback
        pass
    except Exception as e:
        # Unexpected error - log it and show a friendly message
        log_path = write_crash_log(type(e), e, e.__traceback__, context="ServicesUI.run()")
        print(click.style(f"\nAn unexpected error occurred: {e}", fg="red", bold=True))
        print(click.style(f"Details written to: {log_path}", fg="yellow"))
        return

    print(click.style("Shutdown gracefully. Goodbye!", fg="green", bold=True))


@run.command(add_help_option=False)
@click.option("--filter", "filter_svc", default=None, help="Comma-separated list of services to run (dependencies are included automatically).")
@click.option("--migrate-db", "-mdb", is_flag=True, default=False, help="Run Liquibase database migrations before starting services that have a database block.")
@click.pass_context
def dev(ctx: click.Context, filter_svc: str | None, migrate_db: bool) -> None:
    """Run the platform in development mode with the Services UI."""
    _run_services_ui("dev", filter_svc=filter_svc, migrate_db=migrate_db)


@run.command(add_help_option=False)
@click.option("--filter", "filter_svc", default=None, help="Comma-separated list of services to run (dependencies are included automatically).")
@click.pass_context
def build(ctx: click.Context, filter_svc: str | None) -> None:
    """Run the build command for all services."""
    _run_services_ui("build", filter_svc=filter_svc)
    
    