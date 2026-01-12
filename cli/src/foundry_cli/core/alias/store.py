from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundry_cli.core.errors import FoundryError


def _localappdata() -> Path:
    v = os.environ.get("LOCALAPPDATA")
    if not v:
        raise FoundryError("LOCALAPPDATA is not set; cannot manage aliases on this system.")
    return Path(v)


def foundry_data_dir() -> Path:
    return _localappdata() / "Foundry"


def aliases_file() -> Path:
    return foundry_data_dir() / "aliases.json"


@dataclass(frozen=True)
class AliasMap:
    aliases: dict[str, list[str]]


def load_aliases() -> AliasMap:
    path = aliases_file()
    if not path.exists():
        return AliasMap(aliases={})

    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise FoundryError(f"Invalid aliases file: {path} ({e})") from e

    if not isinstance(data, dict):
        raise FoundryError(f"Invalid aliases file: {path} (root must be object)")

    aliases: dict[str, list[str]] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not k:
            continue
        if isinstance(v, list) and all(isinstance(x, str) and x for x in v):
            aliases[k] = v

    return AliasMap(aliases=aliases)


def save_aliases(alias_map: AliasMap) -> None:
    path = aliases_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(alias_map.aliases, indent=2), encoding="utf-8")


def set_alias(name: str, argv_prefix: list[str]) -> None:
    m = load_aliases()
    m.aliases[name] = argv_prefix
    save_aliases(m)


def remove_alias(name: str) -> None:
    m = load_aliases()
    if name in m.aliases:
        del m.aliases[name]
        save_aliases(m)


__all__ = [
    "AliasMap",
    "foundry_data_dir",
    "aliases_file",
    "load_aliases",
    "save_aliases",
    "set_alias",
    "remove_alias",
]
