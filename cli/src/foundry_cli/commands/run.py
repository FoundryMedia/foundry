from __future__ import annotations

import sys
import click

from foundry_cli.core.cli import FoundryGroup
from foundry_cli.core.project.workspace import load_workspace
from foundry_cli.core.ui.runner import ServicesUI
from foundry_cli.core.services.factory import create_runner
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


def _run_services_ui(command: str) -> None:
    """Common logic for running services with the UI."""
    import click
    ctx = click.get_current_context()
    workspace, services_root, services = load_workspace(command=command)
    debug = bool((ctx.obj or {}).get("debug"))

    if debug:
        project_name = workspace.manifests[0].name or "Unnamed Project"
        print(f"Project: {project_name}")
        print(f"Services root: {services_root}")
        print(f"Command: {command}")

    if not services:
        if debug:
            print("No services found.")
        return

    if debug:
        print("Discovered services:")
        for svc in services:
            print(f"  - {svc.name} ({svc.kind}) [{svc.runtime.runtime}] ({svc.runtime.evidence})")
            print(f"    {svc.path}")

    runners = {svc.name: create_runner(svc, debug=debug, command=command) for svc in services}
    app = ServicesUI(services, runners, debug=debug)
    
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
@click.pass_context
def dev(ctx: click.Context) -> None:
    """Run the platform in development mode with the Services UI."""
    _run_services_ui("dev")


@run.command(add_help_option=False)
@click.pass_context
def build(ctx: click.Context) -> None:
    """Run the build command for all services."""
    _run_services_ui("build")
    
    