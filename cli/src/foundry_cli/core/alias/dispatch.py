from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from foundry_cli.core.alias.store import load_aliases


def _prog_basename(argv0: str) -> str:
    name = Path(argv0).name
    # strip extensions used by Windows shims
    lowered = name.lower()
    for ext in (".exe", ".cmd", ".bat", ".ps1"):
        if lowered.endswith(ext):
            return name[: -len(ext)]
    return name


def expand_argv(argv: Sequence[str]) -> list[str]:
    """Expand alias invocation.

    If invoked as `fr ...` (argv0 basename != 'foundry'), we look up `fr` in
    aliases.json and prepend its configured argv prefix.

    We also support the explicit dispatch command:
      foundry alias exec <name> [args...]

    Returns a new argv list.
    """

    if not argv:
        return []

    # Explicit execution path used by .cmd shims:
    #   foundry alias exec <name> ...
    # Convert it into: foundry <alias-target...> <args...>
    def _maybe_hoist_run_options(prefix: list[str], rest: list[str]) -> tuple[list[str], list[str]]:
        """Click requires group options before the subcommand.

        For `run`, users will naturally type: `fr dev --debug`.
        This hoists known `run` options so the expanded argv becomes:
          foundry run --debug dev
        """

        if not prefix or prefix[0] != "run":
            return prefix, rest

        hoist: list[str] = []
        remaining: list[str] = []
        for a in rest:
            if a in ("--debug", "--no-debug"):
                hoist.append(a)
            else:
                remaining.append(a)
        if not hoist:
            return prefix, rest

        # Insert hoisted options right after `run`.
        return [prefix[0], *hoist, *prefix[1:]], remaining

    if len(argv) >= 4 and argv[1] == "alias" and argv[2] == "exec":
        alias_name = argv[3]
        rest = list(argv[4:])
        # Allow a `--` separator (written by our generated shims) so flags like
        # `--help` can be forwarded without Click interpreting them as options
        # for the hidden `alias exec` command if expansion fails.
        if rest and rest[0] == "--":
            rest = rest[1:]
        m = load_aliases().aliases
        prefix = m.get(alias_name)
        if prefix:
            prefix2, rest2 = _maybe_hoist_run_options(list(prefix), rest)
            return [argv[0], *prefix2, *rest2]
        # Unknown alias: drop the internal exec wrapper and let Click error on the real command.
        return [argv[0], *rest]

    prog = _prog_basename(argv[0])
    if prog.lower() in ("foundry", "foundry-cli"):
        return list(argv)

    m = load_aliases().aliases
    prefix = m.get(prog)
    if not prefix:
        return list(argv)

    prefix2, rest2 = _maybe_hoist_run_options(list(prefix), list(argv[1:]))
    return [argv[0], *prefix2, *rest2]


__all__ = ["expand_argv"]
