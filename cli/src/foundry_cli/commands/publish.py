"""`foundry publish` — REMOVED. Kept as a hidden shim that points to the new commands.

The old `publish` conflated three things — cooking a build, uploading it, and "publishing to
the Foundry App" — which read as though the CLI could publish (and charge). It can't: publishing
to the Foundry App is a BILLED action that must go through the web console's checkout.

The surface is now split into two honest, local-vs-network steps:
  foundry package --client / --server   # cook/containerize LOCALLY (no upload, no charge)
  foundry fcm push                        # upload the packaged artifact to FCM
"""

from __future__ import annotations

import click


@click.command(hidden=True)
@click.option("--version", "version", default=None, hidden=True)
@click.option("--submit", "do_submit", is_flag=True, default=False, hidden=True)
def publish(version, do_submit) -> None:
    """REMOVED — use `foundry package` then `foundry fcm push`."""
    raise click.ClickException(
        "`foundry publish` was renamed. Use `foundry package --client` (or `--server`) to package "
        "the build locally, then `foundry fcm push` to upload it. Publishing to the Foundry App is "
        "done in the web console (a billed checkout) — the CLI never charges you."
    )
