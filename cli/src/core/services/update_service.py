from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

from src.core import version as _version


def _get_current_executable() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()


def _select_assets(release: Dict[str, Any]) -> Tuple[str, str]:
    """
    From the release JSON, return (zip_url, sha_url) for the Windows CLI.
    """
    assets = release.get("assets") or []
    zip_url = None
    sha_url = None
    for a in assets:
        name = a.get("name") or ""
        url = a.get("browser_download_url") or ""
        if name.endswith("-windows-amd64.zip"):
            zip_url = url
        elif name.endswith("-windows-amd64.zip.sha256"):
            sha_url = url

    if not zip_url or not sha_url:
        raise RuntimeError("Could not locate Windows CLI assets (zip + sha256) in release.")

    return zip_url, sha_url


def _download_file(url: str, dest: Path, timeout: float = 30.0) -> None:
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)


def _read_sha256_file(path: Path) -> str:
    """
    GitHub asset contents look like:
      <hash>  <filename>
    We only need the first token.
    """
    line = path.read_text(encoding="utf-8").strip()
    return line.split()[0]


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_and_stage_release(release: Dict[str, Any], temp_root: Path) -> Path:
    """
    Download ZIP + SHA, verify, extract into temp_root / 'new'.
    Returns the path to the new exe within that tree.
    """
    zip_url, sha_url = _select_assets(release)

    downloads_dir = temp_root / "downloads"
    new_dir = temp_root / "new"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)

    zip_path = downloads_dir / "foundrycli-windows-amd64.zip"
    sha_path = downloads_dir / "foundrycli-windows-amd64.zip.sha256"

    _download_file(zip_url, zip_path)
    _download_file(sha_url, sha_path)

    expected_hash = _read_sha256_file(sha_path)
    actual_hash = _compute_sha256(zip_path)
    if expected_hash.lower() != actual_hash.lower():
        raise RuntimeError("Checksum mismatch for downloaded update package.")

    # Extract into new_dir
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(new_dir)

    # Assume the new exe is named like the current exe and lives at the root
    current_exe = _get_current_executable()
    new_exe = new_dir / current_exe.name
    if not new_exe.exists():
        # Fallback: try to locate foundry.exe inside the extracted folder
        candidates = list(new_dir.rglob(current_exe.name))
        if not candidates:
            raise RuntimeError(f"New executable {current_exe.name} not found in extracted update.")
        new_exe = candidates[0]

    return new_exe


def _build_updater_cmd(old_exe: Path, new_exe: Path, temp_root: Path) -> List[str]:
    """
    Build the command to run the updater stub in a new process.
    """
    python_exe = sys.executable or "python"
    return [
        python_exe,
        "-m",
        "src.core.updater",
        "--old-exe",
        str(old_exe),
        "--new-exe",
        str(new_exe),
        "--temp-root",
        str(temp_root),
    ]


def execute_update(release: Dict[str, Any]) -> None:
    """
    Orchestrates the update for the given GitHub release JSON.

    Steps:
      1. Stage download in temp dir.
      2. Extract / verify checksum.
      3. Spawn updater stub to swap EXE.
      4. Exit current process.
    """
    local, latest, _ = _version.check_for_updates(timeout=0.1, include_release=False)
    # We don't need the remote response here, but we reuse local/latest for messages/logging
    # (this is a very fast, timeout=0.1 call; you can remove it if you cache elsewhere.)

    current_exe = _get_current_executable()

    temp_root = Path(tempfile.mkdtemp(prefix="foundrycli-update-")).resolve()
    new_exe = _download_and_stage_release(release, temp_root)

    cmd = _build_updater_cmd(current_exe, new_exe, temp_root)

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]

    subprocess.Popen(
        cmd,
        cwd=str(temp_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    raise SystemExit(0)