"""`foundry fcg capacity` + `foundry fcg footprint`: the per-game autoscaling settings and budget.

Locks: the flag -> PUT body mapping (the newer settings are sent only when given, absent =
unchanged), --budget / --no-budget exclusivity, the client-side range checks, `show` tolerating an
older fid that returns none of the new fields, and the footprint rendering for ready / not ready.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from foundry_cli.commands import fcg
from foundry_cli.core import auth
from foundry_cli.core.errors import FoundryError

CURRENT = {"gameSlug": "goo-crew", "warmServers": 1, "maxBurst": 4, "platformCeiling": 10}


class FakeApi:
    """Stand-in for `fid.api_request`: records calls, answers GET with `current`, PUT with the merge."""

    def __init__(self, current=None, footprint=None):
        self.current = dict(CURRENT if current is None else current)
        self.footprint = footprint
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, path, *, method="GET", token=None, body=None):
        self.calls.append((method, path, body))
        if path.startswith("/v1/fcg/footprint"):
            return self.footprint
        if method == "PUT":
            return {**self.current, **(body or {})}
        return self.current

    @property
    def puts(self):
        return [c for c in self.calls if c[0] == "PUT"]


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(fcg.fid, "api_request", fake)
    monkeypatch.setattr(fcg.auth, "access_token", lambda scope=None: "tok")
    monkeypatch.setattr(fcg, "project_game_id", lambda: "")
    return fake


def run(cmd, *args):
    return CliRunner().invoke(cmd, list(args))


# ------------------------------------------------------------------ capacity set: body mapping

def test_set_sends_only_the_new_fields_that_were_given(api):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--ready-servers", "2")
    assert result.exit_code == 0, result.output
    body = api.puts[0][2]
    assert body["readyServers"] == 2
    assert "idleShutdownMinutes" not in body
    assert "monthlyBudgetUsd" not in body
    # The long-standing read-modify-write seed is unchanged.
    assert body["warmServers"] == 1 and body["maxBurst"] == 4


def test_set_idle_shutdown_and_budget_map_to_the_contract_names(api):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--idle-shutdown", "20", "--budget", "150.5")
    assert result.exit_code == 0, result.output
    body = api.puts[0][2]
    assert body["idleShutdownMinutes"] == 20
    assert body["monthlyBudgetUsd"] == 150.5
    assert "readyServers" not in body


def test_set_no_budget_sends_an_explicit_null(api):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--no-budget")
    assert result.exit_code == 0, result.output
    body = api.puts[0][2]
    assert "monthlyBudgetUsd" in body and body["monthlyBudgetUsd"] is None


def test_set_ready_servers_zero_is_sent(api):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--ready-servers", "0")
    assert result.exit_code == 0, result.output
    assert api.puts[0][2]["readyServers"] == 0


def test_set_with_no_flags_says_what_to_pass(api):
    result = run(fcg.capacity_set, "--game", "goo-crew")
    assert isinstance(result.exception, FoundryError)
    assert "--budget" in str(result.exception)
    assert api.calls == []


# ------------------------------------------------------------------ capacity set: validation

def test_budget_and_no_budget_are_mutually_exclusive(api):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--budget", "100", "--no-budget")
    assert isinstance(result.exception, FoundryError)
    assert "mutually exclusive" in str(result.exception)
    assert api.calls == []


@pytest.mark.parametrize("minutes", ["4", "61", "0", "-1"])
def test_idle_shutdown_outside_5_to_60_is_refused_before_any_call(api, minutes):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--idle-shutdown", minutes)
    assert isinstance(result.exception, FoundryError)
    assert "between 5 and 60" in str(result.exception)
    assert api.calls == []


@pytest.mark.parametrize("minutes", ["5", "60"])
def test_idle_shutdown_bounds_are_inclusive(api, minutes):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--idle-shutdown", minutes)
    assert result.exit_code == 0, result.output
    assert api.puts[0][2]["idleShutdownMinutes"] == int(minutes)


def test_negative_ready_servers_is_refused(api):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--ready-servers", "-1")
    assert isinstance(result.exception, FoundryError)
    assert api.calls == []


def test_non_positive_budget_points_at_no_budget(api):
    result = run(fcg.capacity_set, "--game", "goo-crew", "--budget", "0")
    assert isinstance(result.exception, FoundryError)
    assert "--no-budget" in str(result.exception)


# ------------------------------------------------------------------ capacity show

def test_show_tolerates_an_older_fid_with_none_of_the_new_fields(api):
    result = run(fcg.capacity_show, "--game", "goo-crew")
    assert result.exit_code == 0, result.output
    for word in ("ready servers", "idle shutdown", "monthly budget", "budget state", "month to date"):
        assert word not in result.output
    assert "warm servers" in result.output


def test_show_prints_the_new_fields_and_the_budget_block(api):
    api.current.update({
        "readyServers": 1,
        "idleShutdownMinutes": 10,
        "monthlyBudgetUsd": 200,
        "budget": {"state": "OK", "monthToDateUsd": 42.5, "projectedUsd": 120},
    })
    out = run(fcg.capacity_show, "--game", "goo-crew").output
    assert "ready servers (spare while players are online): 1" in out
    assert "idle shutdown: 10 min" in out
    assert "monthly budget: $200.00" in out
    assert "budget state: OK" in out
    assert "month to date: $42.50" in out
    assert "projected this month: $120.00" in out


def test_show_inactive_budget_says_it_is_not_enforced_yet(api):
    api.current.update({"monthlyBudgetUsd": 50, "budget": {"state": "INACTIVE"}})
    out = run(fcg.capacity_show, "--game", "goo-crew").output
    assert "enforced once billing is live" in out
    assert "month to date" not in out  # null / absent figures are skipped


def test_show_prints_none_when_the_budget_is_explicitly_null(api):
    api.current.update({"monthlyBudgetUsd": None, "budget": {"state": "NONE"}})
    out = run(fcg.capacity_show, "--game", "goo-crew").output
    assert "monthly budget: none" in out


# ------------------------------------------------------------------ footprint

READY = {
    "game": "goo-crew", "ready": True, "sampleMinutes": 240, "minSampleMinutes": 60,
    "declared": {"name": "Large", "vcpu": 2, "memoryMb": 4096},
    "measured": {"p95Vcpu": 0.4, "p95MemoryMb": 900, "maxVcpu": 0.7, "maxMemoryMb": 1100},
    "recommended": {"name": "Small", "vcpu": 1, "memoryMb": 2048},
    "direction": "DOWN", "sessionsPerServer": 2,
}


def test_footprint_ready_shows_declared_measured_recommended_and_packing(api):
    api.footprint = READY
    result = run(fcg.footprint, "--game", "goo-crew")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "declared size: Large (2 vCPU, 4096 MB)" in out
    assert "measured p95 per server: 0.40 vCPU, 900 MB" in out
    assert "recommended size: Small (1 vCPU, 2048 MB)" in out
    assert "direction: DOWN - a smaller size would fit" in out
    assert "sessions per server: 2" in out
    assert api.calls[0][1] == "/v1/fcg/footprint?game=goo-crew"


def test_footprint_not_ready_shows_how_far_measuring_has_got(api):
    api.footprint = {
        "game": "goo-crew", "ready": False, "sampleMinutes": 12, "minSampleMinutes": 60,
        "declared": {"name": "Large", "vcpu": 2, "memoryMb": 4096}, "direction": "NONE",
    }
    out = run(fcg.footprint, "--game", "goo-crew").output
    assert "measuring: 12 of 60 minutes sampled" in out
    assert "declared size: Large" in out
    assert "recommended" not in out and "measured p95" not in out


def test_footprint_without_a_game_asks_for_one(api):
    result = run(fcg.footprint)
    assert isinstance(result.exception, FoundryError)
    assert "--game" in str(result.exception)


def test_footprint_uses_the_project_game_when_no_flag(api, monkeypatch):
    monkeypatch.setattr(fcg, "project_game_id", lambda: "goo-crew")
    api.footprint = READY
    assert run(fcg.footprint).exit_code == 0
    assert api.calls[0][1] == "/v1/fcg/footprint?game=goo-crew"


def test_footprint_json_prints_the_raw_response(api):
    api.footprint = READY
    out = run(fcg.footprint, "--game", "goo-crew", "--json").output
    assert '"sessionsPerServer": 2' in out


def test_footprint_asks_for_the_capacity_scope(monkeypatch):
    scopes = []
    monkeypatch.setattr(fcg.auth, "access_token", lambda scope=None: scopes.append(scope) or "tok")
    monkeypatch.setattr(fcg.fid, "api_request", FakeApi(footprint=READY))
    run(fcg.footprint, "--game", "goo-crew")
    assert scopes == [auth.SCOPE_FCG_CAPACITY]
