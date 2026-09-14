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
            "If you have not registered it yet, run `foundry keys register` — you do NOT need "
            "--force for that.\n"
            "Use --force only to REPLACE it (the old private key is lost and any releases signed "
            "with it can only be verified until you rotate the directory)."
        )
    # Check the session BEFORE minting anything. Generating first and failing the register left a
    # local key Foundry had never seen, and the next (correct) attempt then hit the
    # "a signing key already exists" guard above and needed --force — which minted a SECOND key
    # (ST-2 walk, 2026-09-13). A key we cannot register is not worth writing to disk.
    token = auth.access_token() if register else None
    rec = minisign.generate()
    minisign.save(rec)
    click.echo(click.style(f"✓ Generated signing key {rec['keyId']}", fg="green", bold=True))
    click.echo(f"  private key: {minisign.key_path()} (keep it safe — it is not recoverable)")
    if register:
        _register(rec, token)
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


def _register(rec: dict, token: str | None = None) -> None:
    token = token or auth.access_token()
    row = fid.api_request("/v1/publisher/keys", method="POST", token=token,
                          body={"publicKey": minisign.public_key_blob(rec)})
    if not isinstance(row, dict):
        row = {}
    click.echo(click.style(f"✓ Registered public key {row.get('keyId', rec['keyId'])} with Foundry.",
                           fg="green"))
    # fid re-signs the publisher directory with the intermediate key on every registration
    # (FcmDirectoryService.republish) - this stopped being an operator step when the trust
    # hierarchy shipped, and the old note said otherwise for months (ST-75).
    click.echo("  Installed launchers trust it within ~5 minutes (Foundry re-signs the publisher "
               "directory automatically).")
