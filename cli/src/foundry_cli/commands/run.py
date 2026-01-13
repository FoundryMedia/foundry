from __future__ import annotations

import click

from foundry_cli.core.cli import FoundryGroup
from foundry_cli.core.project.workspace import load_workspace
from foundry_cli.core.ui.runner import ServicesUI
from foundry_cli.core.services.factory import create_runner


@click.group(cls=FoundryGroup, invoke_without_command=False)
@click.option("-d", "--debug", is_flag=True, default=False, help="Show debug output (must appear before the subcommand; aliases will hoist it).")
@click.pass_context
def run(ctx: click.Context, debug: bool) -> None:
    """Start Foundry services locally."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    return


@run.command()
@click.pass_context
def dev(ctx: click.Context) -> None:
    """Run the platform in development mode with the Services UI."""
    workspace, services_root, services = load_workspace()
    debug = bool((ctx.obj or {}).get("debug"))

    if debug:
        project_name = workspace.manifests[0].name or "Unnamed Project"
        print(f"Project: {project_name}")
        print(f"Services root: {services_root}")

    if not services:
        if debug:
            print("No services found.")
        return

    if debug:
        print("Discovered services:")
        for svc in services:
            print(f"  - {svc.name} ({svc.kind}) [{svc.runtime.runtime}] ({svc.runtime.evidence})")
            print(f"    {svc.path}")

    runners = {svc.name: create_runner(svc, debug=debug) for svc in services}
    app = ServicesUI(services, runners, debug=debug)
    app.run()

    click.echo(click.style("Shutdown gracefully. Goodbye!", fg="green", bold=True))
    
    