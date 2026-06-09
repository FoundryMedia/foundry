"""``foundry sync`` — Reconcile manifest ↔ filesystem → workspace.yml.

Reads the manifest (intent), scans the filesystem (reality), resolves
directory names, and writes ``.foundry/workspace.yml`` — a simple path map
that tells Foundry where each service actually lives on disk.

Run this after:
- Adding or removing services in ``foundry.json``
- Renaming service directories
- Pulling changes that modify the project structure
- Any time you want to verify the workspace state
"""
from __future__ import annotations

from pathlib import Path

import click

from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project.dotfoundry import (
    detect_project_state,
    ensure_foundry_dir,
)


@click.command()
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Show what would be resolved without writing workspace.yml.",
)
@click.pass_context
def sync(ctx: click.Context, dry_run: bool) -> None:
    """Reconcile manifest and filesystem, then write workspace.yml."""
    try:
        _run_sync(dry_run=dry_run)
    except FoundryError as e:
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + click.style(str(e), fg="red")
        )
        raise SystemExit(1)


def _run_sync(*, dry_run: bool = False) -> None:
    """Core sync logic."""
    cwd = Path.cwd()
    state = detect_project_state(cwd)

    if not state.has_manifest:
        raise FoundryError(
            "No foundry.json found in the current directory.\n"
            "Run 'foundry init' to create a new platform first."
        )

    from foundry_cli.core.project.manifest import load_manifest_from_path
    from foundry_cli.core.project.workspace_config import (
        resolve_workspace,
        save_workspace_yml,
    )

    manifest = load_manifest_from_path(state.manifest_path)
    name = manifest.name or state.root.name
    version = manifest.data.get("schemaVersion", "?")

    click.echo(click.style(f"Syncing workspace: {name}", fg="blue", bold=True))
    click.echo(click.style(f"  Schema: v{version}", fg="white"))
    click.echo()

    # Resolve the workspace (path map + drift)
    workspace_data = resolve_workspace(state.root, manifest)

    # Display resolved services.
    # The services dict is {name: path_or_null}.
    # For a richer display we pull stack info from the manifest.
    services = workspace_data.get("services", {})
    if services:
        click.echo(click.style("Services:", fg="yellow", bold=True))
        for svc_name, path in services.items():
            svc_cfg = manifest.services_config.get(svc_name)
            kind = svc_cfg.kind if svc_cfg else "?"
            framework = svc_cfg.type if svc_cfg else "?"

            kind_color = "magenta" if kind == "backend" else (
                "cyan" if kind == "frontend" else "blue"
            )

            on_disk = path is not None
            disk_icon = "✓" if on_disk else "✗"
            disk_color = "green" if on_disk else "red"
            display_path = path or "(not found)"

            click.echo(
                f"  {click.style(disk_icon, fg=disk_color)} "
                f"{click.style(svc_name, fg='cyan'):24s} "
                f"{click.style(kind or '?', fg=kind_color):12s} "
                f"{click.style(framework or '?', fg='white'):15s} "
                f"{click.style(display_path, fg='bright_black')}"
            )
        click.echo()

    # Display drift
    drift = workspace_data.get("drift", {})
    if drift:
        _display_drift(drift)

    if dry_run:
        click.echo(click.style("[dry-run] Would write .foundry/workspace.yml", fg="cyan"))
        return

    # Write workspace.yml
    foundry_dir = ensure_foundry_dir(state.root)
    save_workspace_yml(workspace_data, foundry_dir)
    svc_count = len(services)
    click.echo(click.style(
        f"  ✓ .foundry/workspace.yml  ({svc_count} services resolved)",
        fg="green",
    ))

    if not drift:
        click.echo()
        click.echo(click.style("Workspace is in sync.", fg="green", bold=True))


def _display_drift(drift: dict) -> None:
    """Display drift information to the user."""
    undeclared = drift.get("undeclared", {})
    missing = drift.get("missing", [])
    mismatches = drift.get("mismatches", {})

    click.echo(click.style("Drift detected:", fg="yellow", bold=True))

    if undeclared:
        click.echo(click.style("  Undeclared (on disk, not in manifest):", fg="yellow"))
        for name, info in undeclared.items():
            kind = info.get("kind", "?")
            path = info.get("path", "?")
            click.echo(
                f"    {click.style(name, fg='cyan')}  "
                f"{click.style(kind, fg='white')}  {path}"
            )
        click.echo(click.style(
            "    → Add these to foundry.json or remove the directories.",
            fg="bright_black",
        ))

    if missing:
        click.echo(click.style("  Missing (in manifest, not on disk):", fg="red"))
        for name in missing:
            click.echo(f"    {click.style(name, fg='cyan')}")
        click.echo(click.style(
            "    → Create the directories or remove from foundry.json.",
            fg="bright_black",
        ))

    if mismatches:
        click.echo(click.style("  Mismatches (manifest ≠ filesystem):", fg="yellow"))
        for name, issues in mismatches.items():
            for issue in issues:
                click.echo(f"    {click.style(name, fg='cyan')}: {issue}")

    click.echo()
