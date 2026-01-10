from __future__ import annotations

import click

from foundry_cli.core.platform import load_manifest_from_cwd


@click.group()
def run() -> None:
    """Run Foundry services locally."""
    return


@run.command()
def dev() -> None:
    """Run the platform in development mode."""
    manifest = load_manifest_from_cwd()
    name = manifest.name or "Unnamed Platform"
    click.echo(f"foundry run dev (scaffold) - platform: {name}")