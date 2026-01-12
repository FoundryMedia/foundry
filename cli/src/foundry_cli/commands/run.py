from __future__ import annotations

import click

from foundry_cli.core.cli import FoundryGroup
from foundry_cli.core.project.workspace import load_workspace
from foundry_cli.core.ui.service_coordinator import ServicesUI
from foundry_cli.core.services.subprocess_runner import SubprocessServiceRunner


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
    """Run the platform in development mode.

    This opens the turbo-like Services UI.

    For now this doesn't start real processes; it just prints hello-world logs.
    """
    workspace, services_root, services = load_workspace()

    debug = bool((ctx.obj or {}).get("debug"))

    project_name = workspace.manifests[0].name or "Unnamed Project"

    if debug:
        print(f"Project: {project_name}")
        print(f"Services root: {services_root}")

    if not services:
        if debug:
            print("No services found.")
        return

    if debug:
        print("Discovered services:")
        for svc in services:
            print(
                f"  - {svc.name} ({svc.kind}) [{svc.runtime.runtime}] ({svc.runtime.evidence})\n"
                f"    {svc.path}"
            )

    runners = {svc.name: SubprocessServiceRunner(svc, debug=debug) for svc in services}

    # Silence non-debug output; the UI is the output.
    app = ServicesUI(services, runners, debug=debug)
    app.run()
    
    