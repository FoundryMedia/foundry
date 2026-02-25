"""``foundry github`` — GitHub integration commands.

Manage GitHub token configuration and test cross-repo discovery.
"""
from __future__ import annotations

import click

from foundry_cli.core.errors import FoundryError
from foundry_cli.core.github import (
    get_org,
    list_org_repos,
    resolve_token,
    save_token_to_config,
    validate_token,
)
from foundry_cli.core.project.dotfoundry import detect_project_state
from foundry_cli.core.project.manifest import load_manifest_from_path


# ------------------------------------------------------------------
# Group
# ------------------------------------------------------------------

@click.group("github", short_help="GitHub integration (token, discovery)")
def github() -> None:
    """Manage GitHub integration for cross-repo discovery."""


# ------------------------------------------------------------------
# foundry github auth
# ------------------------------------------------------------------

@github.command("auth", short_help="Configure or verify GitHub token")
@click.option(
    "--token", "-t",
    prompt=False,
    default=None,
    help="GitHub personal access token (if omitted, checks env vars and gh CLI).",
)
@click.option(
    "--save/--no-save",
    default=False,
    help="Save the token to .foundry/config.yml (gitignored).",
)
def auth(token: str | None, save: bool) -> None:
    """Configure or verify a GitHub personal access token.

    Resolution order:

    \b
    1. --token flag (this command)
    2. FOUNDRY_GITHUB_TOKEN env var
    3. GITHUB_TOKEN env var
    4. gh auth token (GitHub CLI)
    5. .foundry/config.yml → github.token

    If no token is found anywhere, prints setup instructions.
    """
    state = detect_project_state()

    if token:
        # User passed a token explicitly
        result_token = token
        source = "flag"
    else:
        # Try auto-resolution
        resolved = resolve_token(state.root if state.has_manifest else None)
        if not resolved.found:
            _print_setup_instructions()
            return
        result_token = resolved.token
        source = resolved.source

    # Validate the token
    click.echo(f"  Token source: {click.style(source, fg='cyan')}")
    click.echo("  Validating token... ", nl=False)
    try:
        user = validate_token(result_token)
    except FoundryError as exc:
        click.echo(click.style("✗", fg="red", bold=True))
        raise click.ClickException(str(exc))

    click.echo(click.style("✓", fg="green", bold=True))
    login = user.get("login", "unknown")
    name = user.get("name") or login
    click.echo(
        f"  Authenticated as: "
        f"{click.style(name, fg='green', bold=True)} "
        f"({click.style(login, fg='cyan')})"
    )

    # Optionally save
    if save:
        if not state.has_manifest:
            raise click.ClickException(
                "No foundry.json found — run `foundry init` first, "
                "then use --save from the project root."
            )
        path = save_token_to_config(state.root, result_token)
        click.echo(
            f"  Token saved to: {click.style(str(path), fg='yellow')}\n"
            f"  (This file is gitignored — it will NOT be committed.)"
        )


# ------------------------------------------------------------------
# foundry github discover
# ------------------------------------------------------------------

@github.command("discover", short_help="Discover platform repos in a GitHub org")
@click.option("--org", "-o", default=None, help="GitHub organisation login.")
@click.option("--prefix", "-p", default=None, help="Repo naming prefix to filter by.")
def discover(org: str | None, prefix: str | None) -> None:
    """Discover platform repositories in a GitHub organisation.

    If run inside a Foundry project (with foundry.json), reads the
    organisation, prefix, and repository name from the manifest.

    The primary platform repo is matched by its full name (derived from
    the platform name).  Satellite repos are matched by ``{prefix}-*``.

    Otherwise, --org and --prefix must be supplied.
    """
    state = detect_project_state()
    manifest = None
    main_repo: str | None = None

    # Try to load org/prefix/main_repo from manifest
    if state.has_manifest:
        try:
            manifest = load_manifest_from_path(state.manifest_path)
            # v0.4.0: github block; v0.3.0 fallback: ecosystem
            gh = manifest.github
            if gh:
                if not org:
                    org = gh.get("organization", "")
                if not prefix:
                    prefix = manifest.prefix
            # Fall back to derived prefix from platform name
            if not prefix:
                prefix = manifest.prefix
            main_repo = manifest.repository
        except Exception:
            pass

    if not org:
        raise click.ClickException(
            "No organisation specified.\n"
            "  Either run from a project with github.organization in foundry.json,\n"
            "  or pass --org <github-org>."
        )

    if not prefix and not main_repo:
        raise click.ClickException(
            "Cannot determine platform prefix or repository name.\n"
            "  Ensure foundry.json has a 'name' field, or pass --prefix."
        )

    # Resolve token
    resolved = resolve_token(state.root if state.has_manifest else None)
    if not resolved.found:
        _print_setup_instructions()
        raise click.ClickException("No GitHub token found.")

    click.echo(
        f"  Organisation: {click.style(org, fg='cyan', bold=True)}"
    )
    if main_repo:
        click.echo(
            f"  Platform repo: {click.style(main_repo, fg='cyan')}"
        )
    if prefix:
        click.echo(
            f"  Satellite filter: {click.style(prefix + '-*', fg='cyan')}"
        )
    click.echo(
        f"  Token source:  {click.style(resolved.source, fg='cyan')}"
    )
    click.echo()

    # Validate org
    try:
        org_info = get_org(org, resolved.token)
    except FoundryError as exc:
        raise click.ClickException(str(exc))

    click.echo(
        f"  {click.style('✓', fg='green', bold=True)} "
        f"Organisation: {click.style(org_info.login, fg='green')} "
        f"— {org_info.name or '(no display name)'}"
    )

    # List repos
    try:
        repos = list_org_repos(
            org, resolved.token, prefix=prefix, main_repo=main_repo,
        )
    except FoundryError as exc:
        raise click.ClickException(str(exc))

    if not repos:
        label = main_repo or f"{prefix}-*"
        click.echo(
            click.style(
                f"\n  No repositories found matching '{label}'.",
                fg="yellow",
            )
        )
        return

    click.echo(
        f"\n  Found {click.style(str(len(repos)), fg='green', bold=True)} "
        f"repositories:\n"
    )
    for repo in repos:
        vis = "🔒" if repo.private else "🌐"
        name_styled = click.style(repo.name, fg="cyan", bold=True)
        branch_styled = click.style(repo.default_branch, fg="yellow")
        if repo.name == main_repo:
            tag = click.style(" ★ primary", fg="green")
        else:
            tag = ""
        click.echo(
            f"    {vis} {name_styled}  (branch: {branch_styled}){tag}"
        )

    click.echo()


# ------------------------------------------------------------------
# Setup instructions (printed when no token is found)
# ------------------------------------------------------------------

def _print_setup_instructions() -> None:
    """Print user-friendly instructions for setting up a GitHub token."""
    click.echo()
    click.echo(click.style("  ╔══════════════════════════════════════════════╗", fg="yellow"))
    click.echo(click.style("  ║  GitHub Token Required for Repo Discovery   ║", fg="yellow"))
    click.echo(click.style("  ╚══════════════════════════════════════════════╝", fg="yellow"))
    click.echo()
    click.echo("  Foundry needs a GitHub token to discover platform repositories.")
    click.echo("  Choose one of the methods below:\n")
    click.echo(click.style("  Option A — GitHub CLI (recommended)", fg="green", bold=True))
    click.echo("    Install: https://cli.github.com/")
    click.echo("    Then run:")
    click.echo(click.style("      gh auth login", fg="cyan"))
    click.echo()
    click.echo(click.style("  Option B — Environment variable", fg="green", bold=True))
    click.echo("    Create a Personal Access Token at:")
    click.echo(click.style("      https://github.com/settings/tokens", fg="cyan"))
    click.echo("    Required scopes: repo, read:org")
    click.echo("    Then set:")
    click.echo(click.style("      $env:GITHUB_TOKEN = \"ghp_...\"", fg="cyan") + "  (PowerShell)")
    click.echo(click.style("      export GITHUB_TOKEN=ghp_...", fg="cyan") + "    (bash/zsh)")
    click.echo()
    click.echo(click.style("  Option C — .foundry/config.yml (per-project, gitignored)", fg="green", bold=True))
    click.echo("    Run:")
    click.echo(click.style("      foundry github auth --token ghp_... --save", fg="cyan"))
    click.echo("    This stores the token in .foundry/config.yml (which is gitignored).")
    click.echo()
