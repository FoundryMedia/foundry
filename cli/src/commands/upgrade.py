from __future__ import annotations
import os
import click
from typing import Optional

from src.core import version as _version
from src.core import updater as _updater

@click.command(name="upgrade", help="Update cli version.")
@click.option("--check-only", is_flag=True, help="Check for updates.")
@click.option("-y", "--yes", "assume_yes", is_flag=True, help="Assume yes for prompts.")
@click.option("--force", is_flag=True, help="Force re-download / reinstall even if versions match.")
def upgrade_cmd(check_only: bool, assume_yes: bool, force: bool) -> None:
    """
    Upgrade command scaffold:
    - Checks current local version and latest remote release.
    - If check_only, prints results and exits.
    - If an upgrade is available (or --force), prompts then performs the upgrade steps.

    TODO: implement actual download/replace logic in a safe, atomic way.
    """
    try:
        local, latest = _version.get_update_hint(timeout=1.0)
    except Exception as e:
        click.secho(f"Unable to determine versions: {type(e).__name__}: {e}", fg="red", err=True)
        raise SystemExit(2)

    if not latest:
        click.secho(f"Local: {local} — unable to determine latest remote release.", fg="yellow")
        if check_only:
            return

    if latest and _version.is_newer(local, latest):
        click.secho(f"Upgrade available: {local} -> {latest}", fg="green")
        if check_only:
            return
        if not assume_yes:
            if not click.confirm(f"Download and install {latest}?"):
                click.secho("Upgrade aborted.", fg="yellow")
                return
        # Perform the upgrade steps
        token = os.environ.get("GITHUB_TOKEN")
        try:
            result = _updater.perform_update_flow(token=token, assume_yes=assume_yes)
            click.secho(f"Updated to {result.get('version')} (asset {result.get('asset')})", fg="green", bold=True)
        except Exception as e:
            click.secho(f"Upgrade failed: {type(e).__name__}: {e}", fg="red", err=True)
            raise SystemExit(2)
    else:
        if force:
            click.secho(f"Forcing upgrade flow (current {local})", fg="magenta")
            click.secho("Upgrade logic not yet implemented. This is a scaffold.", fg="cyan")
        else:
            click.secho(f"Already up-to-date: {local}", fg="green")