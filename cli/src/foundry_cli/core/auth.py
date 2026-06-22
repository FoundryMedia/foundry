"""Foundry platform session for the CLI (the desktop bearer flow against auth-efga).

There is no browser here, so the CLI uses the same body-token endpoints the desktop launcher
does (``/auth/v1/desktop/{login,refresh,logout}``). The long-lived refresh token is stored in
``~/.foundry/credentials.json`` (0600). auth-efga ROTATES the refresh token on every refresh, so
:func:`access_token` rewrites the file each call — presenting a stale token trips reuse-detection
and revokes the session. The short-lived access token is never persisted (minted per command).

This is distinct from the *project* ``.foundry/`` dir (workspace config) — credentials live under
the user's HOME.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from foundry_cli.core import fid
from foundry_cli.core.errors import FoundryError

_CREDS = Path.home() / ".foundry" / "credentials.json"


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
    """Sign in (email or username + password); persist the rotated refresh token. Returns the user."""
    session = fid.auth_post(
        "/desktop/login",
        {"emailOrUsername": identifier, "password": password, "rememberMe": True},
    )
    if not isinstance(session, dict) or "refreshToken" not in session:
        raise FoundryError("Unexpected login response from the auth service.")
    _write({"refreshToken": session["refreshToken"]})
    return session.get("user", {})


def logout() -> None:
    """Revoke the stored session server-side (best effort) and delete the local credentials."""
    rt = _read().get("refreshToken")
    if rt:
        try:
            fid.auth_post("/desktop/logout", {"refreshToken": rt})
        except Exception:
            pass
    if _CREDS.exists():
        _CREDS.unlink()


def access_token() -> str:
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
