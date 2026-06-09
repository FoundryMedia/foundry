"""``foundry config`` — Display toolchain status and platform configuration.

Shows the status of external tools that Foundry orchestrates:

- **AWS CLI** — credentials, account ID, region
- **GitHub CLI** — authentication, user
- **OpenTofu** — version (if installed)

Foundry never stores credentials.  It reads from whatever the developer
has configured locally (``aws configure``, ``gh auth login``, env vars).

Examples::

    foundry config --show          # show toolchain + project status
    foundry config discover        # discover platform repos in GitHub org
"""
from __future__ import annotations

import subprocess

import click

from foundry_cli.core.errors import FoundryError
from foundry_cli.core.github import (
    get_org,
    list_org_repos,
    resolve_token,
)
from foundry_cli.core.project.dotfoundry import detect_project_state
from foundry_cli.core.project.manifest import load_manifest_from_path


# ------------------------------------------------------------------
# Group
# ------------------------------------------------------------------

@click.group("config", invoke_without_command=True, short_help="Show toolchain status")
@click.option(
    "--show",
    is_flag=True,
    default=False,
    help="Print toolchain and project status.",
)
@click.pass_context
def config(ctx: click.Context, show: bool) -> None:
    """Display Foundry toolchain status and project configuration.

    Foundry orchestrates external tools — it never stores credentials.
    This command shows what's detected from your local environment.
    """
    if show or ctx.invoked_subcommand is None:
        _show_toolchain_status()
        return


# ------------------------------------------------------------------
# foundry config discover
# ------------------------------------------------------------------

@config.command("discover", short_help="Discover platform repos in a GitHub org")
@click.option("--org", "-o", default=None, help="GitHub organisation login.")
@click.option("--prefix", "-p", default=None, help="Repo naming prefix to filter by.")
def discover(org: str | None, prefix: str | None) -> None:
    """Discover platform repositories in a GitHub organisation.

    If run inside a Foundry project (with foundry.json), reads the
    organisation, prefix, and repository name from the manifest.

    Otherwise, --org and --prefix must be supplied.
    """
    state = detect_project_state()
    manifest = None
    main_repo: str | None = None

    if state.has_manifest:
        try:
            manifest = load_manifest_from_path(state.manifest_path)
            eco = manifest.ecosystem
            if eco:
                if not org:
                    org = eco.organization
                if not prefix:
                    prefix = eco.prefix
            if not prefix:
                prefix = manifest.prefix
            main_repo = manifest.repository
        except Exception:
            pass

    if not org:
        raise click.ClickException(
            "No organisation specified.\n"
            "  Either run from a project with ecosystem.organization in foundry.json,\n"
            "  or pass --org <github-org>."
        )

    if not prefix and not main_repo:
        raise click.ClickException(
            "Cannot determine platform prefix or repository name.\n"
            "  Ensure foundry.json has a 'name' field, or pass --prefix."
        )

    resolved = resolve_token()
    if not resolved.found:
        _print_github_setup()
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

    try:
        org_info = get_org(org, resolved.token)
    except FoundryError as exc:
        raise click.ClickException(str(exc))

    click.echo(
        f"  {click.style('✓', fg='green', bold=True)} "
        f"Organisation: {click.style(org_info.login, fg='green')} "
        f"— {org_info.name or '(no display name)'}"
    )

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
# Toolchain status display
# ------------------------------------------------------------------

def _show_toolchain_status() -> None:
    """Print the status of all external tools Foundry relies on."""
    click.echo()
    click.echo(click.style("  ╔══════════════════════════════════════════════╗", fg="cyan"))
    click.echo(click.style("  ║         Foundry Toolchain Status            ║", fg="cyan"))
    click.echo(click.style("  ╚══════════════════════════════════════════════╝", fg="cyan"))
    click.echo()

    # ── AWS CLI ──
    click.echo(click.style("  AWS CLI", fg="cyan", bold=True))
    try:
        from foundry_cli.core.aws import detect_aws_credentials
        status = detect_aws_credentials()
        if status.authenticated:
            click.echo(f"    {click.style('✓', fg='green', bold=True)} Authenticated")
            click.echo(f"    Account: {click.style(status.account_id, fg='green')}")
            click.echo(f"    Identity: {click.style(status.arn, fg='white')}")
        else:
            click.echo(f"    {click.style('✗', fg='red', bold=True)} Not authenticated")
            click.echo(f"    Run: {click.style('aws configure', fg='yellow')} or {click.style('aws sso login', fg='yellow')}")
    except Exception as exc:
        click.echo(f"    {click.style('✗', fg='red', bold=True)} Error: {exc}")
    click.echo()

    # ── GitHub CLI ──
    click.echo(click.style("  GitHub CLI", fg="cyan", bold=True))
    try:
        from foundry_cli.core.github import detect_github_credentials
        gh_status = detect_github_credentials()
        if gh_status.authenticated:
            click.echo(f"    {click.style('✓', fg='green', bold=True)} Authenticated via {click.style(gh_status.source, fg='cyan')}")
            display = gh_status.name or gh_status.login or "unknown"
            click.echo(f"    User: {click.style(display, fg='green')} ({gh_status.login})")
        else:
            click.echo(f"    {click.style('✗', fg='red', bold=True)} Not authenticated")
            click.echo(f"    Run: {click.style('gh auth login', fg='yellow')}")
    except Exception as exc:
        click.echo(f"    {click.style('✗', fg='red', bold=True)} Error: {exc}")
    click.echo()

    # ── OpenTofu ──
    click.echo(click.style("  OpenTofu", fg="cyan", bold=True))
    tofu_version = _detect_tofu_version()
    if tofu_version:
        click.echo(f"    {click.style('✓', fg='green', bold=True)} {click.style(tofu_version, fg='green')}")
    else:
        click.echo(f"    {click.style('—', fg='yellow')} Not installed (optional)")
        click.echo(f"    Install: {click.style('https://opentofu.org/docs/intro/install', fg='yellow')}")
    click.echo()

    # ── Project context ──
    state = detect_project_state()
    click.echo(click.style("  Project", fg="cyan", bold=True))
    if state.has_manifest:
        try:
            manifest = load_manifest_from_path(state.manifest_path)
            click.echo(f"    {click.style('✓', fg='green', bold=True)} {click.style(manifest.name or 'unnamed', fg='green')}")
            if manifest.prefix:
                click.echo(f"    Prefix: {click.style(manifest.prefix, fg='cyan')}")
            envs = manifest.environments
            enabled = [n for n, c in envs.items() if c.enabled]
            if enabled:
                click.echo(f"    Environments: {click.style(', '.join(enabled), fg='cyan')}")
        except Exception:
            click.echo(f"    {click.style('✓', fg='green', bold=True)} foundry.json found")
    else:
        click.echo(f"    {click.style('—', fg='yellow')} No foundry.json in current directory")
    click.echo()


def _detect_tofu_version() -> str | None:
    """Detect OpenTofu version, if installed."""
    try:
        result = subprocess.run(
            ["tofu", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


# ------------------------------------------------------------------
# Setup instructions
# ------------------------------------------------------------------

def _print_github_setup() -> None:
    """Print user-friendly instructions for setting up GitHub access."""
    click.echo()
    click.echo(click.style("  ╔══════════════════════════════════════════════╗", fg="yellow"))
    click.echo(click.style("  ║  GitHub Authentication Required             ║", fg="yellow"))
    click.echo(click.style("  ╚══════════════════════════════════════════════╝", fg="yellow"))
    click.echo()
    click.echo("  Foundry reads your existing GitHub CLI credentials.")
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
