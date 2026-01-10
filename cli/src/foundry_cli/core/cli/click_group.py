from __future__ import annotations

import click

from foundry_cli.core.errors import FoundryError


class FoundryGroup(click.Group):
	"""Click Group that styles usage/click errors and suppresses default Usage output."""

	def _print_usage_line(self, prog: str) -> None:
		usage_pieces = [
			click.style("Usage:", fg="yellow", bold=True),
			click.style(prog, fg="blue", bold=True),
			click.style("[OPTIONS]", fg="blue"),
			click.style("COMMAND", fg="cyan", bold=True),
			click.style("[ARGS]...", fg="cyan"),
			click.style("", reset=True),
		]
		print(" ".join(usage_pieces))

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

			# Clean message: Click may include a full usage line in the message;
			# if so, replace it with a concise error.
			msg = (getattr(e, "message", None) or str(e)).strip()
			if msg.lower().startswith("usage:"):
				msg = "Missing command."
			elif msg == f"{prog} [OPTIONS] COMMAND [ARGS]...":
				msg = "Missing command."

			# Root command behavior: keep errors terse for unknown commands.
			# Example desired output for `foundry test`:
			#   Error: No such command 'test'.
			#   Try 'foundry --help' for usage.
			if is_root and msg.lower().startswith("no such command"):
				self._print_usage_line(prog)
				print(
					click.style("Error:", fg="bright_red", bold=True)
					+ " "
					+ click.style(msg, fg="bright_red")
					+ click.style("", reset=True)
				)
				print()
				print(click.style("Try '", fg="yellow", bold=True) + click.style("foundry", fg="blue", bold=True) + click.style(" --help", fg="blue", bold=False) + click.style("' for a list of commands.", fg="yellow", bold=True))
				raise SystemExit(2)

			# Default behavior: show a single colorized usage line + contextual help.
			self._print_usage_line(prog)
			print(
				click.style("Error:", fg="red", bold=True)
				+ " "
				+ click.style(msg, fg="bright_red")
				+ click.style("", reset=True)
			)

			# Show help for the command that failed (commands BEFORE options)
			if ctx is not None and isinstance(ctx.command, click.Command):
				cmd = ctx.command

				# Print the command's description (one line) if present.
				short = (cmd.get_short_help_str() or "").strip()
				if short:
					print()
					print(click.style(short, fg="green", bold=True) + click.style("", reset=True))

				# Commands first (for groups)
				if isinstance(cmd, click.MultiCommand):
					commands = getattr(cmd, "commands", {}) or {}
					if commands:
						print()
						print(
							click.style("Commands:", fg="yellow", bold=True)
							+ click.style("", reset=True)
						)
						for name, subcmd in sorted(commands.items()):
							sub_name = click.style(name, fg="cyan", bold=True)
							sub_help = (subcmd.get_short_help_str() or "").strip()
							sub_help_styled = click.style(sub_help, fg="white")
							print(f"  {sub_name}  {sub_help_styled}{click.style('', reset=True)}")

				# Options after commands
				options = [p for p in cmd.params if isinstance(p, click.Option)]
				if options:
					print()
					print(
						click.style("Options:", fg="yellow", bold=True)
						+ click.style("", reset=True)
					)
					for opt in options:
						opt_text = ", ".join(
							click.style(o, fg="blue", bold=True) for o in opt.opts
						)
						opt_help = (opt.help or "").strip()
						opt_help_styled = click.style(opt_help, fg="white")
						print(f"  {opt_text}  {opt_help_styled}{click.style('', reset=True)}")

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
				+ click.style(str(e), fg="red")
				+ click.style("", reset=True)
			)
			raise SystemExit(1)
