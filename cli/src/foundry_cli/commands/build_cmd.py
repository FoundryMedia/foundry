"""`foundry build push` — upload a game build to the Foundry Content Mesh (FCM).

The bytes go DIRECTLY to Cloudflare R2 via a presigned PUT (never through fid):
  POST /v1/fcm/builds (create + presign) -> PUT file to R2 -> POST /v1/fcm/builds/{id}/complete.
Requires an active publisher (the server enforces it); run `foundry login` first.
"""

from __future__ import annotations

import os

import click

from foundry_cli.core import auth, fid


@click.group()
def build() -> None:
    """Game build artifacts (FCM)."""


@build.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option(
    "--kind",
    type=click.Choice(["client", "server"], case_sensitive=False),
    default="client",
    show_default=True,
    help="Build face: a player client or a dedicated-server build.",
)
@click.option("--version", "version", default=None, help="Build version, e.g. 1.0.0.")
@click.option("--ram", "ram", type=int, default=None, help="Declared RAM in MB (sizing hint).")
@click.option("--cpu", "cpu", type=float, default=None, help="Declared CPU (sizing hint).")
@click.option("--engine", default=None, help="(server) engine, e.g. unreal/unity/godot.")
@click.option("--entrypoint", default=None, help="(server) launch entrypoint, e.g. Server.sh.")
def push(file, kind, version, ram, cpu, engine, entrypoint) -> None:
    """Upload a build FILE (.zip) to the Foundry Content Mesh."""
    token = auth.access_token()
    filename = os.path.basename(file)
    kind_u = kind.upper()

    req: dict = {"kind": kind_u, "filename": filename}
    if version:
        req["version"] = version
    if ram is not None:
        req["declaredRamMb"] = ram
    if cpu is not None:
        req["declaredCpu"] = cpu
    if kind.lower() == "server":
        if engine:
            req["engine"] = engine
        if entrypoint:
            req["entrypoint"] = entrypoint

    size_mb = os.path.getsize(file) / 1e6
    click.echo(f"Creating {kind_u.lower()} build for {filename} ({size_mb:.1f} MB)…")
    ticket = fid.api_request("/v1/fcm/builds", method="POST", token=token, body=req)

    click.echo("Uploading to Foundry storage…")
    fid.put_file(ticket["uploadUrl"], file)

    row = fid.api_request(f"/v1/fcm/builds/{ticket['buildId']}/complete", method="POST", token=token)
    status = row.get("status") if isinstance(row, dict) else None
    click.echo(
        click.style(f"✓ Uploaded build {ticket['buildId']}", fg="green", bold=True)
        + click.style(f" (status: {status}).", fg="green")
    )
