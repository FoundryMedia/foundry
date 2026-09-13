"""`foundry login` / `foundry logout` — platform sign-in for CLI commands that call Foundry
(e.g. `foundry fcm push`). Uses the desktop bearer flow; the refresh token is stored under
~/.foundry/credentials.json. FoundryError is rendered by the root group.

In API-key mode (FOUNDRY_API_KEY_ID + FOUNDRY_API_KEY_SECRET set — CI) both commands print a
warning and skip: the key is the credential, there is no session to create or revoke."""

from __future__ import annotations

import click

from foundry_cli.core import auth


def _skipped_in_key_mode(command: str) -> bool:
    if not auth.api_key_mode():
        return False
    click.echo(click.style(auth.key_mode_notice(command), fg="yellow"), err=True)
    return True


@click.command()
@click.option("--email", "identifier", default=None, help="Your Foundry email or username (prompted if omitted).")
@click.option("--password", default=None, help="Your Foundry password (prompted if omitted).")
def login(identifier: str | None, password: str | None) -> None:
    """Sign in to Foundry (stores a session in ~/.foundry/credentials.json)."""
    if _skipped_in_key_mode("login"):
        return
    # Prompt here rather than on the options so API-key mode never asks for a password.
    identifier = identifier or click.prompt("Email or username")
    password = password or click.prompt("Password", hide_input=True)
    user = auth.login(identifier, password)
    who = user.get("email") or user.get("displayName") or "your account"
    click.echo(click.style(f"✓ Signed in as {who}.", fg="green", bold=True))


@click.command()
def logout() -> None:
    """Sign out (revoke the stored session)."""
    if _skipped_in_key_mode("logout"):
        return
    auth.logout()
    click.echo("Signed out.")
