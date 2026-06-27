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
