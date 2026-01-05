from __future__ import annotations
import click

from src.core import version as _version
from src.core.services import update_service as _update_service


@click.command(name="upgrade", help="Update cli version.")
def upgrade_cmd() -> None:
    """
    Upgrade command:
    - Uses a single check_for_updates() call.
    - Prompts before performing the update.
    """
    try:
        local, latest, release = _version.check_for_updates(timeout=1.0, include_release=True)
    except Exception as e:
        click.secho(f"Unable to determine versions: {type(e).__name__}: {e}", fg="red", err=True)
        raise SystemExit(2)

    if not latest or not release:
        click.secho(f"Local: {local} — unable to determine latest remote release.", fg="yellow")
        return

    if not _version.is_newer(local, latest):
        click.secho(f"Already up-to-date: {local}", fg="green")
        return

    click.secho(f"Upgrade available: {local} -> {latest}", fg="green")
    if not click.confirm(f"Download and install {latest}?", default=False):
        click.secho("Upgrade aborted.", fg="yellow")
        return

    try:
        _update_service.execute_update(release)
    except SystemExit:
        # execute_update intentionally exits the process
        raise
    except Exception as e:
        click.secho(f"Upgrade failed: {type(e).__name__}: {e}", fg="red", err=True)
        raise SystemExit(2)
