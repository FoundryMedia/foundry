"""The client-package chunk gate judges the GAME containers, never the engine's global.ucas."""
from pathlib import Path

import pytest

from foundry_cli.commands.package import _CHUNK_SIZE_GATE_BYTES, _validate_chunked_output
from foundry_cli.core.errors import FoundryError


def _sparse(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


def test_global_ucas_does_not_hide_a_monolith(tmp_path: Path) -> None:
    paks = tmp_path / "Game" / "Content" / "Paks"
    _sparse(paks / "global.ucas", 3 * 1024 * 1024)
    _sparse(paks / "Game-Windows.ucas", _CHUNK_SIZE_GATE_BYTES + 1)
    with pytest.raises(FoundryError, match="SINGLE"):
        _validate_chunked_output(tmp_path, chunking=True)


def test_chunked_cook_passes(tmp_path: Path) -> None:
    paks = tmp_path / "Game" / "Content" / "Paks"
    _sparse(paks / "global.ucas", 3 * 1024 * 1024)
    _sparse(paks / "pakchunk0-Windows.ucas", _CHUNK_SIZE_GATE_BYTES + 1)
    _sparse(paks / "pakchunk1-Windows.ucas", 50 * 1024 * 1024)
    _validate_chunked_output(tmp_path, chunking=True)


def test_monolith_allowed_when_chunking_is_off(tmp_path: Path) -> None:
    paks = tmp_path / "Game" / "Content" / "Paks"
    _sparse(paks / "Game-Windows.ucas", _CHUNK_SIZE_GATE_BYTES + 1)
    _validate_chunked_output(tmp_path, chunking=False)
