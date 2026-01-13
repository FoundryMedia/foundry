from __future__ import annotations

import click

from foundry_cli.core.errors import FoundryError


class FoundryGroup(click.Group):
	"""Click Group that styles usage/click errors and suppresses default Usage output."""

	def __init__(self, *args, **kwargs):
		# Disable Click's default --help so we can add our custom one
		kwargs.setdefault("add_help_option", False)
		super().__init__(*args, **kwargs)
		
		# Only add our help option if no help option already exists (check by flag names)
		has_help = any(
			isinstance(p, click.Option) and ("--help" in p.opts or "-h" in p.opts)
			for p in self.params
		)
		if not has_help:
			self.params.append(
				click.Option(
					["-h", "--help"],
					is_flag=True,
					expose_value=False,
					is_eager=True,
					callback=self._show_help,
					help="Show this message and exit.",
				)
			)

	def _show_help(self, ctx: click.Context, param: click.Parameter, value: bool) -> None:
		if not value:
			return
		self._print_custom_help(ctx)
		raise SystemExit(0)

	def _print_usage_line(self, prog: str, *, has_options: bool = True) -> None:
		usage_pieces = [
			click.style("Usage:", fg="yellow", bold=True),
			click.style(prog, fg="blue", bold=True),
		]
		if has_options:
			usage_pieces.append(click.style("[OPTIONS]", fg="blue"))
		usage_pieces += [
			click.style("COMMAND", fg="cyan", bold=True),
			click.style("[ARGS]...", fg="cyan"),
			click.style("", reset=True),
		]
		print(" ".join(usage_pieces))

	def _print_custom_help(self, ctx: click.Context) -> None:
		"""Print styled help for a command."""
		cmd = ctx.command
		prog = ctx.command_path
		has_options = any(isinstance(p, click.Option) for p in getattr(cmd, "params", []))

		self._print_usage_line(prog, has_options=has_options)

		# Description
		short = (cmd.get_short_help_str() or "").strip()
		if short:
			print()
			print(click.style(short, fg="green", bold=True) + click.style("", reset=True))

		# Help tip
		help_tip = getattr(cmd, "help_tip", None)
		if help_tip:
			print()
			print(
				click.style("Tip: ", fg="yellow", bold=True)
				+ click.style(help_tip, fg="yellow")
				+ click.style("", reset=True)
			)

		# Commands (for groups)
		if isinstance(cmd, click.MultiCommand):
			command_names = list(cmd.list_commands(ctx))
			if command_names:
				print()
				print(click.style("Commands:", fg="yellow", bold=True) + click.style("", reset=True))
				for name in sorted(command_names):
					subcmd = cmd.get_command(ctx, name)
					if subcmd is None:
						continue
					sub_name = click.style(name, fg="cyan", bold=True)
					sub_help = (subcmd.get_short_help_str() or "").strip()
					sub_help_styled = click.style(sub_help, fg="white")
					print(f"  {sub_name}  {sub_help_styled}{click.style('', reset=True)}")

		# Options
		options = [p for p in cmd.params if isinstance(p, click.Option)]
		if options:
			print()
			print(click.style("Options:", fg="yellow", bold=True) + click.style("", reset=True))
			for opt in options:
				opt_text = ", ".join(click.style(o, fg="blue", bold=True) for o in opt.opts)
				opt_help = (opt.help or "").strip()
				opt_help_styled = click.style(opt_help, fg="white")
				print(f"  {opt_text}  {opt_help_styled}{click.style('', reset=True)}")

	def main(self, *args, **kwargs):
		# We control formatting; don't let Click print tracebacks/usages.
		kwargs.setdefault("standalone_mode", False)
		try:
			return super().main(*args, **kwargs)

		except click.UsageError as e:
			prog = e.ctx.command_path if getattr(e, "ctx", None) else (self.name or "foundry")

			ctx = getattr(e, "ctx", None)
			cmd = ctx.command if ctx is not None else None
			is_root = bool(ctx is not None and cmd is self)
			has_options = bool(cmd is not None and any(isinstance(p, click.Option) for p in getattr(cmd, "params", [])))

			# Clean message: Click may include a full usage line in the message;
			# if so, replace it with a concise error.
			msg = (getattr(e, "message", None) or str(e)).strip()
			if msg.lower().startswith("usage:"):
				msg = "Missing command."
			elif msg == f"{prog} [OPTIONS] COMMAND [ARGS]...":
				msg = "Missing command."

			# Root command behavior: keep errors terse for unknown commands.
			if is_root and msg.lower().startswith("no such command"):
				self._print_usage_line(prog, has_options=has_options)
				print(
					click.style("Error:", fg="bright_red", bold=True)
					+ " "
					+ click.style(msg, fg="bright_red")
					+ click.style("", reset=True)
				)
				print()
				print(click.style("Try '", fg="yellow", bold=True) + click.style("foundry", fg="blue", bold=True) + click.style(" --help", fg="blue", bold=False) + click.style("' for a list of commands.", fg="yellow", bold=True))
				raise SystemExit(2)

			# Default behavior: show error then custom help
			print(
				click.style("Error:", fg="red", bold=True)
				+ " "
				+ click.style(msg, fg="bright_red")
				+ click.style("", reset=True)
			)
			print()

			if ctx is not None:
				self._print_custom_help(ctx)

			raise SystemExit(2)

		except click.ClickException as e:
			print(
				click.style("Error:", fg="red", bold=True)
				+ " "
				+ click.style(e.format_message(), fg="red")
				+ click.style("", reset=True)
			)
			raise SystemExit(1)

		except click.exceptions.Exit:
			raise

		except FoundryError as e:
			print(
				click.style("Error:", fg="red", bold=True)
				+ " "
				+ click.style(str(e), fg="bright_red")
				+ click.style("", reset=True)
			)
			raise SystemExit(1)
