"""`foundry login` / `foundry logout` — platform sign-in for CLI commands that call Foundry
(e.g. `foundry build push`). Uses the desktop bearer flow; the refresh token is stored under
~/.foundry/credentials.json. FoundryError is rendered by the root group."""

from __future__ import annotations

import click

from foundry_cli.core import auth


@click.command()
@click.option("--email", "identifier", prompt="Email or username", help="Your Foundry email or username.")
@click.option("--password", prompt=True, hide_input=True, help="Your Foundry password.")
def login(identifier: str, password: str) -> None:
    """Sign in to Foundry (stores a session in ~/.foundry/credentials.json)."""
    user = auth.login(identifier, password)
    who = user.get("email") or user.get("displayName") or "your account"
    click.echo(click.style(f"✓ Signed in as {who}.", fg="green", bold=True))


@click.command()
def logout() -> None:
    """Sign out (revoke the stored session)."""
    auth.logout()
    click.echo("Signed out.")
