"""Tests for .foundry/ project-state detection and gitignore management."""
from __future__ import annotations

from pathlib import Path

from foundry_cli.core.project.dotfoundry import (
    _ensure_nested_gitignore,
    detect_project_state,
    ensure_path_ignored,
)


# ---------------------------------------------------------------------------
# detect_project_state — must recognize BOTH manifest layouts
# ---------------------------------------------------------------------------

def test_detect_fresh(tmp_path: Path) -> None:
    state = detect_project_state(tmp_path)
    assert state.is_fresh
    assert state.manifest_path is None


def test_detect_root_manifest_needs_upgrade(tmp_path: Path) -> None:
    (tmp_path / "foundry.json").write_text("{}", encoding="utf-8")
    state = detect_project_state(tmp_path)
    assert state.needs_upgrade
    assert state.manifest_path == tmp_path / "foundry.json"


def test_detect_nested_manifest_is_initialized(tmp_path: Path) -> None:
    """A repo shaped like the multi-repo convention (.foundry/foundry.json,
    no root manifest) is INITIALIZED — not orphaned."""
    foundry_dir = tmp_path / ".foundry"
    foundry_dir.mkdir()
    (foundry_dir / "foundry.json").write_text("{}", encoding="utf-8")

    state = detect_project_state(tmp_path)
    assert state.is_initialized
    assert not state.is_orphaned
    assert state.manifest_path == foundry_dir / "foundry.json"


def test_detect_nested_manifest_wins_over_root(tmp_path: Path) -> None:
    """Same precedence as workspace.find_manifest_path."""
    foundry_dir = tmp_path / ".foundry"
    foundry_dir.mkdir()
    (foundry_dir / "foundry.json").write_text("{}", encoding="utf-8")
    (tmp_path / "foundry.json").write_text("{}", encoding="utf-8")

    state = detect_project_state(tmp_path)
    assert state.manifest_path == foundry_dir / "foundry.json"


def test_detect_orphaned_only_when_no_manifest_anywhere(tmp_path: Path) -> None:
    (tmp_path / ".foundry").mkdir()
    state = detect_project_state(tmp_path)
    assert state.is_orphaned


# ---------------------------------------------------------------------------
# .foundry/.gitignore — managed block, non-destructive
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_nested_gitignore_fresh_write_covers_local_files(tmp_path: Path) -> None:
    _ensure_nested_gitignore(tmp_path)
    content = _read(tmp_path / ".gitignore")
    for entry in ("config.yml", "dev.local.env", "*.pem"):
        assert entry in content.splitlines()


def test_nested_gitignore_preserves_hand_added_lines(tmp_path: Path) -> None:
    _ensure_nested_gitignore(tmp_path)
    gi = tmp_path / ".gitignore"
    gi.write_text(_read(gi) + "\nmy-custom-file.txt\n", encoding="utf-8")

    # A second run (every init/sync calls this) must not nuke the entry.
    _ensure_nested_gitignore(tmp_path)
    lines = _read(gi).splitlines()
    assert "my-custom-file.txt" in lines
    assert "dev.local.env" in lines
    # Managed block appears exactly once.
    assert lines.count("config.yml") == 1


def test_nested_gitignore_migrates_legacy_format(tmp_path: Path) -> None:
    """The pre-marker CLI-written format is absorbed, not duplicated."""
    legacy = (
        "# Foundry local files — DO NOT EDIT\n"
        "# Managed by `foundry sync`.  Only workspace.yml is committed.\n"
        "\n"
        "config.yml\n"
        "hand-added.txt\n"
    )
    (tmp_path / ".gitignore").write_text(legacy, encoding="utf-8")

    _ensure_nested_gitignore(tmp_path)
    lines = _read(tmp_path / ".gitignore").splitlines()
    assert lines.count("config.yml") == 1
    assert "hand-added.txt" in lines
    assert "# Foundry local files — DO NOT EDIT" not in lines


# ---------------------------------------------------------------------------
# ensure_path_ignored — key material must never be committable
# ---------------------------------------------------------------------------

def test_ensure_path_ignored_appends_entry(tmp_path: Path) -> None:
    key = tmp_path / "bastion-key.pem"
    assert ensure_path_ignored(tmp_path, key) is True
    assert "/bastion-key.pem" in _read(tmp_path / ".gitignore").splitlines()


def test_ensure_path_ignored_idempotent(tmp_path: Path) -> None:
    key = tmp_path / "bastion-key.pem"
    ensure_path_ignored(tmp_path, key)
    assert ensure_path_ignored(tmp_path, key) is False


def test_ensure_path_ignored_respects_existing_glob(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.pem\n", encoding="utf-8")
    assert ensure_path_ignored(tmp_path, tmp_path / "bastion-key.pem") is False


def test_ensure_path_ignored_outside_root_is_noop(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert ensure_path_ignored(root, tmp_path / "elsewhere.pem") is False
    assert not (root / ".gitignore").exists()
