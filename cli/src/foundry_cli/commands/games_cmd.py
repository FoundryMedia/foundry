"""``foundry games`` — register and list the caller's FCM games.

A game is STEP ONE of shipping on Foundry: builds, hosting, matchmaking queues and players all
hang off it. Registration was console-only until ST-2 (2026-09-13) found that a CI-driven
publisher — one whose whole pipeline is API keys — still had to click through the web console once
per game. Both commands here are key-capable (scope ``publish``).

The SLUG is derived server-side from the name (it is the launcher catalog id and the CDN path
segment, so it is immutable and must be predictable); ``create`` prints the slug and the FRN it
derived, because everything downstream — ``fcm push --game``, ``fmms queue create --game``,
``.foundry/config.yml``'s ``gameId`` — is keyed on the slug, not the title.
"""

from __future__ import annotations

import click

from foundry_cli.core import auth, fid


@click.group()
def games() -> None:
    """Your Foundry games (register, list)."""


@games.command(name="create")
@click.option("--name", required=True, help="Human-facing game title, e.g. 'Space Raiders'.")
@click.option("--engine", default=None,
              help="Engine/toolchain (default UNREAL; UNITY / GODOT accepted).")
def games_create(name: str, engine: str | None) -> None:
    """Register a new game under your publisher.

    The slug is DERIVED from --name (lower-cased, hyphenated) and is permanent - it is the
    launcher catalog id and the CDN path segment. A name that derives an already-taken slug is
    refused; pick a different one. Registering implies no build and no publish.
    """
    title = (name or "").strip()
    if not title:
        raise click.ClickException("--name cannot be empty.")
    token = auth.access_token(scope=auth.SCOPE_PUBLISH)
    body: dict[str, str] = {"name": title}
    if engine:
        body["engine"] = engine.strip().upper()
    row = fid.api_request("/v1/fcm/games", method="POST", token=token, body=body) or {}
    slug = row.get("slug") or "?"
    click.echo(click.style(f"✓ Registered {row.get('title') or title}", fg="green", bold=True))
    click.echo(f"  slug:   {slug}   (use it as --game / .foundry config gameId)")
    if row.get("frn"):
        click.echo(f"  frn:    {row['frn']}")
    click.echo(f"  engine: {row.get('engine') or 'UNREAL'}")


@games.command(name="list")
def games_list() -> None:
    """List the games registered under your publisher."""
    token = auth.access_token(scope=auth.SCOPE_PUBLISH)
    rows = fid.api_request("/v1/fcm/games", token=token) or []
    if not rows:
        click.echo("No games yet. Run `foundry games create --name \"My Game\"`.")
        return
    for g in rows:
        if not isinstance(g, dict):
            continue
        # distributionStatus is the Foundry-App publication gate; currentVersion is the live
        # stable release (empty for a game that has only test builds).
        state = g.get("distributionStatus") or "NOT_PUBLISHED"
        version = g.get("currentVersion") or "-"
        click.echo(f"{(g.get('slug') or '?'):<24} {state:<14} {version:<10} {g.get('title') or ''}")
