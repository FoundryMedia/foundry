"""`foundry fcg` — Foundry Compute Grid: game-hosting capacity.

Configure a game's capacity policy from the CLI (parity with the console's FCG view):
  capacity show        the game's current policy (servers, idle shutdown, budget, plan)
  capacity set         change it (only the flags you pass change)
  footprint            what your game's servers actually use, and the size that would fit

Vocabulary: WARM SERVERS = always-on capacity kept running for your game (one is included per
game and spends your server minutes while idle; `--warm 0` turns it off; more needs Reserved);
BURST CEILING = the max concurrent servers your game may scale to (unset = the platform
default ceiling); READY SERVERS = spare servers kept free while players are online; IDLE SHUTDOWN =
minutes an empty server stays up before it is shut down; MONTHLY BUDGET = a USD cap on the game's
server spend. Game scope defaults from the project's `.foundry/config.yml` gameId
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


MIN_IDLE_SHUTDOWN_MINUTES = 5
MAX_IDLE_SHUTDOWN_MINUTES = 60


def _usd(value) -> str:
    return f"${float(value):,.2f}"


def _print_budget(policy: dict) -> None:
    """Monthly budget + the read-only budget block; each part is skipped when the server omits it."""
    if "monthlyBudgetUsd" in policy:
        budget = policy.get("monthlyBudgetUsd")
        click.echo("  monthly budget: " + (_usd(budget) if budget is not None else "none"))
    block = policy.get("budget")
    if not isinstance(block, dict):
        return
    state = block.get("state")
    if state:
        click.echo(f"  budget state: {state}")
        if state == "INACTIVE":
            click.echo(click.style(
                "    stored, enforced once billing is live", fg="yellow"))
        elif state == "REACHED":
            click.echo(click.style(
                "    budget reached: no new servers start and running servers wind down", fg="red"))
        elif state == "WARN":
            click.echo(click.style("    approaching the budget", fg="yellow"))
    if block.get("monthToDateUsd") is not None:
        click.echo(f"  month to date: {_usd(block['monthToDateUsd'])}")
    if block.get("projectedUsd") is not None:
        click.echo(f"  projected this month: {_usd(block['projectedUsd'])}")


def _print_policy(policy: dict) -> None:
    burst = policy.get("maxBurst")
    ceiling = policy.get("platformCeiling")
    click.echo(click.style(policy.get("gameSlug", "?"), fg="cyan", bold=True))
    click.echo(f"  warm servers (always-on): {policy.get('warmServers', 0)}")
    included = policy.get("freeWarmServers")
    if included:
        click.echo(
            f"  included warm servers: {included} "
            "(idle time spends your server minutes; --warm 0 turns it off; "
            "the first match after idle then waits ~10 min for a server to boot)"
        )
    click.echo(
        "  burst ceiling: "
        + (str(burst) if burst is not None else f"platform default ({ceiling})")
    )
    click.echo(f"  platform ceiling: {ceiling}")
    if policy.get("readyServers") is not None:
        click.echo(f"  ready servers (spare while players are online): {policy['readyServers']}")
    if policy.get("idleShutdownMinutes") is not None:
        click.echo(f"  idle shutdown: {policy['idleShutdownMinutes']} min")
    _print_budget(policy)
    if policy.get("entitled"):
        click.echo(click.style("  always-on: available on your plan", fg="green"))
    elif policy.get("freeWarmServers"):
        click.echo(click.style(
            f"  always-on: {policy['freeWarmServers']} included; more than that needs a paid plan",
            fg="yellow"))
    else:
        click.echo(click.style("  always-on: needs a paid plan (warm servers stay 0)", fg="yellow"))


@click.group()
def fcg() -> None:
    """Compute Grid (FCG): game-hosting capacity."""


@fcg.group()
def capacity() -> None:
    """A game's capacity policy: servers, idle shutdown and monthly budget."""


@capacity.command(name="show")
@click.option("--game", default=None, help="Game slug or FRN (else the project's .foundry gameId).")
@click.option("--json", "as_json", is_flag=True, help="Print the raw policy JSON.")
def capacity_show(game, as_json) -> None:
    """Show the game's capacity policy (servers, idle shutdown, monthly budget, plan)."""
    token = auth.access_token(scope=auth.SCOPE_FCG_CAPACITY)
    policy = _fetch_policy(token, _resolve_game(game))
    if as_json:
        click.echo(json.dumps(policy, indent=2))
        return
    _print_policy(policy)


@capacity.command(name="set")
@click.option("--game", default=None, help="Game slug or FRN (else the project's .foundry gameId).")
@click.option("--warm", type=int, default=None,
              help="Warm (always-on) server count; 1 is included per game (0 turns it off),"
                   " more needs a paid plan.")
@click.option("--max-burst", type=int, default=None,
              help="Burst ceiling: max concurrent servers (within the platform ceiling).")
@click.option("--clear-max-burst", is_flag=True, default=False,
              help="Drop the burst ceiling back to the platform default.")
@click.option("--ready-servers", type=int, default=None,
              help="Spare servers kept free while players are online (0 or more, within the"
                   " platform ceiling).")
@click.option("--idle-shutdown", "idle_shutdown", type=int, default=None, metavar="MINUTES",
              help="Minutes an empty server stays up before it shuts down (5 to 60).")
@click.option("--budget", type=float, default=None, metavar="USD",
              help="Monthly budget in USD for this game's servers.")
@click.option("--no-budget", is_flag=True, default=False,
              help="Remove the monthly budget.")
def capacity_set(game, warm, max_burst, clear_max_burst, ready_servers, idle_shutdown,
                 budget, no_budget) -> None:
    """Change the policy (only the flags you pass change)."""
    if max_burst is not None and clear_max_burst:
        raise FoundryError("--max-burst and --clear-max-burst are mutually exclusive.")
    if budget is not None and no_budget:
        raise FoundryError("--budget and --no-budget are mutually exclusive.")
    if ready_servers is not None and ready_servers < 0:
        raise FoundryError("--ready-servers must be 0 or more.")
    if idle_shutdown is not None and not (
            MIN_IDLE_SHUTDOWN_MINUTES <= idle_shutdown <= MAX_IDLE_SHUTDOWN_MINUTES):
        raise FoundryError(
            f"--idle-shutdown must be between {MIN_IDLE_SHUTDOWN_MINUTES} and "
            f"{MAX_IDLE_SHUTDOWN_MINUTES} minutes (got {idle_shutdown})."
        )
    if budget is not None and budget <= 0:
        raise FoundryError("--budget must be more than 0 USD (use --no-budget to remove it).")
    if (warm is None and max_burst is None and not clear_max_burst and ready_servers is None
            and idle_shutdown is None and budget is None and not no_budget):
        raise FoundryError(
            "Nothing to change. Pass --warm, --max-burst, --clear-max-burst, --ready-servers, "
            "--idle-shutdown, --budget, or --no-budget."
        )
    token = auth.access_token(scope=auth.SCOPE_FCG_CAPACITY)
    key = _resolve_game(game)
    # warmServers + maxBurst keep their read-modify-write seed from the CURRENT policy (an older
    # fid expects both). The newer settings are sent only when given: absent = unchanged.
    current = _fetch_policy(token, key)
    body = {
        "warmServers": warm if warm is not None else current.get("warmServers", 0),
        "maxBurst": None if clear_max_burst
        else (max_burst if max_burst is not None else current.get("maxBurst")),
    }
    if ready_servers is not None:
        body["readyServers"] = ready_servers
    if idle_shutdown is not None:
        body["idleShutdownMinutes"] = idle_shutdown
    if no_budget:
        body["monthlyBudgetUsd"] = None
    elif budget is not None:
        body["monthlyBudgetUsd"] = round(budget, 2)
    policy = fid.api_request(
        f"/v1/fcg/capacity-policy?game={quote(key, safe='')}",
        method="PUT",
        token=token,
        body=body,
    ) or {}
    click.echo(click.style("✓ Capacity policy updated.", fg="green", bold=True))
    _print_policy(policy)


def _size_text(size) -> str:
    """'Medium (2 vCPU, 4096 MB)'-style text for a footprint size; tolerant of missing parts."""
    if not isinstance(size, dict):
        return "unknown"
    parts = []
    if size.get("vcpu") is not None:
        parts.append(f"{float(size['vcpu']):g} vCPU")
    if size.get("memoryMb"):
        parts.append(f"{size['memoryMb']} MB")
    detail = f" ({', '.join(parts)})" if parts else ""
    return f"{size.get('name') or 'custom size'}{detail}"


_DIRECTION_TEXT = {
    "DOWN": "a smaller size would fit - lower cost",
    "UP": "the server runs near its limit - a larger size is more reliable",
    "NONE": "the current size is right",
}


def _print_footprint(fp: dict) -> None:
    click.echo(click.style(fp.get("game", "?"), fg="cyan", bold=True))
    click.echo(f"  declared size: {_size_text(fp.get('declared'))}")
    if not fp.get("ready"):
        click.echo(click.style(
            f"  measuring: {fp.get('sampleMinutes', 0)} of {fp.get('minSampleMinutes', '?')} "
            "minutes sampled (only time spent hosting matches counts)", fg="yellow"))
        return
    measured = fp.get("measured")
    if isinstance(measured, dict):
        click.echo(
            f"  measured p95 per server: {float(measured.get('p95Vcpu', 0)):.2f} vCPU, "
            f"{measured.get('p95MemoryMb', 0)} MB")
    if fp.get("recommended"):
        click.echo(f"  recommended size: {_size_text(fp['recommended'])}")
    direction = fp.get("direction")
    if direction:
        click.echo(f"  direction: {direction} - {_DIRECTION_TEXT.get(direction, '')}".rstrip(" -"))
    if fp.get("sessionsPerServer") is not None:
        click.echo(f"  sessions per server: {fp['sessionsPerServer']}")


@fcg.command(name="footprint")
@click.option("--game", default=None, help="Game slug or FRN (else the project's .foundry gameId).")
@click.option("--json", "as_json", is_flag=True, help="Print the raw footprint JSON.")
def footprint(game, as_json) -> None:
    """What your game's servers use (p95 CPU / memory) and the server size that would fit."""
    token = auth.access_token(scope=auth.SCOPE_FCG_CAPACITY)
    key = _resolve_game(game)
    fp = fid.api_request(f"/v1/fcg/footprint?game={quote(key, safe='')}", token=token) or {}
    if as_json:
        click.echo(json.dumps(fp, indent=2))
        return
    _print_footprint(fp)
