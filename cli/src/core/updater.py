from __future__ import annotations
import os
import sys
import shutil
import tempfile
import zipfile
import urllib.request
import urllib.error
import json
import hashlib
import platform
import subprocess
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
    except PermissionError:
        # try elevated helper on Windows
        if os.name == "nt":
            try:
                _elevated_install_onedir(zip_path, dest_dir)
                return
            except Exception as e:
                raise PermissionError(f"elevated onedir install failed: {e}") from e
        raise
    finally:
        if tmp.exists():
            try:
                shutil.rmtree(tmp)
            except Exception:
                pass

def _elevated_replace(src: Path, target: Path, timeout: int = 120) -> None:
    """
    On Windows: run a small helper script elevated (RunAs) that copies src -> target.new
    then os.replace to atomically swap. Waits for completion and raises on failure.
    """
    if os.name != "nt":
        raise PermissionError("elevation helper only implemented on Windows")

    # create helper script
    tmpdir = Path(tempfile.mkdtemp(prefix="foundry-elev-"))
    script = tmpdir / "replace_elevated.py"
    script.write_text(
        "import sys, shutil, os\n"
        "src = sys.argv[1]\n"
        "tgt = sys.argv[2]\n"
        "try:\n"
        "    # copy then atomic replace\n"
        "    shutil.copy2(src, tgt + '.new')\n"
        "    os.replace(tgt + '.new', tgt)\n"
        "    sys.exit(0)\n"
        "except Exception as e:\n"
        "    print('ELEVATED_REPLACE_FAILED:', e)\n"
        "    sys.exit(2)\n",
        encoding="utf-8",
    )

    # Build PowerShell Start-Process command to run elevated and wait
    py = sys.executable
    src_s = str(src)
    tgt_s = str(target)
    # Note: wrap paths in double quotes for PowerShell command string
    ps_cmd = (
        f'Start-Process -FilePath "{py}" -ArgumentList "{script}","{src_s}","{tgt_s}" -Verb RunAs -Wait'
    )

    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise PermissionError(f"elevated replacement failed (code {proc.returncode})")
    # cleanup
    try:
        script.unlink()
        tmpdir.rmdir()
    except Exception:
        pass

def install_onefile(exe_path: Path) -> None:
    """Replace current running exe with new exe. May require elevation if in Program Files."""
    exe_target = Path(sys.executable).resolve()
    tmp_target = exe_target.with_suffix(".new.exe")
    try:
        shutil.copy2(str(exe_path), str(tmp_target))
        os.replace(str(tmp_target), str(exe_target))
    except PermissionError:
        # If on Windows, try an elevated helper to perform the atomic replace
        if os.name == "nt":
            try:
                _elevated_replace(exe_path, exe_target)
                return
            except Exception as e:
                raise PermissionError(f"elevated update attempt failed: {e}") from e
        raise

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
        # Running from source: offer to install the downloaded onedir into a user-specified directory
        default_dest = Path.cwd() / "foundry-upgrade-test"
        if assume_yes:
            dest = default_dest
        else:
            prompt = (
                "Detected running from source (no automatic in-place upgrade).\n"
                f"Enter directory where to install the onedir (will be created) [{default_dest}]: "
            )
            resp = input(prompt).strip()
            if resp.lower() in ("", "y", "yes"):
                dest = default_dest
            elif resp.lower() in ("n", "no", "cancel", "q"):
                raise RuntimeError("user cancelled upgrade")
            else:
                dest = Path(os.path.expanduser(resp))

        dest.mkdir(parents=True, exist_ok=True)
        _downloaded_target = dl  # zip file path
        install_onedir(_downloaded_target, dest)

    return {"version": rel.get("tag_name") or rel.get("name"), "asset": asset.get("name")}