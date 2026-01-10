from __future__ import annotations

import click


class FoundryError(Exception):
    """Raised for user-facing Foundry CLI errors."""


class StyledClickException(click.ClickException):
    """Click exception with our styling and no Usage block."""

    def show(self, file=None) -> None:  # type: ignore[override]
        if file is None:
            file = click.get_text_stream("stderr")
        # ClickException normally prints "Error: ...". Keep it, but stylize.
        click.echo(click.style(f"Error: {self.message}", fg="red", bold=True), file=file)