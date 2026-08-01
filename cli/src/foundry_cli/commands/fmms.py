"""`foundry fmms` — Foundry Matchmaking Service: queues, tickets, and the connection hand-off.

The player flow (any signed-in user):
  queues               list your matchmaking queues
  submit <queue>       submit a matchmaking ticket
  status <ticket>      poll a ticket's state (--wait blocks until MATCHED/terminal)
  connect <ticket>     fetch the server connection (ip:port + match token) once matched
  cancel <ticket>      cancel a ticket
  play <queue>         the whole loop: submit -> wait for the match -> print the connection

Operator helpers (need fmms:admin; a regular dev gets 403):
  create-queue <name>  create a queue to submit into
  form-match <queue>   form ONE match now from the QUEUED tickets (prod has no auto-sweep)

A match only forms via `form-match` (or the server-side sweep, off in prod), so the end-to-end
demo from a single account is: `create-queue` -> `play <queue> --form`. Run `foundry login` first.
All calls are bearer-authed against fid-native /v1/fmms endpoints (the desktop bearer flow).
"""

from __future__ import annotations

import json
import time

import click

from foundry_cli.core import auth, fid
from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project import project_game_id

# Ticket states (fid TicketState): QUEUED -> MATCHED, or EXPIRED / CANCELED.
_TERMINAL = {"MATCHED", "EXPIRED", "CANCELED"}


def _validate_attributes(raw: str) -> str:
    """Attributes are an opaque JSON string the matcher reads; fail fast if it isn't JSON."""
    try:
        json.loads(raw)
    except ValueError as exc:
        raise FoundryError(f"--attributes must be valid JSON: {exc}") from exc
    return raw


def _poll_status(ticket_id: str, token: str, timeout: int) -> dict:
    """Poll a ticket until it leaves QUEUED (or timeout). Returns the latest ticket row."""
    deadline = time.monotonic() + timeout
    while True:
        row = fid.api_request(f"/v1/fmms/tickets/{ticket_id}", token=token) or {}
        state = row.get("state")
        if state in _TERMINAL:
            return row
        if time.monotonic() >= deadline:
            return row
        click.echo(click.style(f"  {state}…", fg="bright_black"))
        time.sleep(2)


def _wait_connection(ticket_id: str, token: str, timeout: int) -> dict:
    """Fetch the connection, retrying while it 404s (the match may still be allocating)."""
    deadline = time.monotonic() + timeout
    last: FoundryError | None = None
    while True:
        try:
            return fid.api_request(f"/v1/fmms/tickets/{ticket_id}/connection", token=token) or {}
        except FoundryError as exc:
            last = exc
            if time.monotonic() >= deadline:
                raise
            click.echo(click.style("  allocating the server…", fg="bright_black"))
            time.sleep(2)


def _print_connection(conn: dict) -> None:
    ip = conn.get("ip")
    port = conn.get("port")
    token = conn.get("matchToken")
    click.echo(click.style(f"✓ Connect to {ip}:{port}", fg="green", bold=True))
    if token:
        click.echo(click.style("  match token: ", fg="bright_black") + token)


@click.group()
def fmms() -> None:
    """Matchmaking (FMMS)."""


@fmms.command()
def queues() -> None:
    """List your matchmaking queues (and how many players are waiting in each)."""
    token = auth.access_token()
    rows = fid.api_request("/v1/fmms/queues", token=token) or []
    if not rows:
        click.echo("No queues. Create one with `foundry fmms create-queue <name>` (operator).")
        return
    for q in rows:
        waiting = q.get("queuedCount", 0)
        region = q.get("regionPref") or "-"
        click.echo(
            click.style(q.get("id", "?"), fg="cyan")
            + f"  {q.get('name', '?')}  region={region}  waiting={waiting}"
        )


@fmms.command()
@click.argument("queue_id")
@click.option("--attributes", default="{}", show_default=True, help="Opaque JSON match attributes.")
def submit(queue_id, attributes) -> None:
    """Submit a matchmaking ticket into QUEUE_ID."""
    token = auth.access_token()
    row = fid.api_request(
        "/v1/fmms/tickets",
        method="POST",
        token=token,
        body={"queueId": queue_id, "attributes": _validate_attributes(attributes)},
    ) or {}
    click.echo(
        click.style(f"✓ Ticket {row.get('id')}", fg="green", bold=True)
        + click.style(f" (state: {row.get('state')}).", fg="green")
    )


@fmms.command()
@click.argument("ticket_id")
@click.option("--wait", is_flag=True, default=False, help="Block until the ticket is MATCHED or terminal.")
@click.option("--timeout", default=120, show_default=True, help="Max seconds to wait.")
def status(ticket_id, wait, timeout) -> None:
    """Show (or --wait on) a ticket's matchmaking state."""
    token = auth.access_token()
    row = _poll_status(ticket_id, token, timeout) if wait else (fid.api_request(f"/v1/fmms/tickets/{ticket_id}", token=token) or {})
    state = row.get("state")
    color = "green" if state == "MATCHED" else "yellow" if state == "QUEUED" else "red"
    click.echo(click.style(f"Ticket {ticket_id}: {state}", fg=color, bold=True))


@fmms.command()
@click.argument("ticket_id")
@click.option("--wait", is_flag=True, default=False, help="Retry while the server is still allocating.")
@click.option("--timeout", default=60, show_default=True, help="Max seconds to wait for the endpoint.")
def connect(ticket_id, wait, timeout) -> None:
    """Get the server connection (ip:port + match token) for a MATCHED ticket."""
    token = auth.access_token()
    conn = _wait_connection(ticket_id, token, timeout) if wait else (fid.api_request(f"/v1/fmms/tickets/{ticket_id}/connection", token=token) or {})
    _print_connection(conn)


@fmms.command()
@click.argument("ticket_id")
def cancel(ticket_id) -> None:
    """Cancel a matchmaking ticket."""
    token = auth.access_token()
    fid.api_request(f"/v1/fmms/tickets/{ticket_id}", method="DELETE", token=token)
    click.echo(click.style(f"✓ Canceled {ticket_id}.", fg="green", bold=True))


@fmms.command()
@click.argument("queue_id")
@click.option("--attributes", default="{}", show_default=True, help="Opaque JSON match attributes.")
@click.option("--form", is_flag=True, default=False, help="(operator) form the match right after submitting.")
@click.option("--timeout", default=180, show_default=True, help="Max seconds to wait for the match.")
def play(queue_id, attributes, form, timeout) -> None:
    """Drive the whole flow: submit -> wait for the match -> print the connection."""
    token = auth.access_token()
    click.echo(f"Submitting a ticket to {queue_id}…")
    ticket = fid.api_request(
        "/v1/fmms/tickets",
        method="POST",
        token=token,
        body={"queueId": queue_id, "attributes": _validate_attributes(attributes)},
    ) or {}
    ticket_id = ticket.get("id")
    if not ticket_id:
        raise FoundryError("Submit did not return a ticket id.")
    click.echo(click.style(f"  ticket {ticket_id}", fg="cyan"))

    if form:
        click.echo("Forming the match (operator)…")
        fid.api_request(f"/v1/admin/fmms/queues/{queue_id}/form-match", method="POST", token=token)

    click.echo("Waiting for the match…")
    row = _poll_status(ticket_id, token, timeout)
    if row.get("state") != "MATCHED":
        raise FoundryError(
            f"Ticket ended in state {row.get('state')} (no match). "
            "Form a match with `foundry fmms form-match <queue>` or enable the sweep."
        )
    click.echo("Matched — fetching the connection…")
    _print_connection(_wait_connection(ticket_id, token, 60))


@fmms.command(name="create-queue")
@click.argument("name")
@click.option("--region", "region_pref", default=None, help="Region preference hint (e.g. mia).")
@click.option("--rules", default=None, help="Opaque JSON match-formation rules.")
def create_queue(name, region_pref, rules) -> None:
    """(operator) Create a matchmaking queue. Needs fmms:admin."""
    token = auth.access_token()
    body: dict = {"name": name}
    if region_pref:
        body["regionPref"] = region_pref
    if rules:
        body["rules"] = _validate_attributes(rules)
    row = fid.api_request("/v1/admin/fmms/queues", method="POST", token=token, body=body) or {}
    click.echo(click.style(f"✓ Queue {row.get('id')}", fg="green", bold=True) + f"  {row.get('name')}")


@fmms.command(name="form-match")
@click.argument("queue_id")
def form_match(queue_id) -> None:
    """(operator) Form ONE match now from QUEUE_ID's waiting tickets. Needs fmms:admin."""
    token = auth.access_token()
    match = fid.api_request(f"/v1/admin/fmms/queues/{queue_id}/form-match", method="POST", token=token)
    if not match:
        click.echo(click.style("No match formed — not enough waiting tickets (need fmms.match-size).", fg="yellow"))
        return
    click.echo(
        click.style(f"✓ Match {match.get('id')}", fg="green", bold=True)
        + click.style(f" (state: {match.get('state')}).", fg="green")
    )


# ── queue model: customer-scoped create / update / show / list / delete ──
#
# Configure a queue's MODEL (team shape, party cap, region policy, skill/latency rules) as flags
# and/or a --model JSON file — the same document the web console's form + JSON editor edit. These
# hit the cookie/bearer /v1/fmms/queues surface (your OWN games), not the operator create-queue.


def _resolve_game(game_opt: str | None) -> str:
    """The game slug to operate on: an explicit --game, else the project's .foundry gameId."""
    slug = (game_opt or "").strip().lower() or project_game_id()
    if not slug:
        raise FoundryError(
            "No game. Pass --game <slug>, or run inside a game-publisher project (.foundry/config.yml)."
        )
    return slug


def _load_model_file(path: str | None) -> dict:
    """Load a QueueModel JSON document from --model (or {} when absent)."""
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise FoundryError(f"--model: {exc}") from exc
    if not isinstance(data, dict):
        raise FoundryError("--model must be a JSON object (a queue model).")
    return data


def _apply_flags(model: dict, **flags) -> dict:
    """Overlay individual flags onto a model dict (flags win over the --model file)."""
    m = dict(model)
    if flags.get("display_name") is not None:
        m["displayName"] = flags["display_name"]
    if flags.get("mode_slug") is not None:
        m["modeSlug"] = flags["mode_slug"]
    if flags.get("teams") is not None:
        m["teamCount"] = flags["teams"]
    if flags.get("team_size") is not None:
        m["teamSize"] = flags["team_size"]
    if flags.get("max_party") is not None:
        m["maxPartySize"] = flags["max_party"]
    if flags.get("server_build") is not None:
        m["serverBuildId"] = flags["server_build"] or None
    regions = dict(m.get("regions") or {})
    if flags.get("region_mode") is not None:
        regions["mode"] = flags["region_mode"]
    if flags.get("regions"):  # a tuple of repeated --region codes
        regions["allowed"] = list(flags["regions"])
    if flags.get("max_latency") is not None:
        regions["maxLatencyMs"] = flags["max_latency"]
    if regions:
        m["regions"] = regions
    skill = dict(m.get("skill") or {})
    if flags.get("skill_attr") is not None:
        skill["attribute"] = flags["skill_attr"]
    if flags.get("skill_spread") is not None:
        skill["maxSpread"] = flags["skill_spread"]
    if skill:
        m["skill"] = skill
    latency = dict(m.get("latency") or {})
    if flags.get("latency_attr") is not None:
        latency["attribute"] = flags["latency_attr"]
    if flags.get("latency_max") is not None:
        latency["maxMs"] = flags["latency_max"]
    if latency:
        m["latency"] = latency
    fill = dict(m.get("fill") or {})
    if flags.get("min_players") is not None:
        # 0 = clear (back to exact-fill); anything else is the minimum to start a new match.
        fill["minPlayers"] = flags["min_players"] or None
    if flags.get("backfill") is not None:
        fill["backfill"] = flags["backfill"]
    if fill:
        m["fill"] = fill
    return m


def _model_to_request(model: dict, game_slug: str) -> dict:
    """Decompose a queue model into the fid request (rules carries skill/latency/expansions/regions)."""
    rules = {
        "skill": model.get("skill") or {"attribute": "skill"},
        "latency": model.get("latency") or {"attribute": "latencyMs"},
        "expansions": model.get("expansions") or [],
        "regions": model.get("regions") or {"mode": "any", "allowed": [], "maxLatencyMs": None},
        "fill": model.get("fill") or {"minPlayers": None, "backfill": False},
    }
    return {
        "gameSlug": game_slug,
        "displayName": str(model.get("displayName") or "").strip(),
        "modeSlug": model.get("modeSlug"),
        "teamCount": model.get("teamCount") or 1,
        "teamSize": model.get("teamSize") or 1,
        "maxPartySize": model.get("maxPartySize"),
        "serverBuildId": model.get("serverBuildId"),
        "regionPref": None,
        "rules": json.dumps(rules),
    }


def _find_queue(token: str, key: str, game: str | None = None) -> dict:
    """Resolve one of the caller's queues by id, name ('game/mode'), FRN, or submitKey."""
    rows = fid.api_request("/v1/fmms/queues", token=token) or []
    if game:
        rows = [q for q in rows if q.get("gameSlug") == game]
    key_l = key.strip().lower()
    for q in rows:
        if key in (q.get("id"), q.get("frn"), q.get("submitKey")) or (q.get("name") or "").lower() == key_l:
            return q
    raise FoundryError(f"Queue not found: {key}")


_MODE_CHOICE = click.Choice(["any", "allowlist", "player-selected"], case_sensitive=False)


def _model_flags(command):
    """Attach the shared queue-model flags to a create/update command."""
    options = [
        click.option("--display-name", default=None, help="Human display name (e.g. '5v5 Conquest')."),
        click.option("--min-players", type=int, default=None,
                     help="Minimum total players to START a new match (team shape is the max; 0 = full-fill)."),
        click.option("--backfill/--no-backfill", default=None,
                     help="Join-in-progress: seat searchers into an open, live, not-full match."),
        click.option("--mode-slug", default=None, help="Explicit mode id (create only; derived otherwise)."),
        click.option("--teams", type=int, default=None, help="Team count."),
        click.option("--team-size", type=int, default=None, help="Players per team."),
        click.option("--max-party", type=int, default=None, help="Max party size (<= team size)."),
        click.option("--region", "regions", multiple=True, help="Allowed region CODE (repeatable)."),
        click.option("--region-mode", type=_MODE_CHOICE, default=None,
                     help="any | allowlist | player-selected."),
        click.option("--max-latency", type=float, default=None, help="Region latency gate (ms)."),
        click.option("--skill-attr", default=None, help="Ticket attribute carrying skill."),
        click.option("--skill-spread", type=float, default=None, help="Max skill spread within a match."),
        click.option("--latency-attr", default=None, help="Ticket attribute carrying latency."),
        click.option("--latency-max", type=float, default=None, help="Max latency within a match (ms)."),
        click.option("--server-build", default=None, help="FCM SERVER build id the match runs."),
        click.option("--model", "model_file", type=click.Path(exists=True, dir_okay=False),
                     default=None, help="A queue model JSON file (flags override it)."),
        click.option("--game", default=None, help="Game slug (else the project's .foundry gameId)."),
    ]
    for option in reversed(options):
        command = option(command)
    return command


@fmms.group()
def queue() -> None:
    """Configure matchmaking queues (the queue model): create, update, show, list, delete."""


@queue.command(name="list")
@click.option("--game", default=None, help="Filter to a game slug (else the project's .foundry gameId).")
def queue_list(game) -> None:
    """List the project game's queues (or --game; all your queues if neither resolves)."""
    token = auth.access_token()
    slug = (game or "").strip().lower() or project_game_id()
    rows = fid.api_request("/v1/fmms/queues", token=token) or []
    if slug:
        rows = [q for q in rows if q.get("gameSlug") == slug]
    if not rows:
        click.echo("No queues." + (f" (game {slug})" if slug else ""))
        return
    for q in rows:
        regions = (q.get("model") or {}).get("regions") or {}
        click.echo(
            click.style(q.get("name", "?"), fg="cyan")
            + f"  region={regions.get('mode', 'any')}  waiting={q.get('queuedCount', 0)}  {q.get('id')}"
        )


@queue.command(name="show")
@click.argument("key")
@click.option("--game", default=None, help="Game slug (else the project's .foundry gameId).")
@click.option("--json", "as_json", is_flag=True, help="Print the raw queue model JSON.")
def queue_show(key, game, as_json) -> None:
    """Show a queue's model (KEY = name 'game/mode', id, or FRN)."""
    token = auth.access_token()
    q = _find_queue(token, key, game=game)
    model = q.get("model") or {}
    if as_json:
        click.echo(json.dumps(model, indent=2))
        return
    click.echo(click.style(q.get("name", "?"), fg="cyan", bold=True) + f"  {q.get('frn') or ''}")
    click.echo(f"  teams: {model.get('teamCount')} x {model.get('teamSize')}  maxParty: {model.get('maxPartySize')}")
    regions = model.get("regions") or {}
    allowed = ", ".join(regions.get("allowed") or []) or "-"
    click.echo(
        f"  regions: {regions.get('mode', 'any')}  allowed: {allowed}  gate: {regions.get('maxLatencyMs')}"
    )
    fill = model.get("fill") or {}
    click.echo(
        f"  fill: min {fill.get('minPlayers') or 'full'}  backfill: {'on' if fill.get('backfill') else 'off'}"
    )
    click.echo(f"  waiting: {q.get('queuedCount', 0)}")


@queue.command(name="create")
@_model_flags
def queue_create(**flags) -> None:
    """Create a queue from flags and/or a --model file."""
    token = auth.access_token()
    game = _resolve_game(flags.get("game"))
    model = _apply_flags(_load_model_file(flags.get("model_file")), **flags)
    if not str(model.get("displayName") or "").strip():
        raise FoundryError("--display-name is required (or set displayName in --model).")
    body = _model_to_request(model, game)
    row = fid.api_request("/v1/fmms/queues", method="POST", token=token, body=body) or {}
    click.echo(
        click.style(f"✓ Queue {row.get('id')}", fg="green", bold=True)
        + f"  {row.get('name')}  ({row.get('frn')})"
    )


@queue.command(name="update")
@click.argument("key")
@_model_flags
def queue_update(key, **flags) -> None:
    """Update a queue's model (KEY = name 'game/mode', id, or FRN). Identity is immutable."""
    token = auth.access_token()
    q = _find_queue(token, key, game=flags.get("game"))
    # Seed from the queue's CURRENT model, then overlay a --model file, then the individual flags.
    base = q.get("model") or {}
    if flags.get("model_file"):
        base = {**base, **_load_model_file(flags["model_file"])}
    model = _apply_flags(base, **flags)
    body = _model_to_request(model, q.get("gameSlug") or "")
    row = fid.api_request(f"/v1/fmms/queues/{q['id']}", method="PUT", token=token, body=body) or {}
    click.echo(click.style(f"✓ Updated {row.get('name')}", fg="green", bold=True))


@queue.command(name="delete")
@click.argument("key")
@click.option("--game", default=None, help="Game slug (else the project's .foundry gameId).")
def queue_delete(key, game) -> None:
    """Delete a queue (KEY = name 'game/mode', id, or FRN). Idempotent."""
    token = auth.access_token()
    q = _find_queue(token, key, game=game)
    fid.api_request(f"/v1/fmms/queues/{q['id']}", method="DELETE", token=token)
    click.echo(click.style(f"✓ Deleted {q.get('name')}", fg="green", bold=True))
