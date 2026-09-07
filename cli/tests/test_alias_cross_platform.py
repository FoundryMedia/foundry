"""Alias data-dir + shims must work on macOS/Linux, not just Windows.

Platform is faked via the `_is_windows` seam (never by patching os.name —
that breaks pathlib internals on the host).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry_cli.core.alias import shims, store
from foundry_cli.core.errors import FoundryError


def _fake_platform(monkeypatch: pytest.MonkeyPatch, *, windows: bool) -> None:
    monkeypatch.setattr(store, "_is_windows", lambda: windows)
    monkeypatch.setattr(shims, "_is_windows", lambda: windows)


def test_data_dir_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake_platform(monkeypatch, windows=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert store.foundry_data_dir() == tmp_path / "Foundry"


def test_data_dir_windows_requires_localappdata(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_platform(monkeypatch, windows=True)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(FoundryError):
        store.foundry_data_dir()


def test_data_dir_posix_is_dot_foundry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The old implementation raised on missing LOCALAPPDATA — macOS/Linux
    must get ~/.foundry instead of a crash."""
    _fake_platform(monkeypatch, windows=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert store.foundry_data_dir() == Path.home() / ".foundry"


def test_posix_shim_is_single_sh_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_platform(monkeypatch, windows=False)
    monkeypatch.setattr(store, "aliases_file", lambda: tmp_path / "aliases.json")
    store.set_alias("fr", ["run", "dev"])

    written = shims.write_cmd_shim("fr", bin_dir=tmp_path / "bin")
    assert written == tmp_path / "bin" / "fr"  # extension-less
    content = written.read_text(encoding="utf-8")
    assert content.startswith("#!/bin/sh")
    assert 'exec foundry run dev "$@"' in content

    paths = shims.shim_paths("fr", bin_dir=tmp_path / "bin")
    assert paths.cmd == paths.ps1 == written

    shims.remove_shim("fr", bin_dir=tmp_path / "bin")
    assert not written.exists()


def test_windows_shim_pair_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_platform(monkeypatch, windows=True)
    monkeypatch.setattr(store, "aliases_file", lambda: tmp_path / "aliases.json")
    store.set_alias("fr", ["run", "dev"])

    shims.write_cmd_shim("fr", bin_dir=tmp_path / "bin")
    assert (tmp_path / "bin" / "fr.cmd").exists()
    assert (tmp_path / "bin" / "fr.ps1").exists()
