"""``foundry init`` — Initialize or refresh a Foundry platform.

Detects the current project state and either:

- Creates a new platform scaffold (fresh init with interactive wizard)
- Generates/regenerates ``.foundry/`` configuration files (existing projects)
- Upgrades a legacy project (adds ``.foundry/`` to a manifest-only project)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import click

from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project.dotfoundry import (
    FoundryProjectState,
    detect_project_state,
    ensure_foundry_dir,
    ensure_gitignore_entry,
)

KEBAB_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

DEFAULT_SCHEMA_VERSION = "0.5.0"
SCHEMA_URL = (
    "https://raw.githubusercontent.com/FoundryMedia/foundry/release/"
    "foundry.schema.json"
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_platform_name(name: str) -> str:
    """Validate that *name* is kebab-case."""
    if not KEBAB_CASE_PATTERN.match(name):
        raise FoundryError(
            f"Invalid platform name '{name}'. "
            "Must be kebab-case (e.g., 'my-platform')."
        )
    return name


def _derive_platform_name(directory: Path) -> str:
    """Derive a platform name from a directory, lowercased."""
    candidate = directory.name.lower()
    if not KEBAB_CASE_PATTERN.match(candidate):
        raise FoundryError(
            f"Could not derive a valid platform name from directory '{directory.name}'.\n"
            "Use --name to specify one (kebab-case, e.g., 'my-platform')."
        )
    return candidate


# ---------------------------------------------------------------------------
# Manifest creation
# ---------------------------------------------------------------------------

def _create_manifest(
    root: Path,
    name: str,
    *,
    provider: str = "aws",
    iac: str = "opentofu",
    services: dict[str, dict[str, str]] | None = None,
) -> Path:
    """Write a ``foundry.json`` manifest to *root*.

    Returns the path to the created file.
    """
    manifest: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "schemaVersion": DEFAULT_SCHEMA_VERSION,
        "name": name,
        "repository": name,
        "ci": {
            "iac": iac,
            "iacDir": "ci/iac",
            "provider": provider,
        },
        "services": services or {},
    }

    path = root / "foundry.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Shared: generate .foundry/ configuration files
# ---------------------------------------------------------------------------

def _generate_foundry_files(
    root: Path,
    manifest_path: Path,
    foundry_dir: Path,
    *,
    force: bool = False,
) -> tuple[int, int, int]:
    """Generate ``.foundry/workspace.yml`` via sync.

    Returns:
        ``(service_count, undeclared_count, missing_count)``
    """
    from foundry_cli.core.project.manifest import load_manifest_from_path
    from foundry_cli.core.project.workspace_config import (
        load_workspace_yml,
        resolve_workspace,
        save_workspace_yml,
    )

    manifest = load_manifest_from_path(manifest_path)

    # --- workspace.yml ---
    existing_ws = load_workspace_yml(foundry_dir)
    if existing_ws and not force:
        svc_count = len(existing_ws.get("services", {}))
        click.echo(click.style(
            f"  • workspace.yml exists ({svc_count} services) — "
            "use --force or run 'foundry sync' to regenerate",
            fg="yellow",
        ))
    else:
        ws_data = resolve_workspace(root, manifest)
        save_workspace_yml(ws_data, foundry_dir)
        svc_count = len(ws_data.get("services", {}))
        click.echo(click.style(
            f"  ✓ .foundry/workspace.yml  ({svc_count} services resolved)",
            fg="green",
        ))

    # Read back drift from workspace
    ws_data = load_workspace_yml(foundry_dir) or {}
    drift = ws_data.get("drift", {})
    undeclared = len(drift.get("undeclared", {}))
    missing = len(drift.get("missing", []))

    drift_parts: list[str] = []
    if undeclared:
        drift_parts.append(f"{undeclared} undeclared")
    if missing:
        drift_parts.append(f"{missing} missing")

    if drift_parts:
        click.echo(click.style(
            f"  ⚠ Drift: {', '.join(drift_parts)}",
            fg="yellow",
        ))

    return svc_count, undeclared, missing


def _display_drift(foundry_dir: Path) -> None:
    """Display drift information from ``workspace.yml``."""
    from foundry_cli.core.project.workspace_config import load_workspace_yml

    ws_data = load_workspace_yml(foundry_dir)
    if not ws_data:
        return

    drift = ws_data.get("drift", {})
    undeclared = drift.get("undeclared", {})
    missing = drift.get("missing", [])

    if not undeclared and not missing:
        return

    click.echo()
    click.echo(click.style("Drift detected:", fg="yellow", bold=True))

    if undeclared:
        click.echo(click.style("  Undeclared (on disk, not in manifest):", fg="yellow"))
        for name, info in undeclared.items():
            kind = info.get("kind", "?")
            rel_path = info.get("path", "?")
            click.echo(
                f"    {click.style(name, fg='cyan')}  "
                f"{click.style(kind, fg='white')}  {rel_path}"
            )

    if missing:
        click.echo(click.style("  Missing (in manifest, not on disk):", fg="red"))
        for name in missing:
            click.echo(f"    {click.style(name, fg='cyan')}")

    click.echo()
    click.echo(click.style("  Run 'foundry sync' to reconcile.", fg="white"))


# ---------------------------------------------------------------------------
# Handler: already initialized
# ---------------------------------------------------------------------------

def _handle_existing(
    state: FoundryProjectState,
    *,
    force: bool = False,
) -> None:
    """Show project summary and regenerate ``.foundry/`` config files."""
    from foundry_cli.core.project.manifest import load_manifest_from_path

    manifest = load_manifest_from_path(state.manifest_path)
    name = manifest.name or state.root.name
    version = manifest.data.get("schemaVersion", "?")

    click.echo(click.style(f"Foundry project: {name}", fg="green", bold=True))
    click.echo(click.style(f"  Root:   {state.root}", fg="white"))
    click.echo(click.style(f"  Schema: v{version}", fg="white"))
    click.echo()

    # Show declared services from manifest
    svcs = manifest.services_config
    if svcs:
        click.echo(click.style("Services:", fg="yellow", bold=True))
        for svc_name, cfg in svcs.items():
            kind_color = "magenta" if cfg.kind == "backend" else (
                "cyan" if cfg.kind == "frontend" else "blue"
            )
            click.echo(
                f"  {click.style(svc_name, fg='cyan'):30s} "
                f"{click.style(cfg.kind or '?', fg=kind_color):12s} "
                f"{click.style(cfg.type or '?', fg='white'):15s} "
                f"{click.style(cfg.role or '?', fg='blue')}"
            )
    else:
        click.echo(click.style("  No services declared.", fg="yellow"))

    click.echo()

    # Ensure .foundry/ structure is complete
    foundry_dir = ensure_foundry_dir(state.root)
    modified = ensure_gitignore_entry(state.root)

    # Generate runtime + state
    click.echo(click.style("Generating:", fg="yellow", bold=True))
    _generate_foundry_files(
        state.root,
        state.manifest_path,
        foundry_dir,
        force=force,
    )

    # Show drift summary
    _display_drift(foundry_dir)


# ---------------------------------------------------------------------------
# Handler: upgrade (manifest exists, no .foundry/)
# ---------------------------------------------------------------------------

def _handle_upgrade(
    state: FoundryProjectState,
    *,
    dry_run: bool = False,
) -> None:
    """Create ``.foundry/`` and generate config files for an existing manifest."""
    click.echo(click.style(
        "Found existing foundry.json — setting up .foundry/ directory.",
        fg="yellow",
    ))
    click.echo()

    if dry_run:
        click.echo(click.style("  [dry-run] Would create .foundry/", fg="cyan"))
        click.echo(click.style("  [dry-run] Would generate .foundry/workspace.yml", fg="cyan"))
        click.echo(click.style("  [dry-run] Would update .gitignore", fg="cyan"))
        return

    foundry_dir = ensure_foundry_dir(state.root)
    click.echo(click.style(
        f"  ✓ {foundry_dir.relative_to(state.root)}/",
        fg="green",
    ))

    modified = ensure_gitignore_entry(state.root)
    if modified:
        click.echo(click.style("  ✓ .gitignore updated", fg="green"))

    # Generate runtime + state
    _generate_foundry_files(
        state.root,
        state.manifest_path,
        foundry_dir,
        force=True,
    )

    click.echo()
    click.echo(click.style("Foundry project configured.", fg="green", bold=True))
    _display_drift(foundry_dir)


# ---------------------------------------------------------------------------
# Handler: fresh init (interactive wizard)
# ---------------------------------------------------------------------------

_ROLE_HINTS: dict[str, str] = {
    "auth": "auth", "microlith": "microlith", "platform": "microlith",
    "api": "microlith", "hub": "hub",
    "public": "public", "status": "status", "nlp": "internal",
    "ml": "internal", "internal": "internal",
    "worker": "worker", "queue": "worker", "gateway": "gateway",
}

_SCOPE_HINTS: dict[str, str] = {
    "public": "public", "web": "public", "status": "public", "landing": "public",
    "hub": "internal", "admin": "internal", "dashboard": "internal",
    "auth": "internal", "microlith": "internal", "platform": "internal",
    "api": "internal", "nlp": "internal", "ml": "internal",
    "worker": "internal", "queue": "internal", "gateway": "internal",
}


def _guess_role(name: str) -> str:
    """Guess a service role from its directory name."""
    lower = name.lower()
    for fragment, role in _ROLE_HINTS.items():
        if fragment in lower:
            return role
    return "other"


def _guess_scope(name: str) -> str | None:
    """Guess a service scope (public/internal) from its name."""
    lower = name.lower()
    for fragment, scope in _SCOPE_HINTS.items():
        if fragment in lower:
            return scope
    return None


def _handle_fresh_init(
    root: Path,
    name: str,
    template: str | None,
    dry_run: bool,
) -> None:
    """Full init: discover services, prompt for config, create everything."""
    if template is not None and template != "default":
        click.echo(click.style(
            f"Template '{template}' — template scaffolding is not yet implemented.\n"
            "Using default scaffold.",
            fg="yellow",
        ))

    click.echo(click.style(
        f"Initializing Foundry platform: {name}",
        fg="blue", bold=True,
    ))
    click.echo()

    # --- Step 1: Discover existing services on filesystem ---
    from foundry_cli.core.project.workspace_config import scan_filesystem

    discovered = scan_filesystem(root)
    services: dict[str, dict[str, str]] = {}

    if discovered:
        click.echo(click.style(
            f"Discovered {len(discovered)} component(s) on filesystem:",
            fg="yellow",
        ))
        for svc_name, info in discovered.items():
            rt = info["detectedRuntime"]
            if rt == "fastapi":
                rt = "uvicorn"
            kind_color = (
                "magenta" if info["kind"] == "backend"
                else "cyan" if info["kind"] == "frontend"
                else "blue"
            )
            click.echo(
                f"  {click.style(svc_name, fg='cyan'):30s} "
                f"{click.style(info['kind'], fg=kind_color):12s} "
                f"{click.style(rt, fg='white'):15s} "
                f"{click.style(info['evidence'], fg='bright_black')}"
            )
        click.echo()

        if click.confirm("Add discovered components to manifest?", default=True):
            for svc_name, info in discovered.items():
                rt = info["detectedRuntime"]
                if rt == "fastapi":
                    rt = "uvicorn"
                kind = info["kind"]
                framework = rt if rt != "unknown" else None

                svc_entry: dict[str, Any] = {
                    "stack": {"type": kind},
                }
                if framework:
                    svc_entry["stack"]["framework"] = framework

                # Infer scope from name
                scope = _guess_scope(svc_name)
                if scope:
                    svc_entry["scope"] = scope

                # Only add deploy block for non-packages
                if kind != "package":
                    svc_entry["deploy"] = {"strategy": "service" if kind == "backend" else "static"}

                services[svc_name] = svc_entry
    else:
        click.echo(click.style("No existing services found on filesystem.", fg="white"))
        click.echo()

    # --- Step 2: Infrastructure config ---
    provider = click.prompt(
        "  Cloud provider",
        type=click.Choice(["aws", "gcp", "azure", "other"], case_sensitive=False),
        default="aws",
    )
    iac = click.prompt(
        "  IaC tool",
        type=click.Choice(
            ["opentofu", "terraform", "pulumi", "cloudformation", "other"],
            case_sensitive=False,
        ),
        default="opentofu",
    )
    click.echo()

    # --- Step 3: Dry-run preview ---
    if dry_run:
        click.echo(click.style("  [dry-run] Would create:", fg="cyan"))
        click.echo(click.style("    foundry.json", fg="cyan"))
        click.echo(click.style("    .foundry/", fg="cyan"))
        click.echo(click.style("    .foundry/workspace.yml", fg="cyan"))
        click.echo(click.style("    .gitignore (updated)", fg="cyan"))
        return

    # --- Step 4: Create everything ---
    click.echo(click.style("Creating:", fg="yellow", bold=True))

    # Manifest
    manifest_path = _create_manifest(
        root, name,
        provider=provider,
        iac=iac,
        services=services,
    )
    click.echo(click.style(f"  ✓ {manifest_path.name}", fg="green"))

    # .foundry/
    foundry_dir = ensure_foundry_dir(root)
    click.echo(click.style(
        f"  ✓ {foundry_dir.relative_to(root)}/",
        fg="green",
    ))

    # .gitignore
    modified = ensure_gitignore_entry(root)
    if modified:
        click.echo(click.style("  ✓ .gitignore updated", fg="green"))

    # Generate runtime + state
    _generate_foundry_files(root, manifest_path, foundry_dir, force=True)

    click.echo()
    click.echo(click.style(f"Platform '{name}' initialized.", fg="green", bold=True))
    click.echo()
    click.echo(click.style("Next steps:", fg="yellow"))
    if not services:
        click.echo(click.style("  1. Add services to apps/backend/ and apps/frontend/", fg="white"))
        click.echo(click.style("  2. Configure services in foundry.json", fg="white"))
        click.echo(click.style("  3. Run 'foundry sync' to update workspace state", fg="white"))
    else:
        click.echo(click.style("  1. Review foundry.json and adjust service config", fg="white"))
        click.echo(click.style("  2. Run 'foundry sync' to verify workspace state", fg="white"))
        click.echo(click.style("  3. Run 'foundry run dev' to start local development", fg="white"))


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------

@click.command()
@click.option(
    "--name", "-n", default=None,
    help="Platform name (kebab-case). Defaults to current directory name.",
)
@click.option(
    "--template", "-t", default=None,
    help="Template to use for scaffolding.",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Show what would be created without writing any files.",
)
@click.option(
    "--force", "-f", is_flag=True, default=False,
    help="Force regeneration of .foundry/workspace.yml even if it already exists.",
)
@click.pass_context
def init(
    ctx: click.Context,
    name: str | None,
    template: str | None,
    dry_run: bool,
    force: bool,
) -> None:
    """Initialize or refresh a Foundry platform in the current directory."""
    try:
        _run_init(
            name=name,
            template=template,
            dry_run=dry_run,
            force=force,
        )
    except FoundryError as e:
        click.echo(
            click.style("Error: ", fg="red", bold=True)
            + click.style(str(e), fg="red")
        )
        raise SystemExit(1)


def _run_init(
    *,
    name: str | None,
    template: str | None,
    dry_run: bool,
    force: bool = False,
) -> None:
    """Core init logic, separated from the Click handler for testability."""
    cwd = Path.cwd()
    state = detect_project_state(cwd)

    # Already fully initialized — show project status + regenerate
    if state.is_initialized:
        _handle_existing(state, force=force)
        return

    # Orphaned .foundry/ without a manifest (neither .foundry/foundry.json
    # nor a root foundry.json exists)
    if state.is_orphaned:
        raise FoundryError(
            "Found a .foundry/ directory but no manifest at "
            f"{state.root}.\n"
            "Expected .foundry/foundry.json (multi-repo layout) or a "
            "root-level foundry.json. Create one, or remove .foundry/ to "
            "start fresh."
        )

    # Existing manifest, missing .foundry/ — upgrade path
    if state.needs_upgrade:
        _handle_upgrade(state, dry_run=dry_run)
        return

    # Fresh init — nothing exists
    if name is None:
        name = _derive_platform_name(cwd)
    name = _validate_platform_name(name)

    _handle_fresh_init(cwd, name, template, dry_run)
