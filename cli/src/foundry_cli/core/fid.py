"""Foundry platform HTTP client (auth-efga issuer + fid API).

Stdlib-only (urllib + json), mirroring core/github.py. Two hosts:
  - AUTH_BASE  https://auth.foundryplatform.app  — the token issuer (desktop bearer flow)
  - API_BASE   https://api.foundryplatform.app   — fid (FCM build endpoints, ...)

Both speak the JsonApiResponse envelope ``{"data": ..., "errors": [{code,message}]}``; the
helpers below unwrap ``data`` and raise :class:`FoundryError` (with the server's message) on
failure. Presigned R2 PUTs are plain (no auth, no envelope) and stream from disk.

Override the hosts with FOUNDRY_AUTH_BASE / FOUNDRY_API_BASE (local dev);
FOUNDRY_CDN_BASE / FOUNDRY_CONSOLE_BASE cover the published-content CDN and
the web console the same way (another org points all four at its own hosts).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from foundry_cli.core.errors import FoundryError

AUTH_BASE = os.environ.get("FOUNDRY_AUTH_BASE", "https://auth.foundryplatform.app")
API_BASE = os.environ.get("FOUNDRY_API_BASE", "https://api.foundryplatform.app")
CDN_BASE = os.environ.get("FOUNDRY_CDN_BASE", "https://cdn.foundryplatform.app").rstrip("/")
CONSOLE_BASE = os.environ.get("FOUNDRY_CONSOLE_BASE", "https://foundryplatform.app/console").rstrip("/")
_UA = "foundry-cli"


def _unwrap(envelope: Any) -> Any:
    if isinstance(envelope, dict) and "data" in envelope:
        return envelope["data"]
    return envelope


def _send(url: str, *, method: str, token: str | None, body: dict | None, timeout: int = 60) -> Any:
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        raise FoundryError(_http_message(exc)) from exc
    except urllib.error.URLError as exc:
        raise FoundryError(f"Cannot reach {url}: {exc.reason}") from exc


def _http_message(exc: urllib.error.HTTPError) -> str:
    """Pull the friendliest message out of a JsonApiResponse error envelope."""
    body = ""
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    try:
        env = json.loads(body)
        errs = env.get("errors") if isinstance(env, dict) else None
        if errs:
            first = errs[0]
            return first.get("message") or first.get("code") or f"HTTP {exc.code}"
    except Exception:
        pass
    return f"HTTP {exc.code}: {body[:300]}" if body else f"HTTP {exc.code}"


def auth_post(path: str, body: dict, token: str | None = None) -> Any:
    """POST to the auth-efga issuer ({AUTH_BASE}/auth/v1{path}); returns unwrapped data."""
    return _unwrap(_send(f"{AUTH_BASE}/auth/v1{path}", method="POST", token=token, body=body))


def api_request(path: str, *, method: str = "GET", token: str | None = None, body: dict | None = None) -> Any:
    """Call fid ({API_BASE}{path}) with a bearer token; returns unwrapped data."""
    return _unwrap(_send(f"{API_BASE}{path}", method=method, token=token, body=body))


def put_file(url: str, filepath: str, timeout: int = 1800, attempts: int = 5,
             content_type: str | None = None) -> None:
    """Stream a file to a presigned PUT URL (R2). No auth/envelope; streams from disk.

    `content_type` MUST match what the presigner signed when the URL was minted with
    one (fid's publish presigns bake it into the SigV4 signature — a missing/different
    Content-Type is a 403; urllib would otherwise default to x-www-form-urlencoded).

    Retries transient network failures (connection aborts/resets — AV scanners and
    flaky uplinks kill long PUTs; a presigned S3 PUT is all-or-nothing, so the only
    recovery is a fresh attempt). HTTP 4xx never retries (expired/invalid presign).
    """
    import time

    size = os.path.getsize(filepath)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        with open(filepath, "rb") as f:
            headers = {"User-Agent": _UA, "Content-Length": str(size)}
            if content_type:
                headers["Content-Type"] = content_type
            req = urllib.request.Request(
                url,
                data=f,
                method="PUT",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status not in (200, 201, 204):
                        raise FoundryError(f"Upload failed: HTTP {resp.status}")
                    return
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    raise FoundryError(f"Upload failed: HTTP {exc.code}") from exc
                last = exc
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
                last = exc
        if attempt < attempts:
            time.sleep(min(2 ** attempt, 20))
    reason = getattr(last, "reason", None) or last
    raise FoundryError(f"Upload failed after {attempts} attempts: {reason}") from last
