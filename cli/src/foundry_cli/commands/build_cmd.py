"""`foundry build` — game build artifacts on the Foundry Content Mesh (FCM).

  push    upload an already-packaged build (.zip) to FCM
  submit  submit an uploaded CLIENT build for the $20 review

The bytes go DIRECTLY to Cloudflare R2 via a presigned PUT (never through fid):
  POST /v1/fcm/builds (create + presign) -> PUT file to R2 -> POST /v1/fcm/builds/{id}/complete.
Requires an active publisher (the server enforces it); run `foundry login` first.

To cook a UE project locally AND push it in one step, use `foundry publish`.
"""

from __future__ import annotations

import os

import click

from foundry_cli.core import auth, fid


def upload_build(
    file: str,
    *,
    kind: str = "client",
    version: str | None = None,
    engine: str | None = "unreal",
    entrypoint: str | None = None,
    image_ref: str | None = None,
    token: str | None = None,
) -> dict:
    """Upload a packaged build FILE to FCM (create -> presigned PUT -> complete).

    Returns the completed build row (carries ``id`` + ``status``). Shared by
    ``foundry build push`` and ``foundry publish``.
    """
    token = token or auth.access_token()
    filename = os.path.basename(file)
    kind_u = kind.upper()

    req: dict = {"kind": kind_u, "filename": filename}
    if version:
        req["version"] = version
    if engine:
        req["engine"] = engine
    if kind.lower() == "server" and entrypoint:
        req["entrypoint"] = entrypoint
    if kind.lower() == "server" and image_ref:
        # The container image RepoTag this tar carries; fid stores it so FCG runs this image.
        req["imageRef"] = image_ref

    size_mb = os.path.getsize(file) / 1e6
    click.echo(f"Creating {kind_u.lower()} build for {filename} ({size_mb:.1f} MB)…")
    ticket = fid.api_request("/v1/fcm/builds", method="POST", token=token, body=req)

    click.echo("Uploading to Foundry storage…")
    fid.put_file(ticket["uploadUrl"], file)

    row = fid.api_request(f"/v1/fcm/builds/{ticket['buildId']}/complete", method="POST", token=token)
    if not isinstance(row, dict):
        row = {}
    row.setdefault("id", ticket["buildId"])
    click.echo(
        click.style(f"✓ Uploaded build {row['id']}", fg="green", bold=True)
        + click.style(f" (status: {row.get('status')}).", fg="green")
    )
    return row


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
@click.option(
    "--engine",
    default="unreal",
    show_default=True,
    help="Build engine/toolchain: unreal (default), unity, godot.",
)
@click.option("--entrypoint", default=None, help="(server) launch entrypoint, e.g. Server.sh.")
@click.option(
    "--image-tag",
    "image_ref",
    default=None,
    help="(server) the container image RepoTag this build's tar carries (e.g. mygame:1.0.0); "
    "fid stores it so FCG runs this image.",
)
def push(file, kind, version, engine, entrypoint, image_ref) -> None:
    """Upload a packaged build FILE (.zip) to the Foundry Content Mesh."""
    upload_build(file, kind=kind, version=version, engine=engine, entrypoint=entrypoint, image_ref=image_ref)


@build.command()
@click.argument("build_id")
@click.option("--yes", "ack", is_flag=True, default=False, hidden=True)
def submit(build_id, ack) -> None:
    """Submit a build for publishing review. REMOVED — publishing is a billed action.

    Publishing to the Foundry App is a paid review and MUST go through the web checkout so you
    see and confirm the charge. The CLI can never trigger a charge. Publish from the dev console:
    open your game and use "Submit for review".
    """
    raise click.ClickException(
        "Publishing review moved to the web console (it's a billed action that needs an explicit "
        "checkout). Open your game at https://foundryplatform.app/console and use 'Submit for review'. "
        "The CLI cannot submit for publishing."
    )
