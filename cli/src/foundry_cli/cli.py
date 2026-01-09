from __future__ import annotations

import click

from foundry_cli.core.update_check import check_for_updates
from foundry_cli.core.versioning import (
    get_local_version,
    VersionResolutionError,
)
from foundry_cli.utils.formatting import success, error


@click.group(context_settings={"help_option_names": ["-h", "--help"]},
             invoke_without_command=True)
@click.option(
    "--version",
    is_flag=True,
    help="Show Foundry CLI version and exit",
)
def cli(version: bool) -> None:
    """
    Foundry CLI
    """
    if version:
        try:
            success(get_local_version())
        except VersionResolutionError as e:
            error(str(e))
            raise SystemExit(1)
        check_for_updates()
        raise SystemExit(0)
