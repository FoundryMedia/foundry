"""Foundry platform credentials for the CLI — API-key mode (CI) or an interactive session.

:func:`access_token` resolves the mode per call:

**API-key mode** — when BOTH ``FOUNDRY_API_KEY_ID`` and ``FOUNDRY_API_KEY_SECRET`` are set
(non-blank), the CLI is a machine client: it mints a short-lived access token through the
OAuth2 client-credentials grant (``POST /auth/v1/oauth/token``) for the SCOPE the calling
command needs. The env vars WIN over a stored interactive session — the credentials file is
never read or written in key mode, and ``foundry login`` / ``logout`` are skipped with a
warning. Exactly one of the two vars set is an error naming the missing one. Tokens are cached
in-process per scope and re-minted when fewer than 10 s of ``expires_in`` remain; a long R2
upload can outlive one 60 s token, so an uploading command re-asks for the token before its
final call.

Scope per command (the key must hold the scope — choose it when minting the key in the console):

    publish        fcm push, fcm publish, fcm channel set, fcm channel unset
    fmms:queues    fmms queues, fmms queue list / show / create / update / delete
    fcg:capacity   fcg capacity show / set

Every other authenticated command (``fmms submit/status/connect/cancel/play/create-queue/
form-match``, ``keys list/register``, ``keys generate --register``) is account- or player-scoped
and needs an interactive login; in key mode it fails with a message saying so.

**Interactive mode** (a human at a terminal) — there is no browser here, so the CLI uses the
same body-token endpoints the desktop launcher does (``/auth/v1/desktop/{login,refresh,logout}``).
The long-lived refresh token is stored in ``~/.foundry/credentials.json`` (0600). auth-efga
ROTATES the refresh token on every refresh, so :func:`access_token` rewrites the file each call —
presenting a stale token trips reuse-detection and revokes the session. The short-lived access
token is never persisted (minted per command). ``scope`` is ignored here: the session carries
the account's own capabilities.

This is distinct from the *project* ``.foundry/`` dir (workspace config) — credentials live under
the user's HOME.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from foundry_cli.core import fid
from foundry_cli.core.errors import FoundryError

_CREDS = Path.home() / ".foundry" / "credentials.json"

# --- API-key mode ------------------------------------------------------------------------------

KEY_ID_ENV = "FOUNDRY_API_KEY_ID"
KEY_SECRET_ENV = "FOUNDRY_API_KEY_SECRET"

# The scopes an API key can hold, one per command family (see the module docstring).
SCOPE_PUBLISH = "publish"
SCOPE_FMMS_QUEUES = "fmms:queues"
SCOPE_FCG_CAPACITY = "fcg:capacity"

KEY_CAPABLE_COMMANDS = "fcm push / publish / channel, fmms queue, fcg capacity"
INTERACTIVE_LOGIN_REQUIRED = (
    "This command needs an interactive login (`foundry login`). "
    f"API keys cover: {KEY_CAPABLE_COMMANDS}."
)

# Re-mint when fewer than this many seconds of the token's lifetime remain.
_REFRESH_MARGIN_S = 10.0
_DEFAULT_EXPIRES_IN_S = 60.0

# Injectable clock (tests monkeypatch ``auth._now``). Monotonic so a wall-clock jump can never
# resurrect an expired token.
_now = time.monotonic
# scope -> (access_token, expires_at on the ``_now`` clock)
_token_cache: dict[str, tuple[str, float]] = {}


def _key_env() -> tuple[str, str]:
    return os.environ.get(KEY_ID_ENV, "").strip(), os.environ.get(KEY_SECRET_ENV, "").strip()


def api_key_mode() -> bool:
    """True when both API-key env vars are set and non-blank (env wins over a stored session)."""
    key_id, secret = _key_env()
    return bool(key_id and secret)


def key_mode_notice(command: str) -> str:
    """The warning ``foundry login`` / ``logout`` print (and skip on) in API-key mode."""
    return (
        f"{KEY_ID_ENV} is set — the CLI is in API-key mode; "
        f"`foundry {command}` is not needed and was skipped."
    )


def _reject_half_set_key() -> None:
    """Exactly one of the two env vars set is a misconfiguration, not interactive mode."""
    key_id, secret = _key_env()
    if bool(key_id) != bool(secret):
        present, missing = (KEY_ID_ENV, KEY_SECRET_ENV) if key_id else (KEY_SECRET_ENV, KEY_ID_ENV)
        raise FoundryError(
            f"{present} is set but {missing} is missing — set both for API-key mode, "
            "or unset both to use `foundry login`."
        )


def _api_key() -> tuple[str, str]:
    """The (client_id, client_secret) pair from the env; raises naming a missing half."""
    _reject_half_set_key()
    key_id, secret = _key_env()
    if not key_id:
        raise FoundryError(f"{KEY_ID_ENV} and {KEY_SECRET_ENV} are not set.")
    return key_id, secret


def _expires_in(resp: dict) -> float:
    try:
        return float(resp.get("expires_in", _DEFAULT_EXPIRES_IN_S))
    except (TypeError, ValueError):
        return _DEFAULT_EXPIRES_IN_S


def _key_token(scope: str) -> str:
    """A client-credentials token for ``scope`` — cached, re-minted near expiry."""
    cached = _token_cache.get(scope)
    if cached is not None and cached[1] - _now() > _REFRESH_MARGIN_S:
        return cached[0]
    key_id, secret = _api_key()
    try:
        resp: Any = fid.auth_post(
            "/oauth/token",
            {
                "grant_type": "client_credentials",
                "client_id": key_id,
                "client_secret": secret,
                "scope": scope,
            },
        )
    except FoundryError as exc:
        # auth-efga answers 401 `invalid_client` for an unknown/revoked key AND for a scope the
        # key does not hold — say so in the CLI's own words.
        msg = str(exc)
        if "invalid_client" in msg or msg.startswith("HTTP 401"):
            raise FoundryError(
                f"API key rejected for scope '{scope}' — check {KEY_ID_ENV}/{KEY_SECRET_ENV} "
                "and that the key holds that scope."
            ) from exc
        raise
    # The token endpoint is NOT enveloped (a plain OAuth TokenResponse passes `_unwrap` as-is).
    if not isinstance(resp, dict) or not resp.get("access_token"):
        raise FoundryError("Unexpected token response from the auth service (no access_token).")
    token = str(resp["access_token"])
    _token_cache[scope] = (token, _now() + _expires_in(resp))
    return token


# --- Interactive session (desktop bearer flow) -------------------------------------------------


def _read() -> dict:
    if _CREDS.exists():
        try:
            return json.loads(_CREDS.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write(data: dict) -> None:
    _CREDS.parent.mkdir(parents=True, exist_ok=True)
    _CREDS.write_text(json.dumps(data), encoding="utf-8")
    try:  # best-effort 0600 (no-op semantics on Windows)
        os.chmod(_CREDS, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def login(identifier: str, password: str) -> dict:
    """Sign in (email or username + password); persist the rotated refresh token. Returns the user.

    In API-key mode this is a no-op (returns ``{}``) — the credentials file is never touched;
    the command layer prints :func:`key_mode_notice`.
    """
    if api_key_mode():
        return {}
    session = fid.auth_post(
        "/desktop/login",
        {"emailOrUsername": identifier, "password": password, "rememberMe": True},
    )
    if not isinstance(session, dict) or "refreshToken" not in session:
        raise FoundryError("Unexpected login response from the auth service.")
    _write({"refreshToken": session["refreshToken"]})
    return session.get("user", {})


def logout() -> None:
    """Revoke the stored session server-side (best effort) and delete the local credentials.

    In API-key mode this is a no-op — a stored session (if any) is left alone.
    """
    if api_key_mode():
        return
    rt = _read().get("refreshToken")
    if rt:
        try:
            fid.auth_post("/desktop/logout", {"refreshToken": rt})
        except Exception:
            pass
    if _CREDS.exists():
        _CREDS.unlink()


def _session_token() -> str:
    """Mint a fresh access token from the stored refresh token, rotating + re-persisting it."""
    rt = _read().get("refreshToken")
    if not rt:
        raise FoundryError("Not signed in. Run `foundry login` first.")
    session: Any = fid.auth_post("/desktop/refresh", {"refreshToken": rt})
    if not isinstance(session, dict) or "accessToken" not in session:
        raise FoundryError("Session expired. Run `foundry login` again.")
    # auth-efga rotates the refresh token on every refresh — persist the new one immediately.
    if session.get("refreshToken"):
        _write({"refreshToken": session["refreshToken"]})
    return session["accessToken"]


def access_token(scope: str | None = None) -> str:
    """Return a bearer access token for the next fid / auth-efga call.

    ``scope`` is the API-key scope the calling command needs (one of the ``SCOPE_*``
    constants); pass ``None`` from commands that only work with an interactive session.

    - **API-key mode** (both env vars set): mint a client-credentials token for ``scope``
      (``POST /auth/v1/oauth/token``), cached per scope in-process and re-minted when < 10 s
      remain — so calling this again right before a late request is cheap and always valid.
      ``scope=None`` raises: the command is not key-capable.
    - **Interactive mode**: mint from the stored refresh token (``/desktop/refresh``),
      rotating + re-persisting it. ``scope`` is ignored. Exactly one of the two env vars set
      raises naming the missing one rather than silently falling back to the session.
    """
    if api_key_mode():
        if scope is None:
            raise FoundryError(INTERACTIVE_LOGIN_REQUIRED)
        return _key_token(scope)
    _reject_half_set_key()
    return _session_token()
