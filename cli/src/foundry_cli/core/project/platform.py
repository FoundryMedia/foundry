from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundry_cli.core.errors import FoundryError


@dataclass(frozen=True)
class PlatformManifest:
    path: Path
    data: dict[str, Any]

    @property
    def name(self) -> str | None:
        v = self.data.get("name")
        return v if isinstance(v, str) else None


def load_manifest_from_cwd() -> PlatformManifest:
    """Load foundry.json from the current working directory."""
    cwd = Path.cwd()
    manifest_path = cwd / "foundry.json"
    if not manifest_path.exists():
        raise FoundryError(
            "Could not locate platform manifest (foundry.json) in the current directory."
        )

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise FoundryError(f"Invalid foundry.json (failed to parse JSON): {e}") from e

    if not isinstance(data, dict):
        raise FoundryError("Invalid foundry.json (root must be a JSON object).")

    return PlatformManifest(path=manifest_path, data=data)