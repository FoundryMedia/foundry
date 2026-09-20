"""API-key (OAuth2 client-credentials) auth mode for CI — `core/auth.py`.

Locks: the token-endpoint body, per-scope in-process caching with the 10 s re-mint margin,
env-over-session precedence, the half-set error naming the missing var, the key-incapable
message, the interactive path staying byte-identical, the `invalid_client` rewrite, the
login/logout no-op, and the scope each command passes (the contract table).
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from foundry_cli.commands import auth_cmd, build_cmd, fcg, fmms, keys_cmd
from foundry_cli.core import auth, fid
from foundry_cli.core.errors import FoundryError

KEY_ID = "fk_test_key"
KEY_SECRET = "sk_test_secret"
TOKEN_RESPONSE = {"access_token": "tok-1", "token_type": "Bearer", "expires_in": 60, "scope": "publish"}


class Recorder:
    """Stand-in for `fid.auth_post`: records (path, body, token), replays canned responses."""

    def __init__(self, *responses):
        self.calls: list[tuple[str, dict, str | None]] = []
        self._responses = list(responses)

    def __call__(self, path, body, token=None):
        self.calls.append((path, body, token))
        resp = self._responses.pop(0) if self._responses else dict(TOKEN_RESPONSE)
        if isinstance(resp, Exception):
            raise resp
        return resp

    @property
    def paths(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Clean env, empty token cache, credentials file under tmp, frozen injectable clock."""
    monkeypatch.delenv(auth.KEY_ID_ENV, raising=False)
    monkeypatch.delenv(auth.KEY_SECRET_ENV, raising=False)
    monkeypatch.setattr(auth, "_token_cache", {})
    monkeypatch.setattr(auth, "_CREDS", tmp_path / "credentials.json")
    clock = {"t": 1000.0}
    monkeypatch.setattr(auth, "_now", lambda: clock["t"])
    yield clock


@pytest.fixture
def key_env(monkeypatch):
    monkeypatch.setenv(auth.KEY_ID_ENV, KEY_ID)
    monkeypatch.setenv(auth.KEY_SECRET_ENV, KEY_SECRET)


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(fid, "auth_post", rec)
    return rec


# ---------------------------------------------------------------------------
# key mode: mint + cache
# ---------------------------------------------------------------------------


def test_api_key_mode_requires_both_vars_non_blank(monkeypatch):
    assert auth.api_key_mode() is False
    monkeypatch.setenv(auth.KEY_ID_ENV, KEY_ID)
    assert auth.api_key_mode() is False
    monkeypatch.setenv(auth.KEY_SECRET_ENV, "   ")
    assert auth.api_key_mode() is False
    monkeypatch.setenv(auth.KEY_SECRET_ENV, KEY_SECRET)
    assert auth.api_key_mode() is True


def test_mint_sends_client_credentials_body_and_returns_token(key_env, recorder):
    assert auth.access_token(scope="publish") == "tok-1"
    assert recorder.calls == [
        (
            "/oauth/token",
            {
                "grant_type": "client_credentials",
                "client_id": KEY_ID,
                "client_secret": KEY_SECRET,
                "scope": "publish",
            },
            None,
        )
    ]


def test_second_call_same_scope_within_ttl_uses_cache(key_env, recorder, _isolated):
    auth.access_token(scope="publish")
    _isolated["t"] += 30
    assert auth.access_token(scope="publish") == "tok-1"
    assert recorder.paths == ["/oauth/token"]


def test_different_scope_mints_separately(key_env, monkeypatch):
    rec = Recorder(
        {"access_token": "tok-publish", "expires_in": 60},
        {"access_token": "tok-queues", "expires_in": 60},
    )
    monkeypatch.setattr(fid, "auth_post", rec)
    assert auth.access_token(scope="publish") == "tok-publish"
    assert auth.access_token(scope="fmms:queues") == "tok-queues"
    assert auth.access_token(scope="publish") == "tok-publish"  # still cached
    assert [c[1]["scope"] for c in rec.calls] == ["publish", "fmms:queues"]


def test_remints_when_under_ten_seconds_remain(key_env, monkeypatch, _isolated):
    rec = Recorder(
        {"access_token": "tok-1", "expires_in": 60},
        {"access_token": "tok-2", "expires_in": 60},
    )
    monkeypatch.setattr(fid, "auth_post", rec)
    auth.access_token(scope="publish")
    _isolated["t"] += 49  # 11 s left -> cached
    assert auth.access_token(scope="publish") == "tok-1"
    _isolated["t"] += 2  # 9 s left -> re-mint
    assert auth.access_token(scope="publish") == "tok-2"
    assert len(rec.calls) == 2


def test_env_wins_over_stored_session(key_env, recorder, tmp_path):
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"refreshToken": "stored-rt"}), encoding="utf-8")
    assert auth.access_token(scope="publish") == "tok-1"
    assert recorder.paths == ["/oauth/token"]  # no /desktop/refresh
    assert json.loads(creds.read_text(encoding="utf-8")) == {"refreshToken": "stored-rt"}  # untouched


@pytest.mark.parametrize(
    "present, missing",
    [(auth.KEY_ID_ENV, auth.KEY_SECRET_ENV), (auth.KEY_SECRET_ENV, auth.KEY_ID_ENV)],
)
def test_half_set_key_names_the_missing_var(monkeypatch, recorder, present, missing):
    monkeypatch.setenv(present, "value")
    with pytest.raises(FoundryError) as exc:
        auth.access_token(scope="publish")
    assert missing in str(exc.value)
    assert f"{present} is set" in str(exc.value)
    assert recorder.calls == []  # never fell through to /desktop/refresh


def test_scope_none_in_key_mode_needs_interactive_login(key_env, recorder):
    with pytest.raises(FoundryError) as exc:
        auth.access_token()
    assert "interactive login" in str(exc.value)
    assert "foundry login" in str(exc.value)
    assert recorder.calls == []


def test_invalid_client_maps_to_clear_message(key_env, monkeypatch):
    rec = Recorder(FoundryError("invalid_client"))
    monkeypatch.setattr(fid, "auth_post", rec)
    with pytest.raises(FoundryError) as exc:
        auth.access_token(scope="fcg:capacity")
    msg = str(exc.value)
    assert "API key rejected for scope 'fcg:capacity'" in msg
    assert auth.KEY_ID_ENV in msg and auth.KEY_SECRET_ENV in msg
    assert "holds that scope" in msg


def test_other_errors_pass_through(key_env, monkeypatch):
    rec = Recorder(FoundryError("Cannot reach https://auth.example: boom"))
    monkeypatch.setattr(fid, "auth_post", rec)
    with pytest.raises(FoundryError, match="Cannot reach"):
        auth.access_token(scope="publish")


def test_missing_access_token_in_response_is_an_error(key_env, monkeypatch):
    rec = Recorder({"token_type": "Bearer"})
    monkeypatch.setattr(fid, "auth_post", rec)
    with pytest.raises(FoundryError, match="access_token"):
        auth.access_token(scope="publish")


# ---------------------------------------------------------------------------
# interactive mode unchanged
# ---------------------------------------------------------------------------


def test_interactive_mode_ignores_scope_and_refreshes(monkeypatch, tmp_path):
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"refreshToken": "rt-1"}), encoding="utf-8")
    rec = Recorder({"accessToken": "sess-tok", "refreshToken": "rt-2"})
    monkeypatch.setattr(fid, "auth_post", rec)
    assert auth.access_token("publish") == "sess-tok"
    assert rec.calls == [("/desktop/refresh", {"refreshToken": "rt-1"}, None)]
    # rotated refresh token persisted, exactly as before
    assert json.loads(creds.read_text(encoding="utf-8")) == {"refreshToken": "rt-2"}


def test_interactive_mode_not_signed_in(recorder):
    with pytest.raises(FoundryError, match="foundry login"):
        auth.access_token()
    assert recorder.calls == []


# ---------------------------------------------------------------------------
# login / logout in key mode
# ---------------------------------------------------------------------------


def test_core_login_logout_noop_in_key_mode(key_env, recorder, tmp_path):
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"refreshToken": "stored-rt"}), encoding="utf-8")
    assert auth.login("me@example.com", "pw") == {}
    auth.logout()
    assert recorder.calls == []
    assert creds.exists()  # logout did not delete the stored session either


def test_login_command_warns_and_skips_in_key_mode(key_env, recorder):
    result = CliRunner().invoke(auth_cmd.login, [])  # no prompts must fire
    assert result.exit_code == 0, result.output
    assert auth.key_mode_notice("login") in result.output
    assert "Signed in" not in result.output
    assert recorder.calls == []


def test_logout_command_warns_and_skips_in_key_mode(key_env, recorder):
    result = CliRunner().invoke(auth_cmd.logout, [])
    assert result.exit_code == 0, result.output
    assert auth.key_mode_notice("logout") in result.output
    assert "Signed out" not in result.output
    assert recorder.calls == []


def test_login_command_prompts_in_interactive_mode(monkeypatch, tmp_path):
    rec = Recorder({"refreshToken": "rt-1", "user": {"email": "me@example.com"}})
    monkeypatch.setattr(fid, "auth_post", rec)
    result = CliRunner().invoke(auth_cmd.login, [], input="me@example.com\npw\n")
    assert result.exit_code == 0, result.output
    assert "Signed in as me@example.com" in result.output
    assert rec.calls[0][0] == "/desktop/login"
    assert rec.calls[0][1]["emailOrUsername"] == "me@example.com"


# ---------------------------------------------------------------------------
# the scope each command passes (the contract table)
# ---------------------------------------------------------------------------


def _scopes_by_function(module) -> dict[str, list[str | None]]:
    """{function name: [scope passed at each auth.access_token(...) call]} from the source."""
    tree = ast.parse(inspect.getsource(module))
    out: dict[str, list[str | None]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "access_token"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "auth"
            ):
                continue
            scope: str | None = None
            for kw in node.keywords:
                if kw.arg == "scope":
                    assert isinstance(kw.value, ast.Attribute) and kw.value.value.id == "auth", (
                        f"{fn.name}: scope must be an auth.SCOPE_* constant"
                    )
                    scope = getattr(auth, kw.value.attr)
            assert not node.args, f"{fn.name}: pass scope by keyword"
            out.setdefault(fn.name, []).append(scope)
    return out


def test_scope_table_build_cmd():
    got = _scopes_by_function(build_cmd)
    assert got == {
        "upload_build": [auth.SCOPE_PUBLISH, auth.SCOPE_PUBLISH],  # create + re-ask before complete
        "fcm_publish": [auth.SCOPE_PUBLISH, auth.SCOPE_PUBLISH],  # prepare + re-ask before complete
        "channel_set": [auth.SCOPE_PUBLISH],
        "channel_unset": [auth.SCOPE_PUBLISH],
    }


def test_scope_table_fmms():
    got = _scopes_by_function(fmms)
    key_capable = {"queues", "queue_list", "queue_show", "queue_create", "queue_update", "queue_delete"}
    for name in key_capable:
        assert got[name] == [auth.SCOPE_FMMS_QUEUES], name
    for name in ("submit", "status", "connect", "cancel", "play", "create_queue", "form_match"):
        assert got[name] == [None], f"{name} must stay key-incapable (bare access_token())"


def test_scope_table_fcg():
    assert _scopes_by_function(fcg) == {
        "capacity_show": [auth.SCOPE_FCG_CAPACITY],
        "capacity_set": [auth.SCOPE_FCG_CAPACITY],
    }


def test_scope_table_keys_stay_interactive():
    # `generate` joined the table in ST-75: it checks the SESSION before minting a keypair, so a
    # signed-out run cannot leave an unregistered local key behind. Bare access_token() (scope
    # None) is deliberate for all three - registering a BYO signing key is interactive-only.
    assert _scopes_by_function(keys_cmd) == {
        "generate": [None],
        "list_keys": [None],
        "_register": [None],
    }


def test_key_incapable_command_fails_with_login_message(key_env, recorder):
    result = CliRunner().invoke(keys_cmd.list_keys, [])
    assert isinstance(result.exception, FoundryError)
    assert str(result.exception) == auth.INTERACTIVE_LOGIN_REQUIRED
    assert recorder.calls == []


def test_scope_constants_match_contract():
    assert auth.SCOPE_PUBLISH == "publish"
    assert auth.SCOPE_FMMS_QUEUES == "fmms:queues"
    assert auth.SCOPE_FCG_CAPACITY == "fcg:capacity"
    assert auth.KEY_ID_ENV == "FOUNDRY_API_KEY_ID"
    assert auth.KEY_SECRET_ENV == "FOUNDRY_API_KEY_SECRET"


def test_version_bumped():
    # Resolve from THIS file, not the installed package: CI runs the suite against a
    # non-editable install, where the package's parents land in site-packages.
    py = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert 'version = "0.18.0"' in py.read_text(encoding="utf-8")
