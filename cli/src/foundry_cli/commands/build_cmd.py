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
from foundry_cli.core.project import project_game_id

# Map a --type to the FCM engine specifier default (server/client are the two build faces).
_ENGINE_BY_TYPE = {"client": "unreal", "server": "unreal"}


def _project_game_id() -> str | None:
    """The gameId from .foundry/config.yml (game-publisher projects). See core.project.project_game_id.

    Lets `foundry fcm push` link the uploaded build to the project's game without an explicit
    --game — a push from inside a game project is unambiguous. Shared with `foundry fmms queue`.
    """
    return project_game_id()


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
    help="Game to LINK this build to after upload (the console 'Assign to game' action): a slug "
    "or the game FRN (frn:fgs:<orgNumber>:game/<slug>, copyable from the console). Defaults to "
    "the project's .foundry/config.yml gameId when run inside a game project; pass --game '' to skip.",
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
# `foundry fcm publish` — BYO: assemble + SIGN the manifest locally, then upload
# ---------------------------------------------------------------------------

def _load_publisher_config() -> dict:
    """Read the game-publisher .foundry/config.yml (publisher, gameId, build.*). Raises if absent."""
    import yaml  # lazy: only the publish path needs it
    from pathlib import Path

    d = Path.cwd()
    for base in [d, *d.parents]:
        for name in ("config.yml", "config.yaml"):
            p = base / ".foundry" / name
            if p.exists():
                cfg = yaml.safe_load(p.read_text("utf-8")) or {}
                if cfg.get("kind") == "game-publisher":
                    return cfg
    raise click.ClickException(
        "No .foundry/config.yml (kind: game-publisher) found. Run this inside a game project.")


@fcm.command(name="publish")
@click.argument("staged_dir", metavar="STAGED_DIR",
                type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--version", required=True, help="Release version, e.g. 1.0.0.")
@click.option("--prerelease", is_flag=True,
              help="Publish to the private test channel (snapshot); stable is untouched.")
@click.option("--channel", default="stable", show_default=True,
              help="Channel this release activates (ignored with --prerelease).")
@click.option("--min-launcher", "min_launcher", default="0.9.0", show_default=True,
              help="Minimum launcher version required to install this release.")
@click.option("--managed", is_flag=True,
              help="Managed signing: fid signs the manifest via your KMS key (no local key needed). "
                   "Default is BYO (sign locally).")
def fcm_publish(staged_dir, version, prerelease, channel, min_launcher, managed) -> None:
    """Publish a client release.

    STAGED_DIR is the cooked client tree (e.g. Saved/StagedBuilds/Windows from
    `foundry package --client`). The build files upload straight to storage. BYO
    (default): the signed manifest is produced HERE — Foundry never holds your key.
    --managed: fid signs the index via your per-publisher KMS key (the private key
    stays in the HSM). Stage with --prerelease, then flip the channel in the console
    or with `foundry fcm channel set`.
    """
    from pathlib import Path

    from foundry_cli.core import minisign, fcm_manifest as fm

    cfg = _load_publisher_config()
    slug = (cfg.get("gameId") or "").strip().lower()
    publisher = (cfg.get("publisher") or "").strip().lower()
    title = cfg.get("title") or slug
    exe = (cfg.get("build") or {}).get("executableRelpath")
    if not slug or not publisher:
        raise click.ClickException(".foundry/config.yml needs both `publisher` and `gameId`.")

    key = None
    if not managed:
        key = minisign.load()
        if not key:
            raise click.ClickException(
                "No local signing key. Run `foundry keys generate` (BYO) or pass --managed.")

    token = auth.access_token()

    # 1. content-address the staged build + assemble the immutable release doc
    click.echo(f"Hashing {Path(staged_dir).name}…")
    files, total = fm.content_address(Path(staged_dir), exe)
    doc = fm.release_doc(slug, version, files, total)
    doc_bytes = fm.serialize(doc)
    doc_sha = fm.sha256_bytes(doc_bytes)
    click.echo(f"  {len(files)} files, {total / 1e6:.1f} MB")

    # 2. BYO only: accumulate into the current signed root + SIGN it locally. (Managed: fid
    #    assembles + signs the index server-side from the uploaded release doc.)
    root_bytes = sig_text = None
    if not managed:
        existing = fm.fetch_index(f"https://cdn.foundryplatform.app/publishers/{publisher}/games/{slug}")
        root = fm.merge_release(
            existing, game_id=slug, publisher=publisher, title=title, version=version,
            doc_sha256=doc_sha, total_size=total, min_launcher_version=min_launcher,
            mandatory=False, channel=("snapshot" if prerelease else channel),
        )
        root_bytes = fm.serialize(root)
        sig_text = minisign.sign_bytes(
            root_bytes, key, f"signature for {publisher}/{slug} index",
            f"{publisher}/{slug}@{version}")
        click.echo(click.style(f"✓ Signed index.json locally with key {key['keyId']}", fg="green"))

    # 3. ask fid which content-addressed files are new (dedup) + get presigned PUT URLs
    prep = fid.api_request(
        f"/v1/fcm/games/{slug}/publish/prepare", method="POST", token=token,
        body={"version": version, "prerelease": prerelease,
              "files": [{"sha256": f["sha256"], "size": f["size"]} for f in files]})
    uploads = (prep or {}).get("uploads") or {}

    # 4. upload straight to storage (direct presigned PUTs — bytes never touch fid).
    #    Content types MUST mirror fid's PublishService presigns (signed into the URLs).
    by_sha = {f["sha256"]: f for f in files}
    new_files = [s for s in by_sha if s in uploads]
    click.echo(f"Uploading {len(new_files)} new files ({len(files) - len(new_files)} reused)…")
    for sha in new_files:
        fid.put_file(uploads[sha], str(Path(staged_dir) / by_sha[sha]["path"].replace("/", os.sep)),
                     content_type="application/octet-stream")
    _put_bytes(uploads["releaseDoc"], doc_bytes, "application/json")
    if not managed:
        # Managed: fid writes index.json + .minisig (KMS-signed) at complete; don't upload ours.
        _put_bytes(uploads["index"], root_bytes, "application/json")
        _put_bytes(uploads["indexSig"], sig_text.encode("utf-8"), "application/octet-stream")

    # 5. finalize — BYO: fid verifies the CLI-signed objects. Managed: fid assembles + KMS-signs.
    fid.api_request(f"/v1/fcm/games/{slug}/publish/complete", method="POST", token=token,
                    body={"version": version, "prerelease": prerelease,
                          "channel": ("snapshot" if prerelease else channel),
                          "minLauncher": min_launcher})
    signed = "fid (managed KMS)" if managed else f"key {key['keyId']} (BYO)"
    where = ("added (prerelease) - live on the private test channel (snapshot)"
             if prerelease else f"live on {channel}")
    click.echo(click.style(f"✓ Published {slug} {version} — {where}. Signed by {signed}.",
                           fg="green", bold=True))


@fcm.command(name="releases")
def fcm_releases() -> None:
    """List published releases + channel pointers (read from the signed index)."""
    from foundry_cli.core import fcm_manifest as fm

    cfg = _load_publisher_config()
    slug = (cfg.get("gameId") or "").strip().lower()
    publisher = (cfg.get("publisher") or "").strip().lower()
    index = fm.fetch_index(f"https://cdn.foundryplatform.app/publishers/{publisher}/games/{slug}")
    if not index:
        raise click.ClickException(f"No published index found for {publisher}/{slug}.")
    channels = index.get("channels") or {}
    releases = index.get("releases") or {}
    by_version = sorted(releases.items(), key=lambda e: e[1].get("publishedAt") or "", reverse=True)
    for version, meta in by_version:
        pointing = sorted(ch for ch, v in channels.items() if v == version)
        badge = f"  [{', '.join(pointing)}]" if pointing else ""
        size = meta.get("totalSize")
        size_s = f"{size / 1e6:,.1f} MB" if isinstance(size, (int, float)) else "?"
        click.echo(f"{version:<14} {meta.get('publishedAt', '?'):<28} {size_s:>12}{badge}")


@fcm.group()
def channel() -> None:
    """Distribution channel pointers (the signed index's channels map)."""


@channel.command(name="set")
@click.argument("channel_name", metavar="CHANNEL")
@click.argument("version")
@click.option("--managed", is_flag=True,
              help="Managed: fid re-signs the index via your KMS key. Default is BYO (re-sign locally).")
def channel_set(channel_name, version, managed) -> None:
    """Point CHANNEL (e.g. stable) at an already-published VERSION.

    The pointer lives INSIDE the signed index.json. BYO (default): re-sign the index
    on THIS machine + upload it. --managed: fid re-signs via your KMS key (the console
    "Change" button does the same). Rollback = point back at an older version.
    """
    from foundry_cli.core import minisign, fcm_manifest as fm

    cfg = _load_publisher_config()
    slug = (cfg.get("gameId") or "").strip().lower()
    publisher = (cfg.get("publisher") or "").strip().lower()
    ch = channel_name.strip().lower()
    token = auth.access_token()

    if managed:
        # fid validates the version is published, re-assembles + KMS-signs the index.
        fid.api_request(f"/v1/fcm/games/{slug}/publish/channel", method="POST", token=token,
                        body={"channel": ch, "version": version})
        click.echo(click.style(
            f"✓ {slug} {ch} -> {version} (managed, fid-signed) — live for launchers now.",
            fg="green", bold=True))
        return

    key = minisign.load()
    if not key:
        raise click.ClickException("No local signing key. Run `foundry keys generate` (BYO) or pass --managed.")

    index = fm.fetch_index(f"https://cdn.foundryplatform.app/publishers/{publisher}/games/{slug}")
    if not index:
        raise click.ClickException(f"No published index found for {publisher}/{slug}.")
    releases = index.get("releases") or {}
    if version not in releases:
        raise click.ClickException(
            f"{version} is not a published release. Published: {', '.join(sorted(releases)) or '(none)'}")
    prev = (index.get("channels") or {}).get(ch)
    index.setdefault("channels", {})[ch] = version

    root_bytes = fm.serialize(index)
    sig_text = minisign.sign_bytes(
        root_bytes, key, f"signature for {publisher}/{slug} index",
        f"{publisher}/{slug}@{version}")
    click.echo(click.style(f"✓ Re-signed index.json locally with key {key['keyId']}", fg="green"))

    # prepare/complete with files=[] — only the re-signed manifest objects move. complete()
    # also stamps the game's currentVersion; for a stable flip that is exactly right.
    prep = fid.api_request(
        f"/v1/fcm/games/{slug}/publish/prepare", method="POST", token=token,
        body={"version": version, "prerelease": False, "files": []})
    uploads = (prep or {}).get("uploads") or {}
    _put_bytes(uploads["index"], root_bytes, "application/json")
    _put_bytes(uploads["indexSig"], sig_text.encode("utf-8"), "application/octet-stream")
    fid.api_request(f"/v1/fcm/games/{slug}/publish/complete", method="POST", token=token,
                    body={"version": version, "prerelease": False, "channel": ch})
    click.echo(click.style(
        f"✓ {slug} {ch}: {prev or '(unset)'} -> {version} — live for launchers now.",
        fg="green", bold=True))


def _put_bytes(url: str, data: bytes, content_type: str) -> None:
    """PUT raw bytes to a presigned URL (small manifest objects)."""
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(data)
        tmp = tf.name
    try:
        fid.put_file(url, tmp, content_type=content_type)
    finally:
        os.unlink(tmp)


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
