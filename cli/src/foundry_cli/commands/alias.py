from __future__ import annotations

import shlex
from pathlib import Path

import click

from foundry_cli.core.cli import FoundryGroup
from foundry_cli.core.errors import FoundryError
from foundry_cli.core.alias.shims import alias_bin_dir, remove_shim, validate_alias_name, write_cmd_shim
from foundry_cli.core.alias.store import load_aliases, remove_alias, set_alias


@click.group(cls=FoundryGroup)
def alias() -> None:
    """Manage Foundry command aliases."""


@alias.command("init", hidden=True)
@click.option(
    "--bin-dir",
    type=click.Path(path_type=str, file_okay=False, dir_okay=True),
    default=None,
    help="Where to write alias shims (defaults to packaged dir, env Scripts dir, or LOCALAPPDATA).",
)
def init_aliases(bin_dir: str | None) -> None:
    """Initialize alias support (creates alias bin directory)."""
    d = (click.Path(path_type=str).convert(bin_dir, None, None) if bin_dir else None)
    d_path = Path(d) if d else alias_bin_dir()
    d_path.mkdir(parents=True, exist_ok=True)
    print(f"Alias bin: {d_path}")
    print("Add this folder to your PATH to use aliases from source installs.")


@alias.command("list")
def list_aliases() -> None:
    """List configured aliases."""
    m = load_aliases().aliases
    if not m:
        print("No aliases configured.")
        return
    for name in sorted(m.keys()):
        print(f"{name} -> {' '.join(m[name])}")


@alias.command("set")
@click.option(
    "--bin-dir",
    type=click.Path(path_type=str, file_okay=False, dir_okay=True),
    default=None,
    help="Where to write the alias shim (defaults to packaged dir, env Scripts dir, or LOCALAPPDATA).",
)
@click.argument("name")
@click.argument("command", nargs=-1, required=True)
def set_alias_cmd(bin_dir: str | None, name: str, command: tuple[str, ...]) -> None:
    """Create/update an alias.

    Examples:
      foundry alias set fr run
      foundry alias set fd run dev

    If you want to pass a quoted command string, it will still work because we
    accept multiple tokens.
    """

    validate_alias_name(name)

    # If user passed a single string with spaces (rare with Click), split it.
    argv_prefix = list(command)
    if len(argv_prefix) == 1:
        argv_prefix = shlex.split(argv_prefix[0])

    if not argv_prefix:
        raise FoundryError("Alias target cannot be empty.")

    set_alias(name, argv_prefix)
    shim = write_cmd_shim(name, bin_dir=Path(bin_dir) if bin_dir else None)

    print(f"Alias '{name}' -> {' '.join(argv_prefix)}")
    print(f"Shim: {shim}")


@alias.command("remove")
@click.option(
    "--bin-dir",
    type=click.Path(path_type=str, file_okay=False, dir_okay=True),
    default=None,
    help="Where the alias shim is located (defaults to packaged dir, env Scripts dir, or LOCALAPPDATA).",
)
@click.argument("name")
def remove_alias_cmd(bin_dir: str | None, name: str) -> None:
    """Remove an alias and its shim."""
    validate_alias_name(name)
    remove_alias(name)
    remove_shim(name, bin_dir=Path(bin_dir) if bin_dir else None)
    print(f"Removed alias '{name}'.")


@alias.command("exec", hidden=True)
@click.argument("name")
@click.argument("args", nargs=-1)
def exec_alias_cmd(name: str, args: tuple[str, ...]) -> None:
    """Internal: used by .cmd shims to execute an alias.

    This command is not intended to be called directly by users.
    """
    # Execution is handled via argv expansion before Click parsing.
    # If we got here, no alias existed.
    raise FoundryError(f"Alias not found: {name}")


__all__ = ["alias"]
