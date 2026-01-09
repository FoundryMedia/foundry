from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    # PyInstaller sets sys.frozen = True and sys._MEIPASS
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    """
    Returns a stable base directory:
    - Frozen: directory containing the executable
    - Source/installed: package directory
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent  # .../foundry_cli


def resources_dir() -> Path:
    if is_frozen():
        return base_dir()
    return base_dir() / "resources"