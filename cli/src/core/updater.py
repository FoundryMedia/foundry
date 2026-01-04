from __future__ import annotations
import os
import sys
import json
import tempfile
import shutil
import hashlib
import platform
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

GITHUB_API = "https://api.github.com"

def _api_get(url: str, token: Optional[str] = None) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "foundry-updater/0.1", "Accept": "application/vnd.github.v3+json"})
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)

def _download_text(url: str, token: Optional[str] = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "foundry-updater/0.1"})
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8")

def fetch_latest_release(repo: str = "FoundryMedia/foundry", token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return GitHub release JSON for latest release or None (unauthenticated by default)."""
    try:
        return _api_get(f"{GITHUB_API}/repos/{repo}/releases/latest", token)
    except urllib.error.HTTPError as e:
        # keep behavior simple for public repos: return None on HTTP error (rate limit / not found / forbidden)
        return None
    except Exception:
        return None

def _platform_key() -> str:
    system = platform.system().lower()
    arch = platform.machine().lower()
    # simplify common names
    if system.startswith("windows"):
        sysname = "windows"
    elif system.startswith("linux"):
        sysname = "linux"
    elif system.startswith("darwin"):
        sysname = "macos"
    else:
        sysname = system
    return f"{sysname}-{arch}"

def choose_asset_for_current_run(release: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick best asset for this machine; expects naming convention like foundry-windows-x64.zip / .exe"""
    key = _platform_key()
    assets = release.get("assets", []) or []
    # heuristics: prefer zip (onedir) or exe (onefile); allow both
    candidates = []
    for a in assets:
        name = a.get("name", "").lower()
        if key in name:
            candidates.append(a)
    # fallback: try name containing system only
    if not candidates:
        for a in assets:
            if _platform_key().split("-")[0] in (a.get("name", "").lower()):
                candidates.append(a)
    # pick first candidate (could be refined)
    return candidates[0] if candidates else None

def download_asset(asset: Dict[str, Any], token: Optional[str] = None) -> Path:
    """Download asset to temp file and return Path."""
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("No download URL on asset")
    fd, tmp_path = tempfile.mkstemp(suffix=Path(url).suffix)
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "foundry-updater/0.1"})
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp_path, "wb") as out:
        shutil.copyfileobj(r, out)
    return Path(tmp_path)

def verify_sha256(path: Path, expected_hex: str) -> bool:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hex.lower()

def detect_packaging() -> str:
    """Return 'source', 'onedir' or 'onefile' depending on runtime."""
    if getattr(sys, "frozen", False):
        # onefile sets _MEIPASS; onedir generally has exe in dist/<name> directory
        if hasattr(sys, "_MEIPASS"):
            return "onefile"
        return "onedir"
    return "source"

def install_onedir(zip_path: Path, dest_dir: Path) -> None:
    """Extract zip into temp and atomically swap dest_dir. Safe: leaves .bak on failure."""
    import zipfile
    tmp = Path(tempfile.mkdtemp(prefix="foundry-update-"))
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmp)
        backup = dest_dir.with_name(dest_dir.name + ".bak")
        if dest_dir.exists():
            if backup.exists():
                shutil.rmtree(backup)
            shutil.move(str(dest_dir), str(backup))
        shutil.move(str(tmp), str(dest_dir))
        # cleanup backup on success could be done later
    finally:
        if tmp.exists():
            try:
                shutil.rmtree(tmp)
            except Exception:
                pass

def install_onefile(exe_path: Path) -> None:
    """Replace current running exe with new exe. May require elevation if in Program Files."""
    exe_target = Path(sys.executable).resolve()
    tmp_target = exe_target.with_suffix(".new.exe")
    # move downloaded into place then atomic rename
    shutil.copy2(str(exe_path), str(tmp_target))
    # On Windows, replace needs os.replace to be atomic
    os.replace(str(tmp_target), str(exe_target))

# high-level orchestrator (safe skeleton)
def perform_update_flow(repo: str = "FoundryMedia/foundry", token: Optional[str] = None, assume_yes: bool = False) -> Dict[str, Any]:
    """
    Orchestrate update:
      - fetch release metadata (unauthenticated by default)
      - choose platform asset
      - download optional checksum asset and verify
      - download asset and install
    """
    rel = fetch_latest_release(repo=repo, token=token)
    if not rel:
        raise RuntimeError("unable to fetch latest release; ensure a published GitHub release exists and is reachable")

    asset = choose_asset_for_current_run(rel)
    if not asset:
        raise RuntimeError("no suitable asset found for this platform in release")

    # try to find a matching .sha256 asset (same name + ".sha256")
    assets = rel.get("assets", []) or []
    checksum_asset = None
    expected_hex = None
    desired_sha_name = asset.get("name", "") + ".sha256"
    for a in assets:
        if a.get("name", "") == desired_sha_name:
            checksum_asset = a
            break
    if checksum_asset:
        try:
            txt = _download_text(checksum_asset.get("browser_download_url"), token=token).strip()
            # common formats: "<hex>  filename" or just "<hex>"
            expected_hex = txt.split()[0]
        except Exception:
            expected_hex = None

    dl = download_asset(asset, token=token)

    if expected_hex:
        ok = verify_sha256(dl, expected_hex)
        if not ok:
            raise RuntimeError("downloaded asset failed checksum verification")

    pkg = detect_packaging()
    if pkg == "onedir":
        exe_parent = Path(sys.executable).resolve().parent
        dest = exe_parent if exe_parent.name != "" else Path.cwd()
        install_onedir(dl, dest)
    elif pkg == "onefile":
        install_onefile(dl)
    else:
        raise RuntimeError("auto-update not supported for source installs; run pip install/update manually")

    return {"version": rel.get("tag_name") or rel.get("name"), "asset": asset.get("name")}