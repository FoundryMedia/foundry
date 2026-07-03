"""`foundry fcm` — upload game build artifacts to the Foundry Content Mesh (FCM).

  push    upload an already-packaged build (.zip client / .tar server) to FCM

The bytes go DIRECTLY to Cloudflare R2 via a presigned PUT (never through fid):
  POST /v1/fcm/builds (create + presign) -> PUT file to R2 -> POST /v1/fcm/builds/{id}/complete.
Requires an active publisher (the server enforces it); run `foundry login` first.

To PACKAGE a build locally first, use `foundry package --client` / `foundry package --server`.
Uploading does NOT publish: publishing to the Foundry App is a billed action done in the web
console (with checkout) — the CLI never charges you.

`foundry build push` is a DEPRECATED alias of `foundry fcm push` (kept so existing scripts work).
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from foundry_cli.core import auth, fid
from foundry_cli.core.errors import FoundryError

# Map a --type to the FCM engine specifier default (server/client are the two build faces).
_ENGINE_BY_TYPE = {"client": "unreal", "server": "unreal"}


def _project_game_id() -> str | None:
    """The gameId from .foundry/config.yml, walking up from CWD (game-publisher projects only).

    Lets `foundry fcm push` link the uploaded build to the project's game without an explicit
    --game — a push from inside a game project is unambiguous. Any read/parse problem just means
    "no default" (the push must never fail on config sniffing).
    """
    cwd = Path.cwd()
    for root in (cwd, *cwd.parents):
        for filename in ("config.yml", "config.yaml"):
            cfg_path = root / ".foundry" / filename
            if cfg_path.is_file():
                try:
                    import yaml

                    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    return None
                if cfg.get("kind") != "game-publisher":
                    return None
                game_id = cfg.get("gameId")
                return str(game_id).strip().lower() if game_id else None
    return None


def upload_build(
    file: str,
    *,
    kind: str = "client",
    version: str | None = None,
    engine: str | None = "unreal",
    entrypoint: str | None = None,
    image_ref: str | None = None,
    name: str | None = None,
    game: str | None = None,
    token: str | None = None,
) -> dict:
    """Upload a packaged build FILE to FCM (create -> presigned PUT -> complete).

    When ``game`` is set, the completed build is LINKED to that game (the console
    "Assign to game" action) so it never sits in the Unassigned bucket. Link failure
    never fails the push — the bytes are already up; the console action remains.

    Returns the completed build row (carries ``id`` + ``status``). Shared by
    ``foundry fcm push`` and its deprecated alias ``foundry build push``.
    """
    token = token or auth.access_token()
    filename = os.path.basename(file)
    kind_u = kind.upper()

    req: dict = {"kind": kind_u, "filename": filename}
    if name:
        # fid's BuildUploadRequest calls the human name field `label` (the console "Name").
        req["label"] = name
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

    if game:
        try:
            fid.api_request(
                f"/v1/fcm/builds/{row['id']}/game",
                method="POST",
                token=token,
                body={"gameSlug": game},
            )
            click.echo(click.style(f"✓ Linked to game '{game}'.", fg="green"))
        except FoundryError as exc:
            # Upload succeeded — a link failure (already assigned / not your game) is a warning,
            # and the console "Assign to game" action remains available.
            click.echo(click.style(f"note: build uploaded but not linked to '{game}': {exc}", fg="yellow"))
    return row


# ---------------------------------------------------------------------------
# `foundry fcm push` — the canonical upload command
# ---------------------------------------------------------------------------

@click.group()
def fcm() -> None:
    """Foundry Content Mesh — upload packaged game builds."""


@fcm.command(name="push")
@click.argument("path_to_build", metavar="PATH_TO_BUILD",
                type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option(
    "--type",
    "build_type",
    type=click.Choice(["client", "server"], case_sensitive=False),
    default="client",
    show_default=True,
    help="Build face: a player 'client' (.zip) or a dedicated 'server' (.tar).",
)
@click.option("--name", "name", default=None, help="Build label/name for this artifact.")
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
@click.option(
    "--game",
    default=None,
    help="Game slug to LINK this build to after upload (the console 'Assign to game' action). "
    "Defaults to the project's .foundry/config.yml gameId when run inside a game project; "
    "pass --game '' to skip linking.",
)
def fcm_push(path_to_build, build_type, name, version, engine, entrypoint, image_ref, game) -> None:
    """Upload a packaged build to FCM.

    PATH_TO_BUILD is the packaged artifact: a .zip for --type client, a .tar for --type server
    (produced by `foundry package --client` / `--server`).
    """
    if game is None:
        game = _project_game_id()
        if game:
            click.echo(f"Linking to game '{game}' (.foundry/config.yml) — pass --game '' to skip.")
    game = (game or "").strip().lower() or None
    upload_build(
        path_to_build,
        kind=build_type,
        version=version,
        engine=engine,
        entrypoint=entrypoint,
        image_ref=image_ref,
        name=name,
        game=game,
    )


# ---------------------------------------------------------------------------
# `foundry build` — DEPRECATED alias group (kept so existing scripts keep working)
# ---------------------------------------------------------------------------

@click.group(hidden=True)
def build() -> None:
    """DEPRECATED — renamed to `foundry fcm`. Use `foundry fcm push`."""


@build.command(name="push", hidden=True)
@click.argument("file", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option(
    "--kind",
    type=click.Choice(["client", "server"], case_sensitive=False),
    default="client",
    show_default=True,
    help="Build face: a player client or a dedicated-server build.",
)
@click.option("--name", "name", default=None, help="Build label/name for this artifact.")
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
    help="(server) the container image RepoTag this build's tar carries (e.g. mygame:1.0.0).",
)
def build_push(file, kind, name, version, engine, entrypoint, image_ref) -> None:
    """DEPRECATED alias of `foundry fcm push`. Upload a packaged build FILE to FCM."""
    click.echo(click.style(
        "note: `foundry build push` is deprecated — use `foundry fcm push`.", fg="yellow"))
    upload_build(
        file,
        kind=kind,
        version=version,
        engine=engine,
        entrypoint=entrypoint,
        image_ref=image_ref,
        name=name,
    )


@build.command(name="submit", hidden=True)
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
