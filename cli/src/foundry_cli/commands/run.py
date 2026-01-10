from __future__ import annotations

import click

from foundry_cli.core.cli import FoundryGroup
from foundry_cli.core.project.platform import load_manifest_from_cwd


@click.group(cls=FoundryGroup, invoke_without_command=False)
def run() -> None:
    """Run Foundry services locally."""
    return


@run.command()
def dev() -> None:
    """Run the platform in development mode."""
    manifest = load_manifest_from_cwd()
    name = manifest.name or "Unnamed Platform"
    print(f"foundry run dev (scaffold) - platform: {name}")