from pathlib import Path
from typing import Optional, Tuple
import os
import re
import json
import urllib.request
import sys

try:
    from packaging.version import parse as _parse_version  # type: ignore
except Exception:
    _parse_version = None


class VersionError(RuntimeError):
    """Raised when the local version cannot be determined."""


def get_local_version() -> str:
    """
    Resolve local version from (in order):
      1) FOUNDRY_CLI_VERSION env var (dev/build override),
      2) src/VERSION next to package source (SOT),
      3) PyInstaller onefile runtime (_MEIPASS/VERSION),
      4) PyInstaller onedir runtime (exe parent / VERSION or exe parent / src / VERSION).

    Raises VersionError if no readable VERSION is found.
    """
    # 1) env override (useful for local dev)
    env_v = os.environ.get("FOUNDRY_CLI_VERSION")
    if env_v:
        return str(env_v).lstrip("v")

    candidates = []
    # 2) source SOT (src/VERSION)
    candidates.append(Path(__file__).resolve().parents[1] / "VERSION")

    # 3) PyInstaller onefile (sys._MEIPASS)
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "VERSION")
    except Exception:
        pass

    # 4) PyInstaller onedir: data placed next to executable (dist/<name>/VERSION)
    try:
        exe_parent = Path(sys.executable).resolve().parent
        candidates.append(exe_parent / "VERSION")
        candidates.append(exe_parent / "src" / "VERSION")
    except Exception:
        pass

    for p in candidates:
        try:
            if p.exists():
                v = p.read_text(encoding="utf-8").strip()
                if v:
                    return v.lstrip("v")
        except Exception:
            # ignore and try next candidate
            continue

    raise VersionError(
        "Unexpected error: version metadata (src/VERSION) not found. "
        "Ensure the build step has been run and the VERSION file is present."
    )


def _repo_from_pyproject() -> Optional[str]:
    try:
        base = Path(__file__).resolve().parents[2]
        pyproject = base / "pyproject.toml"
        if not pyproject.exists():
            return None
        try:
            import tomllib as _toml
            data = _toml.load(pyproject.open("rb"))
        except Exception:
            try:
                import toml as _toml  # type: ignore
                data = _toml.load(str(pyproject))
            except Exception:
                return None
        if not isinstance(data, dict):
            return None
        proj = data.get("project") or {}
        urls = proj.get("urls") or {}
        repo_url = urls.get("Repository") or urls.get("repository") or proj.get("repository")
        if isinstance(repo_url, str) and "github.com" in repo_url:
            m = re.search(r"github\.com/([^/]+/[^/]+)", repo_url)
            if m:
                return m.group(1)
        name = proj.get("name")
        if isinstance(name, str) and "/" in name:
            return name
    except Exception:
        pass
    return None


def fetch_latest_release(repo: Optional[str] = None, timeout: float = 1.0) -> Optional[str]:
    """
    Query GitHub Releases API for latest release tag (owner/repo).
    Returns tag without leading 'v' or None on failure.
    """
    if repo is None:
        repo = "FoundryMedia/foundry"
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "foundry-cli-updater/0.1",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
        data = json.loads(payload.decode("utf-8"))
        tag = data.get("tag_name") or data.get("name")
        if not tag:
            return None
        return str(tag).lstrip("v")
    except Exception:
        return None


def is_newer(local: str, remote: str) -> bool:
    if not remote:
        return False
    try:
        if _parse_version:
            return _parse_version(str(remote)) > _parse_version(str(local))
        def to_tuple(v: str):
            parts = re.split(r"[^\d]+", str(v))
            return tuple(int(p) if p.isdigit() else 0 for p in parts)
        return to_tuple(remote) > to_tuple(local)
    except Exception:
        return False


def check_for_updates(repo: Optional[str] = None, timeout: float = 1.0) -> Tuple[str, Optional[str]]:
    """
    Returns (local_version, latest_version_or_None).
    Raises VersionError if local version cannot be determined.
    """
    local = get_local_version()  # may raise VersionError
    try:
        repo_to_check = repo or _repo_from_pyproject() or "FoundryMedia/foundry"
        latest = fetch_latest_release(repo=repo_to_check, timeout=timeout)
    except Exception:
        latest = None
    return local, latest
