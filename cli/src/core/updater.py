from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List


def _wait_for_unlock(path: Path, timeout: float = 30.0, interval: float = 0.5) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not path.exists():
            return
        try:
            tmp = path.with_suffix(path.suffix + ".lockcheck")
            path.rename(tmp)
            tmp.rename(path)
            return
        except OSError:
            time.sleep(interval)


def _copy_tree_overwrite(src_root: Path, dst_root: Path) -> None:
    """
    Recursively copy all files/dirs from src_root into dst_root,
    overwriting existing files. Used to update supporting files
    alongside the EXE.
    """
    for root, dirs, files in os.walk(src_root):
        rel = Path(root).relative_to(src_root)
        target_dir = dst_root / rel
        target_dir.mkdir(parents=True, exist_ok=True)

        for name in files:
            src_file = Path(root) / name
            dst_file = target_dir / name
            shutil.copy2(src_file, dst_file)


def _atomic_replace(src: Path, dst: Path) -> None:
    backup = dst.with_suffix(dst.suffix + ".bak")
    if dst.exists():
        try:
            if backup.exists():
                backup.unlink()
            dst.rename(backup)
        except OSError:
            pass

    src.rename(dst)

    try:
        if backup.exists():
            backup.unlink()
    except OSError:
        pass


def _launch_new_cli_help(exe: Path) -> None:
    """
    Fire-and-forget run of `foundry --help` using the freshly updated exe.
    """
    try:
        args = [str(exe), "--help"]
        if os.name == "nt":
            # Non-blocking; let Windows resolve console behavior
            os.spawnv(os.P_NOWAIT, str(exe), args)
        else:
            os.spawnv(os.P_NOWAIT, str(exe), args)
    except Exception:
        # Non-fatal if we can't show help; update already applied.
        pass


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Foundry CLI updater stub.")
    parser.add_argument("--old-exe", required=True, help="Path to currently installed exe.")
    parser.add_argument("--new-exe", required=True, help="Path to new exe in staging dir.")
    parser.add_argument("--temp-root", required=True, help="Root temp directory for this update run.")

    ns = parser.parse_args(argv)
    old_exe = Path(ns.old_exe).resolve()
    new_exe = Path(ns.new_exe).resolve()
    temp_root = Path(ns.temp_root).resolve()

    # Wait for main process to exit and release locks
    _wait_for_unlock(old_exe, timeout=30.0, interval=0.5)

    # First copy all non-exe files over (config, libs, etc.)
    # new_exe.parent is the root of the extracted payload
    src_root = new_exe.parent
    dst_root = old_exe.parent
    _copy_tree_overwrite(src_root, dst_root)

    # Then atomically replace the exe itself
    try:
        _atomic_replace(dst_root / new_exe.name, old_exe)
    except Exception as e:
        sys.stderr.write(f"Failed to replace executable: {type(e).__name__}: {e}\n")
        return 1

    # Auto-run the updated CLI with --help so the user sees the new version
    _launch_new_cli_help(old_exe)

    # Cleanup temp
    try:
        shutil.rmtree(temp_root, ignore_errors=True)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())