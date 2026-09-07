import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
import time
import click
import threading
from typing import List, Optional
import platform

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SRC_DIR = ROOT / "src"
VERSION_FILE = SRC_DIR / "foundry_cli" / "resources" / "VERSION"
ISS_FILE = Path(__file__).resolve().parent / "installer" / "foundry-cli-installer-setup.iss"

# record high-resolution start time for duration-based timestamps
START_NS = time.perf_counter_ns()

def _fmt_duration_ns(now_ns: int) -> str:
    # return duration since START_NS WITHOUT a leading '+'; 4-decimal precision
    delta_ns = now_ns - START_NS
    secs = delta_ns / 1_000_000_000
    return f"{secs:.4f}s"

def _styled_log(level: str, message: str):
    """Print a single formatted log line with duration timestamp, colored level, and white message."""
    ts = _fmt_duration_ns(time.perf_counter_ns())
    lvl = (level or "INFO").upper()
    # ensure a stable 7-char level cell even if caller passes weird string
    lvl_cell = (lvl[:7]).ljust(7)
    color_map = {
        "INFO": "blue",
        "WARNING": "yellow",
        "WARN": "yellow",
        "ERROR": "red",
        "CRITICAL": "red",
    }
    color = color_map.get(lvl, "blue")
    ts_s = click.style(f"[{ts}]", fg="bright_black")
    level_s = click.style(lvl_cell, fg=color, bold=True)
    msg_s = click.style(message, fg="white")
    print(f"{ts_s} {level_s} {msg_s}")

def _styled_step(message: str, version: str | None = None, level: str = "INFO"):
    """
    Styled step output: timestamp + colored level, message colored cyan.
    If `version` is provided, that substring is highlighted in magenta (bold).
    """
    ts = _fmt_duration_ns(time.perf_counter_ns())
    lvl = (level or "INFO").upper()
    color_map = {"INFO": "blue", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "red"}
    lvl_color = color_map.get(lvl, "blue")
    ts_s = click.style(f"[{ts}]", fg="bright_black")
    level_s = click.style(f"{lvl:7}", fg=lvl_color, bold=True)

    if version:
        idx = message.find(version)
        if idx != -1:
            pre = message[:idx]
            post = message[idx + len(version) :]
            msg_s = click.style(pre, fg="cyan") + click.style(version, fg="magenta", bold=True) + click.style(post, fg="cyan")
        else:
            msg_s = click.style(message, fg="cyan")
    else:
        msg_s = click.style(message, fg="cyan")

    print(f"{ts_s} {level_s} {msg_s}")

def _styled_final(message: str):
    """Final success message: timestamp + bold green message."""
    ts = _fmt_duration_ns(time.perf_counter_ns())
    ts_s = click.style(f"[{ts}]", fg="bright_black")
    msg_s = click.style(message, fg="green", bold=True)
    print(f"{ts_s} {msg_s}")

def _process_and_log_line(line: str):
    """
    Parse and print subprocess lines. Special-case Windows drive-letter paths so they
    don't accidentally get mis-parsed as a short "level" token.
    """
    if not line:
        return

    sline = line.rstrip("\r\n")

    # If the line looks like a Windows absolute path (e.g. "D:\..." or "D   \...") treat as INFO message
    if re.match(r'^\s*[A-Za-z]:(\\|/)', sline) or re.match(r'^\s*[A-Za-z]\s+\\', sline):
        _styled_log("INFO", sline.strip())
        return

    # Try PyInstaller numeric prefix + LEVEL
    m = re.match(r"^\s*\d+\s+([A-Z]+):\s*(.*)$", sline)
    if m:
        level, msg = m.group(1), m.group(2)
        _styled_log(level, msg)
        return
    # Try generic "LEVEL: message"
    m2 = re.match(r"^\s*([A-Z]+):\s*(.*)$", sline)
    if m2:
        level, msg = m2.group(1), m2.group(2)
        _styled_log(level, msg)
        return
    # Default: plain INFO
    _styled_log("INFO", sline)

def _stream_subprocess(cmd: List[str], cwd: str = None):
    """
    Run subprocess and stream combined stdout/stderr, formatting each line.
    Returns the process returncode (raises CalledProcessError on non-zero to keep behavior).
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        cwd=cwd,
    )

    # Read lines as they arrive
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            _process_and_log_line(line)
    finally:
        proc.stdout.close()
    rc = proc.wait()
    return rc

def read_pyproject_version():
    if not PYPROJECT.exists():
        raise SystemExit(f"FATAL: pyproject.toml not found at {PYPROJECT}. This repo is the source of truth.")
    # prefer tomllib (py3.11+)
    try:
        import tomllib as _toml
        data = _toml.loads(PYPROJECT.read_bytes().decode("utf-8"))
    except Exception:
        try:
            import toml as _toml  # type: ignore
            data = _toml.load(str(PYPROJECT))
        except Exception as e:
            raise SystemExit(f"FATAL: cannot parse pyproject.toml ({e})")
    proj = data.get("project") if isinstance(data, dict) else {}
    version = proj.get("version")
    if not version:
        raise SystemExit("FATAL: project.version not found in pyproject.toml")
    return str(version).lstrip("v")

def update_version_file(version: str):
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(version.strip(), encoding="utf-8")
    _styled_step(f"Wrote version {version} to {VERSION_FILE}", version=version)

def update_iss_version(version: str, source_folder: str | None = None):
    if not ISS_FILE.exists():
        raise SystemExit(f"FATAL: installer .iss file not found at {ISS_FILE}")
    text = ISS_FILE.read_text(encoding="utf-8")

    # Update first #define MyVersion "..." occurrence
    ver_pattern = re.compile(r'^(?P<prefix>\s*#\s*define\s+MyVersion\s+)(?P<quote>"|\')(?P<ver>.*?)\2', flags=re.M)
    m = ver_pattern.search(text)
    if not m:
        _styled_log("WARNING", "could not find '#define MyVersion' line to update in .iss file.")
    else:
        current = m.group("ver").strip()
        if current == version:
            _styled_log("INFO", f".iss MyVersion already up-to-date (\"{current}\")")
        else:
            replacement = f'{m.group("prefix")}{m.group("quote")}{version}{m.group("quote")}'
            text = text[: m.start()] + replacement + text[m.end() :]
            _styled_log("INFO", f"Updated MyVersion in .iss from \"{current}\" to \"{version}\"")

    # Update first #define SourceFolder "..." occurrence if requested
    if source_folder:
        # normalize to backslashes for .iss and append wildcard if not present
        sf = str(Path(source_folder)).replace("/", "\\")
        if not sf.endswith("*"):
            if sf.endswith("\\") or sf.endswith("/"):
                sf = sf + "*"
            else:
                sf = sf + "\\*"
        src_pattern = re.compile(r'^(?P<prefix>\s*#\s*define\s+SourceFolder\s+)(?P<quote>"|\')(?P<path>.*?)\2', flags=re.M)
        ms = src_pattern.search(text)
        if not ms:
            _styled_log("WARNING", "could not find '#define SourceFolder' line to update in .iss file.")
        else:
            cur_path = ms.group("path").strip()
            if cur_path == sf:
                _styled_log("INFO", f".iss SourceFolder already up-to-date ({cur_path})")
            else:
                replacement = f'{ms.group("prefix")}{ms.group("quote")}{sf}{ms.group("quote")}'
                text = text[: ms.start()] + replacement + text[ms.end() :]
                _styled_log("INFO", f"Updated SourceFolder in .iss from {cur_path} to {sf}")

    # Backup & write if changed
    backup = ISS_FILE.with_suffix(".iss.bak")
    shutil.copy2(ISS_FILE, backup)
    ISS_FILE.write_text(text, encoding="utf-8")
    _styled_step(f"Saved .iss (backup at {backup})", version=version)

def run_pyinstaller(version: str) -> Path:
    # include the VERSION file at root level (exe_dir() / "VERSION" for packaged installs)
    adddata = f"{str(VERSION_FILE)}{os.pathsep}."
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onedir",
        "--name",
        "foundry",
        "--add-data",
        adddata,
        str(SRC_DIR / "foundry_cli" / "__main__.py"),
    ]
    _styled_step("Running PyInstaller: " + " ".join(cmd))
    rc = _stream_subprocess(cmd, cwd=str(ROOT))
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)

    # return the expected dist directory path (pyinstaller --name foundry -> dist/foundry)
    dist_dir = ROOT / "dist" / "foundry"
    if not dist_dir.exists():
        # fallback: check dist root for any recently-created dir
        raise SystemExit(f"FATAL: expected pyinstaller output at {dist_dir} not found")
    return dist_dir

def run_inno_setup() -> Optional[Path]:
    """
    Find and run Inno Setup Compiler (ISCC). Honors ISCC_PATH env var or searches PATH.
    Streams and colorizes output; logs a WARNING and returns None if ISCC not found.
    If successful, returns Path to produced installer (.exe) when detectable.
    """
    iscc = os.environ.get("ISCC_PATH") or shutil.which("ISCC")
    if not iscc:
        _styled_log("WARNING", "ISCC (Inno Setup) not found on PATH and ISCC_PATH not set — skipping installer creation.")
        return None

    cmd = [iscc, str(ISS_FILE)]
    _styled_step("Running Inno Setup Compiler: " + " ".join(cmd))
    start_ts = time.time()
    rc = _stream_subprocess(cmd, cwd=str(ISS_FILE.parent))
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)

    # try to locate produced installer .exe. Search ISS_FILE.parent recursively (includes Output\)
    candidates = []
    try:
        for p in ISS_FILE.parent.rglob("*.exe"):
            try:
                if not p.is_file():
                    continue
                mtime = p.stat().st_mtime
            except Exception:
                continue
            candidates.append((mtime, p))
    except Exception:
        candidates = []

    if candidates:
        # prefer files modified after the run started, else pick newest
        recent = [p for m, p in candidates if m >= start_ts - 5]
        chosen = None
        if recent:
            chosen = max(recent, key=lambda p: p.stat().st_mtime)
        else:
            chosen = max([p for m, p in candidates], key=lambda p: p.stat().st_mtime)
        _styled_log("INFO", f"Detected installer produced by Inno Setup at {chosen}")
        return chosen
    else:
        _styled_log("WARNING", "Could not detect produced installer .exe after running ISCC.")
        return None

def _platform_key() -> str:
    system = platform.system().lower()
    arch = platform.machine().lower()
    if system.startswith("windows"):
        sysname = "windows"
    elif system.startswith("linux"):
        sysname = "linux"
    elif system.startswith("darwin"):
        sysname = "macos"
    else:
        sysname = system
    return f"{sysname}-{arch}"

def _archive_dir_to(dst_archive: Path, src_dir: Path) -> None:
    # Archive src_dir contents (not a parent folder). Windows ships a zip;
    # POSIX ships a tar.gz — zipfile does not preserve the executable bit,
    # so a zipped macOS/Linux build would need a manual chmod after extract.
    if dst_archive.name.endswith(".tar.gz"):
        base = str(dst_archive)[: -len(".tar.gz")]
        shutil.make_archive(base, "gztar", root_dir=str(src_dir), base_dir=".")
    else:
        base = str(dst_archive.with_suffix(""))
        shutil.make_archive(base, "zip", root_dir=str(src_dir), base_dir=".")
    _styled_log("INFO", f"Created archive {dst_archive}")

def create_release_target(version: str, dist_dir: Path, installer_path: Optional[Path]) -> Path:
    """
    Create package/target/{version}/ and place:
      - foundrycli-{version}-{platform}.zip  (contents of dist_dir)
      - foundrycli-{version}-{platform}.zip.sha256
      - installer .exe (copied) if present (original removed from installer/ to avoid bloat)
    Returns the version directory Path.
    """
    pkg_dir = Path(__file__).resolve().parent
    target_root = pkg_dir / "target"
    version_dir = target_root / version
    version_dir.mkdir(parents=True, exist_ok=True)

    platform_key = _platform_key()
    ext = ".zip" if platform.system() == "Windows" else ".tar.gz"
    archive_name = f"foundrycli-{version}-{platform_key}{ext}"
    archive_path = version_dir / archive_name

    _styled_step(f"Archiving dist contents to {archive_path}", version=version)
    _archive_dir_to(archive_path, dist_dir)

    _styled_step("Computing checksum", version=version)
    sha = _sha256_of_file(archive_path)
    sha_file = version_dir / (archive_name + ".sha256")
    sha_file.write_text(f"{sha}  {archive_name}", encoding="utf-8")
    _styled_log("INFO", f"Wrote checksum to {sha_file}")

    if installer_path and installer_path.exists():
        try:
            dest_installer = version_dir / installer_path.name
            shutil.copy2(str(installer_path), str(dest_installer))
            _styled_log("INFO", f"Copied installer to {dest_installer}")

            # remove original installer produced in the installer/ directory to avoid bloat
            try:
                installer_dir = ISS_FILE.parent
                # only remove if the original installer lives inside the packager's installer dir
                if installer_dir in installer_path.parents or installer_path.parent == installer_dir:
                    try:
                        installer_path.unlink()
                        _styled_log("INFO", f"Removed original installer from {installer_dir}")
                    except Exception as ex_del:
                        _styled_log("WARNING", f"Failed to remove original installer {installer_path}: {ex_del}")
            except Exception:
                # non-fatal: don't block packaging if cleanup fails
                pass

        except Exception as e:
            _styled_log("WARNING", f"Failed to copy installer into target dir: {e}")
    else:
        _styled_log("WARNING", "No installer found to include in target; only zip and checksum are present.")

    _styled_step(f"Release artifacts available at {version_dir}", version=version)
    return version_dir

def _sha256_of_file(path: Path) -> str:
    """Return hex sha256 of a file."""
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    version = read_pyproject_version()
    update_version_file(version)

    # run pyinstaller first so we can update the .iss to point to the actual dist
    dist_dir = run_pyinstaller(version)

    installer = None
    if platform.system() == "Windows":
        # compute a path relative to the .iss location (so the .iss keeps portable relative path)
        rel = os.path.relpath(dist_dir, start=ISS_FILE.parent)
        # convert to backslashes for Inno Setup and append wildcard
        rel_win = str(Path(rel)).replace("/", "\\")
        if not rel_win.endswith("*"):
            if rel_win.endswith("\\"):
                rel_win = rel_win + "*"
            else:
                rel_win = rel_win + "\\*"

        # now update the .iss with both version and SourceFolder
        update_iss_version(version=version, source_folder=rel_win)

        # compile installer (if ISCC available). Capture produced installer path when possible.
        installer = run_inno_setup()
    else:
        _styled_log("INFO", f"Non-Windows host ({platform.system()}) — skipping Inno Setup installer.")

    # create release/target artifacts: archive of dist, checksum, and include installer
    create_release_target(version=version, dist_dir=dist_dir, installer_path=installer)

    _styled_final("Build complete.")

if __name__ == "__main__":
    main()