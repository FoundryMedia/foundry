"""Client-side FCM v3 manifest assembly (BYO signing).

The publisher's machine content-addresses their build, assembles the signed root
`index.json` + immutable per-release doc, and signs the root LOCALLY (core.minisign) —
the platform never holds the private key. This mirrors the server-side split_v3 the ops
pipeline used, moved to the CLI so the dev is the sole assembler+signer.

The launcher trust chain this feeds: root pubkey -> publisher key (this signs index.json)
-> index.json records releaseDocSha256 -> release doc records each file sha -> content-
addressed files. Only index.json is signed; everything downstream is hash-vouched.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PLATFORM = "windows-x86_64"
_UA = {"User-Agent": "foundry-cli"}  # r2.dev 403s the default urllib UA


def content_address(staged_dir: Path, executable_relpath: str | None) -> tuple[list[dict], int]:
    """Walk a staged build dir -> [{path, sha256, size, executable?}], total bytes.

    Exactly one file is marked executable: the configured relpath, else the shallowest .exe.
    """
    files: list[dict] = []
    for p in sorted(staged_dir.rglob("*")):
        if not p.is_file():
            continue
        data = p.read_bytes()
        files.append({
            "path": p.relative_to(staged_dir).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })
    if not files:
        raise ValueError(f"no files under {staged_dir}")
    _mark_executable(files, executable_relpath)
    total = sum(f["size"] for f in files)
    return files, total


def _mark_executable(files: list[dict], executable_relpath: str | None) -> None:
    if executable_relpath:
        want = executable_relpath.replace("\\", "/")
        for f in files:
            if f["path"] == want:
                f["executable"] = True
                return
    exes = [f for f in files if f["path"].lower().endswith(".exe")]
    if not exes:
        raise ValueError("no .exe in the build and no executable path configured")
    exes.sort(key=lambda f: (f["path"].count("/"), len(f["path"])))
    exes[0]["executable"] = True


def release_doc(game_id: str, version: str, files: list[dict], total_size: int) -> dict:
    """The immutable per-release file list (verified by sha256 from the signed root)."""
    return {
        "manifestSchemaVersion": "3",
        "id": game_id,
        "version": version,
        "platforms": {PLATFORM: {"files": files, "totalSize": total_size}},
    }


def fetch_index(cdn_base: str) -> dict | None:
    """Fetch the game's current signed root index.json (to accumulate releases), or None."""
    try:
        req = urllib.request.Request(f"{cdn_base}/index.json", headers=_UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


def merge_release(
    existing: dict | None,
    *,
    game_id: str,
    publisher: str,
    title: str,
    version: str,
    doc_sha256: str,
    total_size: int,
    min_launcher_version: str,
    mandatory: bool,
    channel: str | None,
) -> dict:
    """Add this version to the (possibly existing) root index. Prior releases keep their
    recorded releaseDocSha256 (their docs are immutable + already published). `channel`
    non-None points that channel at this version (None = prerelease, pointer untouched)."""
    root = existing or {
        "manifestSchemaVersion": "3", "id": game_id, "publisher": publisher, "title": title,
        "description": "", "iconUrl": "", "bannerUrl": "",
        "channels": {}, "releases": {},
    }
    root["manifestSchemaVersion"] = "3"
    root["id"] = game_id
    root["publisher"] = publisher
    root["minLauncherVersion"] = min_launcher_version
    root.setdefault("channels", {})
    root.setdefault("releases", {})
    root["releases"][version] = {
        "publishedAt": datetime.now(timezone.utc).isoformat(),
        "mandatory": bool(mandatory),
        "totalSize": total_size,
        "releaseDoc": f"releases/{version}.json",
        "releaseDocSha256": doc_sha256,
    }
    if channel:
        root["channels"][channel] = version
    root["updatedAt"] = datetime.now(timezone.utc).isoformat()
    return root


def serialize(obj: dict) -> bytes:
    """Canonical serialization used for BOTH hashing and upload (the launcher hashes the
    exact bytes it fetches, so hash-input == upload-bytes)."""
    return json.dumps(obj, indent=2).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
