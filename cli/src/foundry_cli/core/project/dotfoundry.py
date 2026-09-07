"""Foundry project configuration directory (``.foundry/``) management.

The ``.foundry/`` directory lives alongside ``foundry.json`` at the project root
and contains both **committed** and **local-only** files:

  Committed (shared with team):
    - ``workspace.yml`` — resolved workspace state (services, launch config, drift)

  Gitignored (local per developer):
    - ``config.yml``  — personal CLI preferences / credential pointers

The split is enforced by a ``.foundry/.gitignore`` that Foundry creates.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from foundry_cli.core.errors import FoundryError

FOUNDRY_DIR_NAME = ".foundry"
FOUNDRY_CONFIG_FILENAME = "config.yml"
FOUNDRY_GENERATED_DIR = "generated"


@dataclass(frozen=True)
class FoundryProjectState:
    """Detection result for the state of a Foundry project directory.

    Checks for a manifest (``.foundry/foundry.json`` or root ``foundry.json``)
    and ``.foundry/`` at a given root.  The combinations drive ``foundry
    init`` behaviour:

    - **fresh**: neither exists → full init needed
    - **needs_upgrade**: manifest exists, no ``.foundry/`` → create the dir
    - **initialized**: both exist → already set up
    - **orphaned**: ``.foundry/`` without manifest → broken state
    """

    has_manifest: bool
    has_foundry_dir: bool
    manifest_path: Path | None
    foundry_dir_path: Path | None
    root: Path

    @property
    def is_initialized(self) -> bool:
        """Both manifest and .foundry/ exist — project is fully set up."""
        return self.has_manifest and self.has_foundry_dir

    @property
    def needs_upgrade(self) -> bool:
        """Manifest exists but .foundry/ does not (pre-init or legacy project)."""
        return self.has_manifest and not self.has_foundry_dir

    @property
    def is_fresh(self) -> bool:
        """Neither manifest nor .foundry/ exist — ready for a full init."""
        return not self.has_manifest and not self.has_foundry_dir

    @property
    def is_orphaned(self) -> bool:
        """.foundry/ exists without a manifest — broken state."""
        return not self.has_manifest and self.has_foundry_dir


def detect_project_state(directory: Path | None = None) -> FoundryProjectState:
    """Detect the Foundry project state of a directory.

    Checks for the presence of ``foundry.json`` and ``.foundry/`` in the
    specified directory.  Does **not** walk up parent directories — checks
    only the given (or current working) directory.

    Args:
        directory: Directory to check.  Defaults to CWD.

    Returns:
        A ``FoundryProjectState`` describing what was found.
    """
    root = (directory or Path.cwd()).resolve()

    foundry_dir_path = root / FOUNDRY_DIR_NAME

    # Same precedence as workspace.find_manifest_path: .foundry/foundry.json
    # (the multi-repo convention) wins over a root-level foundry.json (the
    # legacy/monorepo location).
    manifest_path: Path | None = None
    for candidate in (foundry_dir_path / "foundry.json", root / "foundry.json"):
        if candidate.is_file():
            manifest_path = candidate
            break

    has_manifest = manifest_path is not None
    has_foundry_dir = foundry_dir_path.is_dir()

    return FoundryProjectState(
        has_manifest=has_manifest,
        has_foundry_dir=has_foundry_dir,
        manifest_path=manifest_path,
        foundry_dir_path=foundry_dir_path if has_foundry_dir else None,
        root=root,
    )


def create_foundry_dir(root: Path) -> Path:
    """Create the ``.foundry/`` directory structure.

    Creates::

        .foundry/

    Args:
        root: Project root directory (where ``foundry.json`` lives or will live).

    Returns:
        Path to the created ``.foundry/`` directory.

    Raises:
        FoundryError: If ``.foundry/`` already exists or *root* doesn't exist.
    """
    foundry_dir = root / FOUNDRY_DIR_NAME

    if foundry_dir.exists():
        raise FoundryError(f".foundry/ directory already exists at {foundry_dir}")

    if not root.is_dir():
        raise FoundryError(f"Project root does not exist: {root}")

    # Create directory
    foundry_dir.mkdir()

    return foundry_dir


def ensure_foundry_dir(root: Path) -> Path:
    """Ensure ``.foundry/`` exists with proper structure.  Idempotent.

    Unlike :func:`create_foundry_dir`, this will **not** error if the directory
    already exists.  Missing subdirectories and files are created.

    Also writes ``.foundry/.gitignore`` to exclude local-only files while
    allowing committed files (``runtime.yml``) to be tracked.

    Returns:
        Path to the ``.foundry/`` directory.
    """
    if not root.is_dir():
        raise FoundryError(f"Project root does not exist: {root}")

    foundry_dir = root / FOUNDRY_DIR_NAME
    foundry_dir.mkdir(exist_ok=True)

    # Nested .gitignore — keeps local files out of VCS while letting
    # runtime.yml (team-shared config) be committed.
    _ensure_nested_gitignore(foundry_dir)

    return foundry_dir


# Managed block of .foundry/.gitignore: local-only files the CLI itself
# creates.  Everything outside the markers is user content and is preserved.
_NESTED_GITIGNORE_BEGIN = "# --- foundry managed (do not edit between markers) ---"
_NESTED_GITIGNORE_END = "# --- end foundry managed ---"
_NESTED_GITIGNORE_ENTRIES = (
    "config.yml",
    "dev.local.env",
    "*.local.env",
    "*.pem",
)

# Legacy (pre-managed-block) content this function used to write verbatim —
# recognized and migrated instead of duplicated.
_LEGACY_NESTED_LINES = frozenset({
    "# Foundry local files — DO NOT EDIT",
    "# Managed by `foundry sync`.  Only workspace.yml is committed.",
    "config.yml",
})


def _ensure_nested_gitignore(foundry_dir: Path) -> None:
    """Ensure ``.foundry/.gitignore`` carries the managed ignore block.

    Non-destructive: only the block between the managed markers is rewritten;
    hand-added lines outside it survive every ``foundry init``/``sync``.
    Legacy CLI-written content (the pre-marker format) is migrated into the
    managed block.
    """
    path = foundry_dir / ".gitignore"

    preserved: list[str] = []
    if path.exists():
        in_managed = False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == _NESTED_GITIGNORE_BEGIN:
                in_managed = True
                continue
            if stripped == _NESTED_GITIGNORE_END:
                in_managed = False
                continue
            if in_managed or stripped in _LEGACY_NESTED_LINES:
                continue
            preserved.append(line)

    # Drop leading/trailing blank runs left behind by the migration.
    while preserved and not preserved[0].strip():
        preserved.pop(0)
    while preserved and not preserved[-1].strip():
        preserved.pop()

    lines = [_NESTED_GITIGNORE_BEGIN, *_NESTED_GITIGNORE_ENTRIES, _NESTED_GITIGNORE_END]
    if preserved:
        lines += ["", *preserved]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_gitignore_entry(root: Path) -> bool:
    """Clean up legacy ``.foundry/`` entries from the root ``.gitignore``.

    In Foundry ≥0.3.0 we no longer gitignore the entire ``.foundry/``
    directory — ``runtime.yml`` is committed.  Local files are handled by
    ``.foundry/.gitignore`` instead.

    If the root ``.gitignore`` still contains a blanket ``.foundry/`` ignore
    line (from an earlier Foundry version), this function **removes** it.

    Returns:
        ``True`` if ``.gitignore`` was modified, ``False`` otherwise.
    """
    gitignore_path = root / ".gitignore"
    if not gitignore_path.exists():
        return False

    content = gitignore_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    # Remove lines that blanket-ignore .foundry/ and the comment before it
    new_lines: list[str] = []
    skip_next_blank = False
    i = 0
    modified = False
    while i < len(lines):
        stripped = lines[i].strip()

        # Remove the entry itself
        if stripped in (".foundry/", ".foundry"):
            modified = True
            # Also remove a preceding comment line if it's the Foundry header
            if new_lines and new_lines[-1].strip() == "# Foundry local configuration":
                new_lines.pop()
            # Eat trailing blank line
            if i + 1 < len(lines) and lines[i + 1].strip() == "":
                i += 1
            i += 1
            continue

        new_lines.append(lines[i])
        i += 1

    if modified:
        # Clean up trailing whitespace
        result = "".join(new_lines).rstrip("\n") + "\n"
        gitignore_path.write_text(result, encoding="utf-8")

    return modified


def ensure_path_ignored(root: Path, target: Path) -> bool:
    """Best-effort: make sure *target* is covered by a ``.gitignore``.

    Used for files the CLI writes that must never be committed (e.g. a
    bastion private key fetched by ``run dev``).  If *target* lives inside
    ``.foundry/`` the nested managed block already covers ``*.pem``; anything
    else gets an explicit entry appended to the root ``.gitignore``.

    Purely textual (no git invocation — the root may not even be a repo):
    the entry is considered present if the exact relative path, its basename,
    or a matching ``*.<suffix>`` glob already appears as a line.

    Returns:
        ``True`` if ``.gitignore`` was created or modified.
    """
    try:
        rel = target.resolve().relative_to(root.resolve())
    except ValueError:
        return False  # outside the workspace — nothing sensible to ignore

    rel_posix = rel.as_posix()
    gitignore_path = root / ".gitignore"

    existing: set[str] = set()
    if gitignore_path.exists():
        existing = {
            line.strip().rstrip("/")
            for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        }

    candidates = {rel_posix, f"/{rel_posix}", target.name}
    if target.suffix:
        candidates.add(f"*{target.suffix}")
    if existing & candidates:
        return False

    entry = (
        "\n# foundry: local key material written by `foundry run dev` — never commit\n"
        f"/{rel_posix}\n"
    )
    with gitignore_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)
    return True


__all__ = [
    "FOUNDRY_DIR_NAME",
    "FOUNDRY_CONFIG_FILENAME",
    "FOUNDRY_GENERATED_DIR",
    "FoundryProjectState",
    "create_foundry_dir",
    "detect_project_state",
    "ensure_foundry_dir",
    "ensure_gitignore_entry",
    "ensure_path_ignored",
]
