from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundry_cli.core.errors import FoundryError


@dataclass(frozen=True)
class ProjectManifest:
    """Represents a single Foundry project manifest file (typically `foundry.json`).

    Note: A future "platform" concept may aggregate multiple `ProjectManifest` instances
    across repositories.
    """

    path: Path
    data: dict[str, Any]

    @property
    def name(self) -> str | None:
        v = self.data.get("name")
        return v if isinstance(v, str) else None

    @property
    def services_dir_name(self) -> str:
        """Directory name (or relative path) containing runnable services.

        Configurable via `servicesDir` in `foundry.json`. Defaults to `apps`.
        """

        v = self.data.get("servicesDir")
        return v if isinstance(v, str) and v.strip() else "apps"


def load_manifest() -> ProjectManifest:
    """Load `foundry.json` from the current working directory."""

    cwd = Path.cwd()
    manifest_path = cwd / "foundry.json"
    if not manifest_path.exists():
        raise FoundryError(
            "Could not locate project manifest (foundry.json) in the current directory."
        )

    return load_manifest_from_path(manifest_path)


def load_manifest_from_path(manifest_path: Path) -> ProjectManifest:
    """Load a manifest from a specific path."""

    if not manifest_path.exists():
        raise FoundryError(f"Manifest file does not exist: {manifest_path}")

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise FoundryError(f"Invalid foundry.json (failed to parse JSON): {e}") from e

    if not isinstance(data, dict):
        raise FoundryError("Invalid foundry.json (root must be a JSON object).")

    return ProjectManifest(path=manifest_path, data=data)


__all__ = ["ProjectManifest", "load_manifest", "load_manifest_from_path"]
