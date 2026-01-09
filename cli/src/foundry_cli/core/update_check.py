from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

import click

from foundry_cli.core.versioning import get_local_version

LATEST_URL = "https://api.github.com/repos/FoundryMedia/foundry/releases/latest"
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours

_SEMVER_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?\s*$")


def _parse_semver(v: str) -> tuple[int, int, int] | None:
    m = _SEMVER_RE.match(v)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _cache_file() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.getcwd()
    return Path(root) / "Foundry" / "cache" / "update_check.json"


def _read_cache(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (time.time() - float(data.get("checked_at", 0))) <= CACHE_TTL_SECONDS:
            return data
    except Exception:
        return None
    return None


def _write_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _normalize_tag(tag: str) -> str:
    return tag[1:] if tag.startswith(("v", "V")) else tag


def _fetch_latest_release() -> dict | None:
    """
    Returns:
      {"tag": "v0.3.1", "latest": "0.3.1", "url": "<html_url>"}
    """
    req = urllib.request.Request(
        LATEST_URL,
        headers={
            "User-Agent": "foundry-cli",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        body = resp.read().decode("utf-8")

    data = json.loads(body)
    tag = data.get("tag_name")
    url = data.get("html_url")

    if not isinstance(tag, str):
        return None

    latest = _normalize_tag(tag)

    return {
        "tag": tag,
        "latest": latest,
        "url": url if isinstance(url, str) else None,
    }

def check_for_updates() -> tuple[str, str, str | None] | None:
    """
    Notify only. Do not block CLI behavior if network fails.
    Only notify when latest > local.

    Returns:
        (local_version, latest_version, url) if an update is available,
        otherwise None.
    """
    local = get_local_version()

    cache_path = _cache_file()
    cached = _read_cache(cache_path)

    if cached and "latest" in cached:
        latest = str(cached.get("latest") or "")
        url = cached.get("url")
        url = url if isinstance(url, str) else None
    else:
        try:
            rel = _fetch_latest_release()
            if not rel:
                return None
            latest = str(rel["latest"])
            url = rel.get("url")
            _write_cache(
                cache_path,
                {
                    "checked_at": time.time(),
                    "latest": latest,
                    "tag": rel.get("tag"),
                    "url": url,
                },
            )
        except Exception:
            return None

    if not latest:
        return None

    local_v = _parse_semver(local)
    latest_v = _parse_semver(latest)

    # If we can't parse versions reliably, don't spam users.
    if local_v is None or latest_v is None:
        return None

    if latest_v > local_v:
        return local, latest, url

    return None
