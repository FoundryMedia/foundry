from __future__ import annotations

import argparse
import errno
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Foundry updater sidecar")
    parser.add_argument("--src", required=True, help="Path to downloaded updater payload")
    parser.add_argument("--target", required=True, help="Path to target executable")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds to wait for target to be replaceable")
    parser.add_argument("--relaunch", action="store_true", help="Relaunch the target after replacement")
    return parser.parse_args(argv)


def _stage_payload(src: Path, target: Path) -> Path:
    staged = target.with_name(target.name + ".new")
    if staged.exists():
        staged.unlink()
    shutil.copy2(src, staged)
    return staged


def _replace_with_retry(staged: Path, target: Path, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() <= deadline:
        try:
            os.replace(staged, target)
            return
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM, errno.EBUSY):
                last_error = exc
            else:
                raise
        time.sleep(0.4)
    if last_error:
        raise RuntimeError(f"timed out waiting for target to exit: {last_error}") from last_error
    raise RuntimeError("timed out waiting for target to exit")


def _relaunch_target(target: Path) -> None:
    subprocess.Popen([str(target)], close_fds=True)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    src = Path(args.src).resolve()
    target = Path(args.target).resolve()

    staged = None
    try:
        staged = _stage_payload(src, target)
        _replace_with_retry(staged, target, args.timeout)
    finally:
        if staged and staged.exists():
            try:
                staged.unlink()
            except Exception:
                pass

    if args.relaunch:
        _relaunch_target(target)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
