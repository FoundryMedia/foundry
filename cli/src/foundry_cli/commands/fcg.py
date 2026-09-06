"""`foundry fcg` — Foundry Compute Grid: game-hosting capacity.

Configure a game's capacity policy from the CLI (parity with the console's FCG view):
  capacity show        the game's current policy (warm servers, burst ceiling, plan)
  capacity set         change it (read-modify-write; only the flags you pass change)

Vocabulary: WARM SERVERS = always-on capacity kept running for your game (paid plans);
BURST CEILING = the max concurrent servers your game may scale to (unset = the platform
default ceiling). Game scope defaults from the project's `.foundry/config.yml` gameId
(game-publisher projects), like `foundry fmms queue`. Run `foundry login` first.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import click

from foundry_cli.core import auth, fid
from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project import project_game_id


def _resolve_game(game_opt: str | None) -> str:
    """The game to operate on: an explicit --game (slug or FRN), else the project's .foundry gameId."""
    game = (game_opt or "").strip().lower() or project_game_id()
    if not game:
        raise FoundryError(
            "No game. Pass --game <slug>, or run inside a game-publisher project (.foundry/config.yml)."
        )
    return game


def _fetch_policy(token: str, game: str) -> dict:
    """GET the game's current capacity policy."""
    return fid.api_request(f"/v1/fcg/capacity-policy?game={quote(game, safe='')}", token=token) or {}


def _print_policy(policy: dict) -> None:
    burst = policy.get("maxBurst")
    ceiling = policy.get("platformCeiling")
    click.echo(click.style(policy.get("gameSlug", "?"), fg="cyan", bold=True))
    click.echo(f"  warm servers (always-on): {policy.get('warmServers', 0)}")
    click.echo(
        "  burst ceiling: "
        + (str(burst) if burst is not None else f"platform default ({ceiling})")
    )
    click.echo(f"  platform ceiling: {ceiling}")
    if policy.get("entitled"):
        click.echo(click.style("  always-on: available on your plan", fg="green"))
    else:
        click.echo(click.style("  always-on: needs a paid plan (warm servers stay 0)", fg="yellow"))


@click.group()
def fcg() -> None:
    """Compute Grid (FCG): game-hosting capacity."""


@fcg.group()
def capacity() -> None:
    """A game's capacity policy: warm (always-on) servers + burst ceiling."""


@capacity.command(name="show")
@click.option("--game", default=None, help="Game slug or FRN (else the project's .foundry gameId).")
@click.option("--json", "as_json", is_flag=True, help="Print the raw policy JSON.")
def capacity_show(game, as_json) -> None:
    """Show the game's capacity policy (warm servers, burst ceiling, platform ceiling)."""
    token = auth.access_token()
    policy = _fetch_policy(token, _resolve_game(game))
    if as_json:
        click.echo(json.dumps(policy, indent=2))
        return
    _print_policy(policy)


@capacity.command(name="set")
@click.option("--game", default=None, help="Game slug or FRN (else the project's .foundry gameId).")
@click.option("--warm", type=int, default=None,
              help="Warm (always-on) server count; >0 needs a paid plan.")
@click.option("--max-burst", type=int, default=None,
              help="Burst ceiling: max concurrent servers (within the platform ceiling).")
@click.option("--clear-max-burst", is_flag=True, default=False,
              help="Drop the burst ceiling back to the platform default.")
def capacity_set(game, warm, max_burst, clear_max_burst) -> None:
    """Change the policy (read-modify-write: only the flags you pass change)."""
    if max_burst is not None and clear_max_burst:
        raise FoundryError("--max-burst and --clear-max-burst are mutually exclusive.")
    if warm is None and max_burst is None and not clear_max_burst:
        raise FoundryError("Nothing to change. Pass --warm, --max-burst, or --clear-max-burst.")
    token = auth.access_token()
    key = _resolve_game(game)
    # Seed from the CURRENT policy, then overlay the flags (like `fmms queue update`).
    current = _fetch_policy(token, key)
    body = {
        "warmServers": warm if warm is not None else current.get("warmServers", 0),
        "maxBurst": None if clear_max_burst
        else (max_burst if max_burst is not None else current.get("maxBurst")),
    }
    policy = fid.api_request(
        f"/v1/fcg/capacity-policy?game={quote(key, safe='')}",
        method="PUT",
        token=token,
        body=body,
    ) or {}
    click.echo(click.style("✓ Capacity policy updated.", fg="green", bold=True))
    _print_policy(policy)
