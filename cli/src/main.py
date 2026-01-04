import sys

_import_error = None
try:
    import re
    import click
    from pathlib import Path

    from src.core import version

    class StyledGroup(click.Group):
        """Minimal styling for help output (title, usage, headings, flags)."""

        def _ensure_commands_registered(self):
            """Import & register subcommands once, before Click tries to resolve them."""
            if getattr(self, "_cmds_registered", False):
                return
            try:
                import src.commands as _cmds  # noqa: F401
                if hasattr(_cmds, "register_commands"):
                    _cmds.register_commands(self)
            except Exception as e:
                # keep the exception to surface later in a helpful way
                self._cmds_import_error = e
            finally:
                self._cmds_registered = True

        def _style_help_text(self, help_text: str) -> str:
            """Apply the same beautification used for the main help to any help text."""
            text = help_text
            try:
                local, _ = version.get_update_hint(timeout=0.5)
                title = click.style(f"Foundry CLI v{local}", fg="blue", bold=True)
                text = text.replace("Foundry CLI", title, 1)
            except Exception:
                pass

            def _usage_repl(m):
                remainder = m.group(1)
                return click.style("Usage:", fg="red", bold=True) + click.style(remainder, fg="red", bold=False)

            text = re.sub(r"^Usage:(.*)$", _usage_repl, text, count=1, flags=re.M)
            text = text.replace("Options:", click.style("Options:", fg="yellow", bold=True))
            text = text.replace("Commands:", click.style("Commands:", fg="yellow", bold=True))

            # color option names only when they appear at the start of an option line
            def _style_option_line(match):
                indent = match.group("indent") or ""
                opts = match.group("opts")
                # split combined forms like "-y, --yes" and style each token
                tokens = re.split(r",\s*", opts)
                styled = ", ".join(click.style(t, fg="cyan", bold=True) for t in tokens)
                return f"{indent}{styled}"

            # match lines that begin (option lines) with optional indent then one or more option tokens
            text = re.sub(
                r"(?m)^(?P<indent>\s*)(?P<opts>(?:-{1,2}[A-Za-z0-9][A-Za-z0-9\-_]*(?:,\s*)?)+)",
                _style_option_line,
                text,
            )
            return text

        def get_command(self, ctx, cmd_name):
            # ensure commands are available before Click looks up cmd_name
            self._ensure_commands_registered()
            if getattr(self, "_cmds_import_error", None):
                raise click.ClickException(f"Error loading commands: {type(self._cmds_import_error).__name__}: {self._cmds_import_error}")

            cmd = super().get_command(ctx, cmd_name)

            # Patch command help so subcommand `--help` output is styled like the group help
            if cmd is not None and not getattr(cmd, "_styled_help_applied", False):
                orig_get_help = cmd.get_help

                def _patched_get_help(inner_ctx, _orig=orig_get_help):
                    raw = _orig(inner_ctx)
                    try:
                        return self._style_help_text(raw)
                    except Exception:
                        return raw

                # override instance method
                cmd.get_help = _patched_get_help  # type: ignore
                cmd._styled_help_applied = True

            return cmd

        def list_commands(self, ctx):
            # ensure commands are available when Click lists them (help, tab-complete)
            self._ensure_commands_registered()
            if getattr(self, "_cmds_import_error", None):
                return []
            return super().list_commands(ctx)

        def format_commands(self, ctx, formatter):
            # keep your existing styling but ensure commands are registered first
            self._ensure_commands_registered()
            commands = []
            for name, cmd in self.commands.items():
                display_name = click.style(name, fg="green")
                help_text = cmd.get_short_help_str()
                commands.append((display_name, help_text))
            if commands:
                with formatter.section("Commands"):
                    formatter.write_dl(commands)

        def get_help(self, ctx):
            orig = super().get_help(ctx)
            help_text = orig

            try:
                local, _ = version.get_update_hint(timeout=0.5)
                title = click.style(f"Foundry CLI v{local}", fg="blue", bold=True)
                help_text = help_text.replace("Foundry CLI", title, 1)
            except Exception:
                pass

            def _usage_repl(m):
                remainder = m.group(1)
                return click.style("Usage:", fg="red", bold=True) + click.style(remainder, fg="red", bold=False)

            help_text = re.sub(r"^Usage:(.*)$", _usage_repl, help_text, count=1, flags=re.M)

            help_text = help_text.replace("Options:", click.style("Options:", fg="yellow", bold=True))
            help_text = help_text.replace("Commands:", click.style("Commands:", fg="yellow", bold=True))
            help_text = re.sub(r"(--[A-Za-z0-9\-\_]+)", lambda m: click.style(m.group(1), fg="cyan", bold=True), help_text)

            return help_text


    @click.group(cls=StyledGroup, invoke_without_command=True, name="foundry")
    @click.option("--version", "show_version", is_flag=True, help="Show version and exit.")
    @click.pass_context
    def cli(ctx: click.Context, show_version: bool):
        """
        Foundry CLI
        """
        try:
            local, latest = version.get_update_hint(timeout=0.6)
        except Exception as e:
            click.secho(f"Unexpected error: {type(e).__name__}: {e}", fg="red", bold=True, err=True)
            ctx.exit(1)

        if show_version:
            click.secho(local, fg="green", bold=True)
            ctx.exit(0)

        # Register commands lazily so import-time issues don't prevent help rendering
        try:
            import src.commands as _cmds
            # ask the commands package to register onto our click Group
            if hasattr(_cmds, "register_commands"):
                _cmds.register_commands(cli)
        except Exception as e:
            click.secho(f"Unexpected error: {type(e).__name__}: {e}", fg="red", bold=True, err=True)
            ctx.exit(1)

        try:
            if latest and version.is_newer(local, latest):
                click.secho("A new version is available ", fg="magenta", nl=False)
                click.secho(local, fg="red", nl=False)
                click.secho(" -> ", fg="yellow", nl=False)
                click.secho(latest, fg="green")
                click.secho("Use ", fg="blue", nl=False)
                click.secho("`foundry upgrade`", fg="yellow", nl=False)
                click.secho(" to update.", fg="blue")
        except Exception:
            pass

        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())

except Exception as exc:
    _import_error = exc
    try:
        import click as _click

        def _fallback_cli_main(ctx=None):
            _click.secho(f"Unexpected error: {type(_import_error).__name__}: {_import_error}", fg="red", bold=True, err=True)
            raise SystemExit(1)

        @_click.group(name="foundry", invoke_without_command=True)
        @_click.pass_context
        def cli(ctx):
            _fallback_cli_main(ctx)

    except Exception:
        cli = None

        def _run_fatal():
            print(f"Unexpected error: {type(_import_error).__name__}: {_import_error}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    try:
        if callable(globals().get("cli")) and globals().get("cli") is not None:
            cli()
        else:
            globals().get("_run_fatal", lambda: None)()
    except Exception as e:
        try:
            import click as _click
            _click.secho(f"Unexpected error: {type(e).__name__}: {e}", fg="red", bold=True, err=True)
        except Exception:
            print(f"Unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)