"""Publisher-flow CLI papercuts found on the ST-2 stranger-dev walk (2026-09-13).

Locks three behaviours a real publisher hit in order:

* **ST-75** ``keys generate`` checks the SESSION before minting a key, so a signed-out run cannot
  leave an unregistered local key that then forces ``--force`` (and a second key).
* **ST-71** ``--managed`` refuses up front when Foundry holds no MANAGED signing key for the
  publisher, instead of uploading the whole build and dying at ``/complete`` with
  "Publish artifact missing from storage"; a read failure fails OPEN.
* **ST-69** ``games create`` posts the registration the console used to own, and prints the
  server-DERIVED slug (everything downstream is keyed on the slug, not the title).
"""
from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from foundry_cli.commands import build_cmd, games_cmd, keys_cmd
from foundry_cli.core import auth, fid, minisign
from foundry_cli.core.errors import FoundryError


# --------------------------------------------------------------------- ST-75

def test_keys_generate_checks_the_session_before_minting(monkeypatch, tmp_path):
    """Signed out: no keypair is written, so the next attempt needs no --force."""
    key_file = tmp_path / "signing.json"
    minted: list[str] = []

    monkeypatch.setattr(minisign, "load", lambda: None)
    monkeypatch.setattr(minisign, "key_path", lambda: key_file)
    monkeypatch.setattr(minisign, "generate", lambda: minted.append("minted") or {"keyId": "AAA"})
    monkeypatch.setattr(minisign, "save", lambda rec: key_file.write_text("{}"))
    monkeypatch.setattr(auth, "access_token",
                        lambda *a, **k: (_ for _ in ()).throw(FoundryError("Not signed in. Run `foundry login` first.")))

    result = CliRunner().invoke(keys_cmd.generate, [])

    assert result.exit_code != 0
    assert "Not signed in" in str(result.output) + str(result.exception)
    assert minted == []          # nothing minted
    assert not key_file.exists()  # and nothing written


def test_keys_generate_offline_still_works_without_a_session(monkeypatch, tmp_path):
    """--no-register is the offline path: it never needs a session."""
    key_file = tmp_path / "signing.json"
    monkeypatch.setattr(minisign, "load", lambda: None)
    monkeypatch.setattr(minisign, "key_path", lambda: key_file)
    monkeypatch.setattr(minisign, "generate", lambda: {"keyId": "BBB"})
    monkeypatch.setattr(minisign, "save", lambda rec: None)
    monkeypatch.setattr(auth, "access_token",
                        lambda *a, **k: pytest.fail("--no-register must not touch the session"))

    result = CliRunner().invoke(keys_cmd.generate, ["--no-register"])

    assert result.exit_code == 0
    assert "BBB" in result.output


def test_keys_generate_existing_key_points_at_register_not_force(monkeypatch, tmp_path):
    """The guard must offer `keys register` — reaching for --force is what minted a second key."""
    monkeypatch.setattr(minisign, "load", lambda: {"keyId": "CCC"})
    monkeypatch.setattr(minisign, "key_path", lambda: tmp_path / "signing.json")

    result = CliRunner().invoke(keys_cmd.generate, [])

    assert result.exit_code != 0
    assert "foundry keys register" in result.output
    assert "do NOT need --force" in result.output


def test_register_reuses_a_token_and_drops_the_operator_step_note(monkeypatch):
    """fid re-signs the publisher directory itself; the old note claimed an operator did."""
    monkeypatch.setattr(auth, "access_token", lambda *a, **k: pytest.fail("token must be reused"))
    monkeypatch.setattr(minisign, "public_key_blob", lambda rec: "PUBKEY")
    monkeypatch.setattr(fid, "api_request", lambda *a, **k: {"keyId": "DDD"})

    runner = CliRunner()
    with runner.isolation() as (out, _err, _):
        keys_cmd._register({"keyId": "DDD"}, "tok-1")
        text = out.getvalue().decode()  # read INSIDE the context - the buffer closes on exit

    assert "operator step" not in text
    assert "~5 minutes" in text


# --------------------------------------------------------------------- ST-71

def _keys(*rows):
    return lambda path, token=None, **kw: list(rows)


def test_managed_publish_refuses_a_byo_publisher(monkeypatch):
    monkeypatch.setattr(fid, "api_request",
                        _keys({"keyId": "BYO1", "status": "active", "signerType": "BYO"}))

    with pytest.raises(click.ClickException) as exc:
        build_cmd._require_managed_signing("tok-1")

    assert "Managed signing is not enabled" in str(exc.value)
    assert "BYO1" in str(exc.value)  # names the key so the fix is obvious


def test_managed_publish_refuses_a_publisher_with_no_keys(monkeypatch):
    monkeypatch.setattr(fid, "api_request", _keys())

    with pytest.raises(click.ClickException) as exc:
        build_cmd._require_managed_signing("tok-1")

    assert "foundry keys generate" in str(exc.value)


def test_managed_publish_passes_for_a_managed_publisher(monkeypatch):
    monkeypatch.setattr(fid, "api_request",
                        _keys({"keyId": "OLD", "status": "retired", "signerType": "MANAGED"},
                              {"keyId": "KMS1", "status": "active", "signerType": "MANAGED"}))

    build_cmd._require_managed_signing("tok-1")  # no raise


def test_managed_precheck_fails_open_on_a_read_error(monkeypatch):
    """A network blip must not block a legitimate managed publish."""
    def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(fid, "api_request", boom)

    build_cmd._require_managed_signing("tok-1")  # no raise


# --------------------------------------------------------------------- ST-69

def test_games_create_posts_the_name_and_prints_the_derived_slug(monkeypatch):
    calls: list[tuple] = []

    def api(path, method="GET", token=None, body=None, **kw):
        calls.append((path, method, body))
        return {"slug": "my-cool-game", "title": "My Cool Game", "engine": "UNITY",
                "frn": "frn:fgs:482910573312:game/my-cool-game"}

    monkeypatch.setattr(auth, "access_token", lambda *a, **k: "tok-1")
    monkeypatch.setattr(fid, "api_request", api)

    result = CliRunner().invoke(games_cmd.games_create, ["--name", "My Cool Game", "--engine", "unity"])

    assert result.exit_code == 0, result.output
    assert calls == [("/v1/fcm/games", "POST", {"name": "My Cool Game", "engine": "UNITY"})]
    assert "my-cool-game" in result.output          # the slug everything downstream keys on
    assert "frn:fgs:482910573312:game/my-cool-game" in result.output


def test_games_create_omits_engine_when_unset(monkeypatch):
    """fid defaults the engine; sending an empty one would be a lie about the caller's intent."""
    seen: dict = {}

    def api(path, method="GET", token=None, body=None, **kw):
        seen.update(body or {})
        return {"slug": "s", "title": "t"}

    monkeypatch.setattr(auth, "access_token", lambda *a, **k: "tok-1")
    monkeypatch.setattr(fid, "api_request", api)

    result = CliRunner().invoke(games_cmd.games_create, ["--name", "Solo"])

    assert result.exit_code == 0, result.output
    assert seen == {"name": "Solo"}


def test_games_commands_are_key_capable(monkeypatch):
    """A CI publisher runs on API keys - both commands must pass the publish scope."""
    scopes: list = []
    monkeypatch.setattr(auth, "access_token", lambda scope=None: scopes.append(scope) or "tok-1")
    monkeypatch.setattr(fid, "api_request", lambda *a, **k: [])

    CliRunner().invoke(games_cmd.games_list, [])
    CliRunner().invoke(games_cmd.games_create, ["--name", "X"])

    assert scopes == [auth.SCOPE_PUBLISH, auth.SCOPE_PUBLISH]
