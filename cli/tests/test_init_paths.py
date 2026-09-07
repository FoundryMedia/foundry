"""End-to-end tests for the non-interactive `foundry init` paths.

The upgrade and re-init paths shipped broken once (`_generate_foundry_files`
called with a nonexistent kwarg — a TypeError AFTER files were half-written),
because nothing exercised them. These tests run the real command.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from foundry_cli.commands.init import init

MINIMAL_MANIFEST = {
    "schemaVersion": "0.7.0",
    "name": "test-platform",
    "services": {},
}


@pytest.fixture()
def in_tmp_repo(tmp_path: Path):
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _write_manifest(path: Path) -> None:
    path.write_text(json.dumps(MINIMAL_MANIFEST, indent=2), encoding="utf-8")


def test_init_upgrade_path_completes(in_tmp_repo: Path) -> None:
    """Existing root foundry.json, no .foundry/ — the first command a new
    adopter runs. Must complete and generate workspace.yml."""
    _write_manifest(in_tmp_repo / "foundry.json")

    result = CliRunner().invoke(init, [])
    assert result.exit_code == 0, result.output
    assert (in_tmp_repo / ".foundry" / "workspace.yml").is_file()


def test_init_reinit_path_completes(in_tmp_repo: Path) -> None:
    """Second run on an initialized repo (the _handle_existing path)."""
    _write_manifest(in_tmp_repo / "foundry.json")
    assert CliRunner().invoke(init, []).exit_code == 0

    result = CliRunner().invoke(init, ["--force"])
    assert result.exit_code == 0, result.output


def test_init_accepts_nested_manifest_layout(in_tmp_repo: Path) -> None:
    """A repo using the multi-repo convention (.foundry/foundry.json) must not
    be told to delete its manifest as 'orphaned'."""
    foundry_dir = in_tmp_repo / ".foundry"
    foundry_dir.mkdir()
    _write_manifest(foundry_dir / "foundry.json")

    result = CliRunner().invoke(init, [])
    assert result.exit_code == 0, result.output
    assert "unexpected state" not in result.output.lower()


def test_init_nested_gitignore_survives_reruns(in_tmp_repo: Path) -> None:
    """Hand-added entries in .foundry/.gitignore survive repeated inits."""
    _write_manifest(in_tmp_repo / "foundry.json")
    assert CliRunner().invoke(init, []).exit_code == 0

    gi = in_tmp_repo / ".foundry" / ".gitignore"
    gi.write_text(gi.read_text(encoding="utf-8") + "\ncustom.txt\n", encoding="utf-8")

    assert CliRunner().invoke(init, ["--force"]).exit_code == 0
    assert "custom.txt" in gi.read_text(encoding="utf-8").splitlines()
