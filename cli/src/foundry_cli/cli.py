from __future__ import annotations

import click

from foundry_cli.core.errors import FoundryError, StyledClickException
from foundry_cli.core.update_check import check_for_updates
from foundry_cli.core.versioning import get_local_version, VersionResolutionError

from foundry_cli.commands.run import run

class FoundryGroup(click.Group):
    """Click Group that styles usage/click errors and suppresses default Usage output."""

    def main(self, *args, **kwargs):
        kwargs.setdefault("standalone_mode", False)
        try:
            return super().main(*args, **kwargs)

        except click.UsageError as e:
            # Build a colored Usage line in the exact format you want
            prog = e.ctx.command_path if getattr(e, "ctx", None) else (self.name or "foundry")

            usage_pieces = [
                click.style("Usage:", fg="yellow", bold=True),
                click.style(prog, fg="blue", bold=True),
                click.style("[OPTIONS]", fg="blue"),
                click.style("COMMAND", fg="cyan", bold=True),
                click.style("[ARGS]...", fg="cyan"),
            ]

            print(" ".join(usage_pieces))
            print(
                click.style("Error:", fg="red", bold=True)
                + " "
                + click.style(e.format_message(), fg="bright_red")
            )
            raise SystemExit(2)

        except click.ClickException as e:
            print(
                click.style("Error:", fg="red", bold=True)
                + " "
                + click.style(e.format_message(), fg="red")
            )
            raise SystemExit(1)

        except click.exceptions.Exit:
            raise

        except FoundryError as e:
            print(
                click.style("Error:", fg="red", bold=True)
                + " "
                + click.style(str(e), fg="red")
            )
            raise SystemExit(1)

def register_commands(root: click.Group) -> None:
    root.add_command(run)


def print_header(local: str) -> None:
    # ASCII logo
    print(click.style(r"       ______ ____  _    _ _   _ _____  _______     __", fg="blue", bold=True))
    print(click.style(r"      |  ____/ __ \| |  | | \ | |  __ \|  __ \ \   / /", fg="blue", bold=True))
    print(click.style(r"      | |__ | |  | | |  | |  \| | |  | | |__) \ \_/ / ", fg="blue", bold=True))
    print(click.style(r"      |  __|| |  | | |  | | . ` | |  | |  _  / \   /  ", fg="blue", bold=True))
    print(click.style(r"      | |   | |__| | |__| | |\  | |__| | | \ \  | |   ", fg="blue", bold=True))
    print(click.style(r"      |_|    \____/ \____/|_| \_|_____/|_|  \_\ |_|   ", fg="blue", bold=True))
    print()
    print(click.style(f"                         v{local}", fg="blue", bold=True))
    
def print_update_banner(local: str, latest: str, url: str | None) -> None:
    print(click.style("-----------------------------------------------------------------------", fg="blue", bold=True))

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

    print(click.style("-----------------------------------------------------------------------", fg="blue", bold=True))
        
    
        
def display_help(ctx: click.Context) -> None:
    """Custom help display for the Foundry CLI root command."""

    local_version, latest_version, update_url = check_for_updates()
            
    print_header(local_version)

    if latest_version:
        print_update_banner(local_version, latest_version, update_url)

    # Commands
    print(click.style("Commands:", fg="yellow", bold=True))
    for name, command in sorted(ctx.command.commands.items()):
        cmd_name = click.style(name, fg="cyan", bold=True)
        cmd_help = (command.get_short_help_str() or "").strip()
        cmd_help_styled = click.style(cmd_help, fg="white")
        print(f"  {cmd_name}  {cmd_help_styled}")

    print()
    # Options
    print(click.style("Options:", fg="yellow", bold=True))
    for param in ctx.command.params:
        if not isinstance(param, click.Option):
            continue

        opts = ", ".join(
            click.style(opt, fg="blue", bold=True) for opt in param.opts
        )
        help_text = (param.help or "").strip()
        help_styled = click.style(help_text, fg="white")
        print(f"  {opts}  {help_styled}")
        

@click.group(
    cls=FoundryGroup,
    invoke_without_command=True
)
@click.option("-v", "--version", is_flag=True, help="Show Foundry CLI Version")
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
    try:
        if version:
            try:
                print(click.style(get_local_version(), fg="blue", bold=True))
            except VersionResolutionError as e:
                raise FoundryError(str(e)) from e
            raise SystemExit(0)

        if show_help:
            display_help(ctx)
            raise SystemExit(0)

        if ctx.invoked_subcommand is not None:
            return

        display_help(ctx)

    except FoundryError as e:
        raise StyledClickException(str(e)) from e
    
register_commands(cli)

    
