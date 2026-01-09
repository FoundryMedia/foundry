from __future__ import annotations

import click

from foundry_cli.core.update_check import check_for_updates
from foundry_cli.core.versioning import get_local_version, VersionResolutionError


def print_header(local: str) -> None:
    # ASCII logo
    print(
        click.style(
            r"       ______ ____  _    _ _   _ _____  _______     __", fg="blue", bold=True
        )
    )
    print(
        click.style(
            r"      |  ____/ __ \| |  | | \ | |  __ \|  __ \ \   / /",
            fg="blue",
            bold=True,
        )
    )
    print(
        click.style(
            r"      | |__ | |  | | |  | |  \| | |  | | |__) \ \_/ / ",
            fg="blue",
            bold=True,
        )
    )
    print(
        click.style(
            r"      |  __|| |  | | |  | | . ` | |  | |  _  / \   /  ",
            fg="blue",
            bold=True,
        )
    )
    print(
        click.style(
            r"      | |   | |__| | |__| | |\  | |__| | | \ \  | |   ",
            fg="blue",
            bold=True,
        )
    )
    print(
        click.style(
            r"      |_|    \____/ \____/|_| \_|_____/|_|  \_\ |_|   ",
            fg="blue",
            bold=True,
        )
    )
    print()
    print(
        click.style(
            f"                           v{local}",
            fg="blue",
            bold=True,
        )
    )
def print_update_banner(local: str, latest: str, url: str | None) -> None:
    
    print(
        click.style(
            "-----------------------------------------------------------------------",
            fg="blue",
        )
    )
    
    line = (
        click.style("Update available: ", fg="magenta", bold=True)
        + click.style(local, fg="red", bold=True)
        + click.style(" → ", fg="yellow", bold=True)
        + click.style(latest, fg="green", bold=True)
    )
    print(line)

    if url:
        print(click.style(f"Download: {url}", fg="cyan"))
    else:
        print(click.style("Run the latest installer from GitHub Releases to upgrade.", fg="cyan"))
        
    print(
        click.style(
            "-----------------------------------------------------------------------",
            fg="blue",
        )
    )
        
    
        
def display_help(ctx: click.Context) -> None:
    """Custom help display for the Foundry CLI root command."""

    update = check_for_updates()
    if update:
        local_version, latest_version, update_url = update
            
    print_header(local_version)
    
    if update:
        print_update_banner(local_version, latest_version, update_url)

    # Commands
    print(click.style("Commands:", fg="yellow", bold=True))
    for name, command in sorted(ctx.command.commands.items()):
        cmd_name = click.style(name, fg="bright_cyan", bold=True)
        cmd_help = (command.get_short_help_str() or "").strip()
        cmd_help_styled = click.style(cmd_help, fg="cyan")
        print(f"  {cmd_name}  {cmd_help_styled}")

    print()
    # Options
    print(click.style("Options:", fg="yellow", bold=True))
    for param in ctx.command.params:
        if not isinstance(param, click.Option):
            continue

        opts = ", ".join(
            click.style(opt, fg="cyan", bold=True) for opt in param.opts
        )
        help_text = (param.help or "").strip()
        help_styled = click.style(help_text, fg="white")
        print(f"  {opts}  {help_styled}")
        


@click.group(
    invoke_without_command=True
)
@click.option("--version", is_flag=True, help="Show Foundry CLI Version")
@click.option(
    "-h",
    "--help",
    "show_help",
    is_flag=True,
    help="Show this message and exit.",
)
@click.pass_context
def cli(ctx: click.Context, version: bool, show_help: bool) -> None:
    """
    Foundry CLI
    """
    if version:
        try:
           print(click.style(get_local_version(), fg="magenta", bold=True))
        except VersionResolutionError as e:
            print(click.style(str(e), fg="red", bold=True))
            raise SystemExit(1)
        raise SystemExit(0)
    
    if ctx.invoked_subcommand is not None:
        return

    # Base command no args
    display_help(ctx)

    
