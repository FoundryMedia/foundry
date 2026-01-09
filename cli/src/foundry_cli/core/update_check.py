from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

import click

from foundry_cli.core.versioning import get_local_version

LATEST_URL = "https://api.github.com/repos/FoundryMedia/foundry/releases/latest"
CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours


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


def _fetch_latest_tag() -> str | None:
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
    return tag if isinstance(tag, str) else None


def _normalize_tag(tag: str) -> str:
    return tag[1:] if tag.startswith(("v", "V")) else tag


def check_for_updates() -> None:
    """
    Notify only. Do not block CLI behavior if network fails.
    """
    local = get_local_version()

    cache_path = _cache_file()
    cached = _read_cache(cache_path)
    if cached and "latest" in cached:
        latest = str(cached["latest"])
    else:
        try:
            tag = _fetch_latest_tag()
            latest = _normalize_tag(tag) if tag else ""
            _write_cache(cache_path, {"checked_at": time.time(), "latest": latest})
        except Exception:
            return

    # note: local version resolution is fatal by design; if we got here it's valid.
    if latest and latest != local:
        click.echo(
            f"Update available: {local} → {latest}\n"
            f"Run the latest MSI installer from GitHub Releases to upgrade.",
            err=True,
        )
