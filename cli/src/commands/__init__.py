from __future__ import annotations
from typing import Callable
from click import Group

# simple registration entrypoint used by src.main
def register_commands(root: Group) -> None:
    """
    Import subcommand modules and register their click commands on the root Group.
    Keep imports local so import errors are surfaced here and handled by the caller.
    """
    # import subcommands
    from . import upgrade  # noqa: F401

    # register commands expected to expose a click Command named `upgrade_cmd` or `cli`
    if hasattr(upgrade, "upgrade_cmd"):
        root.add_command(upgrade.upgrade_cmd)
    elif hasattr(upgrade, "cli"):
        root.add_command(upgrade.cli)