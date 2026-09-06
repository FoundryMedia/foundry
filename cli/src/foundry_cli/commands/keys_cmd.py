"""`foundry keys` — your publisher signing key (BYO).

You sign your own game releases; Foundry never holds your private key. The keypair is
generated + kept on THIS machine (~/.foundry/keys/signing.json); only the public half is
registered with Foundry, which vouches for it in the signed publisher directory so players'
launchers trust your releases.

  foundry keys generate   create a local signing keypair (private stays here)
  foundry keys show       print your public key + key id
  foundry keys register   send your PUBLIC key to Foundry
  foundry keys list       list the keys Foundry has on file for you
"""

from __future__ import annotations

import click

from foundry_cli.core import auth, fid, minisign


@click.group()
def keys() -> None:
    """Manage your publisher signing key (BYO)."""


@keys.command()
@click.option("--force", is_flag=True, help="Overwrite an existing local key (the old one is lost).")
@click.option("--register/--no-register", default=True,
              help="Also register the new public key with Foundry (default: yes).")
def generate(force: bool, register: bool) -> None:
    """Create a signing keypair on THIS machine. The private key never leaves it."""
    existing = minisign.load()
    if existing and not force:
        raise click.ClickException(
            f"A signing key already exists ({existing['keyId']}) at {minisign.key_path()}.\n"
            "Use --force to replace it (the old private key is lost and any releases signed with "
            "it can only be verified until you rotate the directory)."
        )
    rec = minisign.generate()
    minisign.save(rec)
    click.echo(click.style(f"✓ Generated signing key {rec['keyId']}", fg="green", bold=True))
    click.echo(f"  private key: {minisign.key_path()} (keep it safe — it is not recoverable)")
    if register:
        _register(rec)
    else:
        click.echo("  run `foundry keys register` to send the public key to Foundry.")


@keys.command()
def show() -> None:
    """Print your local public key + key id."""
    rec = minisign.load()
    if not rec:
        raise click.ClickException("No local signing key. Run `foundry keys generate`.")
    click.echo(f"key id: {rec['keyId']}")
    click.echo(minisign.public_key_blob(rec))


@keys.command()
def register() -> None:
    """Send your local PUBLIC key to Foundry (registers it for the directory)."""
    rec = minisign.load()
    if not rec:
        raise click.ClickException("No local signing key. Run `foundry keys generate` first.")
    _register(rec)


@keys.command(name="list")
def list_keys() -> None:
    """List the signing keys Foundry has on file for you."""
    token = auth.access_token()
    rows = fid.api_request("/v1/publisher/keys", token=token) or []
    if not rows:
        click.echo("No signing keys registered. Run `foundry keys generate`.")
        return
    for k in rows:
        marker = click.style(" (active)", fg="green") if k.get("status") == "active" else f" ({k.get('status')})"
        click.echo(f"{k.get('keyId')}{marker}")


def _register(rec: dict) -> None:
    token = auth.access_token()
    row = fid.api_request("/v1/publisher/keys", method="POST", token=token,
                          body={"publicKey": minisign.public_key_blob(rec)})
    if not isinstance(row, dict):
        row = {}
    click.echo(click.style(f"✓ Registered public key {row.get('keyId', rec['keyId'])} with Foundry.",
                           fg="green"))
    click.echo(click.style(
        "  Note: installed launchers trust it once Foundry updates the signed publisher "
        "directory (an operator step today).", fg="yellow"))
