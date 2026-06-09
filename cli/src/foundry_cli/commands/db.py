"""``foundry db`` — Database management commands.

Standalone Liquibase operations with automatic SSH tunnel and credential
resolution.  No service startup required — just database operations.

Examples::

    foundry db migrate                          # Run migrations for all databases
    foundry db migrate --filter microlith       # Migrate a specific database
    foundry db changelog-sync                   # Mark all pending changesets as executed
    foundry db changelog-sync --filter auth-efga
    foundry db status                           # Show pending changeset count
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from foundry_cli.core.cli import FoundryGroup
from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project.manifest import (
    DatabaseConfig,
    ProjectManifest,
    load_manifest_from_path,
)
from foundry_cli.core.project.workspace import find_manifest_path


# JDBC URL templates per engine
_JDBC_TEMPLATES: dict[str, str] = {
    "mariadb": "jdbc:mariadb://{host}:{port}/{dbname}",
    "mysql": "jdbc:mysql://{host}:{port}/{dbname}",
    "postgresql": "jdbc:postgresql://{host}:{port}/{dbname}",
    "postgres": "jdbc:postgresql://{host}:{port}/{dbname}",
}

# Default ports per engine
_DEFAULT_PORTS: dict[str, int] = {
    "mariadb": 3306,
    "mysql": 3306,
    "postgresql": 5432,
    "postgres": 5432,
}


# ── SSH tunnel helpers ───────────────────────────────────────────────


def _is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _open_tunnel(tunnel_cfg: dict[str, Any], workspace_root: Path):
    """Open an SSH tunnel synchronously.  Returns the SSHTunnelForwarder instance."""
    from sshtunnel import SSHTunnelForwarder

    local_port = tunnel_cfg["localPort"]
    remote_host = os.path.expandvars(tunnel_cfg["remoteHost"])
    remote_port = tunnel_cfg["remotePort"]
    host = os.path.expandvars(tunnel_cfg["host"])
    user = os.path.expandvars(tunnel_cfg.get("user", "ec2-user"))
    key_path_raw = tunnel_cfg.get("password")

    # Check if tunnel is already up
    if _is_port_open("127.0.0.1", local_port, timeout=0.5):
        click.echo(click.style(
            f"  Port {local_port} already open — tunnel may already be active",
            fg="yellow",
        ))
        return None

    # Resolve key file
    key_path = None
    if key_path_raw:
        expanded = os.path.expandvars(key_path_raw)
        p = Path(expanded)
        if p.is_absolute() and p.exists():
            key_path = str(p)
        else:
            resolved = workspace_root / p
            if resolved.exists():
                key_path = str(resolved)
            else:
                raise FoundryError(f"SSH key file not found: {key_path_raw}")

    click.echo(click.style(f"  Connecting to {host}...", fg="cyan"))

    tunnel = SSHTunnelForwarder(
        (host, 22),
        ssh_username=user,
        ssh_pkey=key_path,
        remote_bind_address=(remote_host, remote_port),
        local_bind_address=("0.0.0.0", local_port),
        set_keepalive=30.0,
    )
    tunnel.start()

    if not tunnel.is_active:
        raise FoundryError("SSH tunnel failed to start")

    click.echo(click.style(
        f"  Tunnel established (localhost:{local_port} → {remote_host}:{remote_port})",
        fg="green",
    ))
    return tunnel


# ── Credential resolution ────────────────────────────────────────────


def _resolve_credentials(
    db_config: DatabaseConfig,
    tunnel_local_port: int | None = None,
) -> dict[str, str]:
    """Resolve database credentials from AWS Secrets Manager or defaults."""
    overrides: dict[str, str] = {}

    if db_config.credentials_secret_id:
        try:
            from foundry_cli.core.aws import get_secret_json
            creds = get_secret_json(db_config.credentials_secret_id)
        except Exception as exc:
            click.echo(click.style(
                f"  ⚠ AWS Secrets Manager lookup failed: {exc}",
                fg="yellow",
            ))
            click.echo(click.style(
                "  Falling back to liquibase.properties defaults",
                fg="yellow",
            ))
            return overrides

        host = creds.get("host", "localhost")
        port = creds.get("port", _DEFAULT_PORTS.get(db_config.engine, 5432))
        dbname = creds.get("dbname", "")

        # Apply tunnel override
        ssl_params = ""
        if tunnel_local_port:
            host = "localhost"
            port = tunnel_local_port
            if db_config.engine in ("mariadb", "mysql"):
                ssl_params = "?sslMode=trust"

        template = _JDBC_TEMPLATES.get(db_config.engine)
        if template:
            overrides["url"] = template.format(host=host, port=port, dbname=dbname) + ssl_params

        if creds.get("username"):
            overrides["username"] = creds["username"]
        if creds.get("password"):
            overrides["password"] = creds["password"]

        if db_config.schema:
            overrides["default-schema-name"] = db_config.schema

        click.echo(click.style(
            f"  Credentials resolved from: {db_config.credentials_secret_id}",
            fg="green",
        ))

    return overrides


# ── Liquibase execution ──────────────────────────────────────────────


def _run_liquibase(
    db_config: DatabaseConfig,
    workspace_root: Path,
    liquibase_command: str,
    tunnel_local_port: int | None = None,
    extra_args: list[str] | None = None,
) -> bool:
    """Execute a Liquibase command against a database.  Returns True on success."""

    liquibase_bin = shutil.which("liquibase")
    if not liquibase_bin:
        raise FoundryError(
            "Liquibase CLI not found on PATH. "
            "Install it: https://docs.liquibase.com/start/install/home.html"
        )

    changelog = db_config.changelog
    if not changelog:
        click.echo(click.style("  No changelog path configured — skipping", fg="yellow"))
        return True

    changelog_abs = workspace_root / changelog
    if not changelog_abs.exists():
        raise FoundryError(f"Changelog not found: {changelog_abs}")

    # Build command
    args = [liquibase_bin, "--log-level=OFF"]

    if db_config.properties_path:
        properties_abs = workspace_root / db_config.properties_path
        if properties_abs.exists():
            args.append(f"--defaults-file={properties_abs}")

    args.append(f"--changelog-file={changelog}")

    # Resolve credentials via env vars (avoids cmd.exe special char issues)
    cred_overrides = _resolve_credentials(db_config, tunnel_local_port)

    _ENV_MAP = {
        "url": "LIQUIBASE_COMMAND_URL",
        "username": "LIQUIBASE_COMMAND_USERNAME",
        "password": "LIQUIBASE_COMMAND_PASSWORD",
        "default-schema-name": "LIQUIBASE_COMMAND_DEFAULT_SCHEMA_NAME",
    }

    env = os.environ.copy()
    for key, value in cred_overrides.items():
        env_name = _ENV_MAP.get(key)
        if env_name:
            env[env_name] = str(value)
        else:
            args.append(f"--{key}={value}")

    args.append(liquibase_command)

    # Add any extra arguments (e.g., --sql for execute-sql)
    if extra_args:
        args.extend(extra_args)

    click.echo(click.style(f"  Running: liquibase ... {liquibase_command}", fg="cyan"))

    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(workspace_root),
        env=env,
    )

    for line in iter(process.stdout.readline, ""):
        stripped = line.rstrip()
        if stripped:
            click.echo(f"    {stripped}")

    process.wait()
    return process.returncode == 0


# ── Local config loading ─────────────────────────────────────────────


def _load_local_config(foundry_dir: Path) -> dict[str, Any] | None:
    """Load merged .foundry/config.defaults.yml + .foundry/config.yml."""
    try:
        import yaml
    except ImportError:
        return None

    def _load_yaml(path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return raw if isinstance(raw, dict) else None

    def _deep_merge(base: dict, overlay: dict) -> dict:
        merged = dict(base)
        for key, value in overlay.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = _deep_merge(existing, value)
            else:
                merged[key] = value
        return merged

    defaults = _load_yaml(foundry_dir / "config.defaults.yml") or {}
    local = _load_yaml(foundry_dir / "config.yml") or {}

    if not defaults and not local:
        return None

    return _deep_merge(defaults, local)


# ── Main command logic ───────────────────────────────────────────────


def _run_db_command(
    liquibase_command: str,
    filter_svc: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    """Core logic: open tunnels, resolve creds, run Liquibase for each database."""

    manifest_path = find_manifest_path()
    manifest = load_manifest_from_path(manifest_path)
    workspace_root = manifest_path.parent
    foundry_dir = workspace_root / ".foundry"

    # Find all databases in the manifest
    databases = manifest.databases
    if not databases:
        raise FoundryError("No databases configured in foundry.json")

    # Apply filter
    if filter_svc:
        filter_names = {s.strip() for s in filter_svc.split(",") if s.strip()}
        unknown = filter_names - set(databases.keys())
        if unknown:
            available = ", ".join(sorted(databases.keys()))
            raise FoundryError(
                f"Unknown database(s): {', '.join(sorted(unknown))}. "
                f"Available: {available}"
            )
        databases = {k: v for k, v in databases.items() if k in filter_names}

    # Load local config for SSH tunnel configs
    local_cfg = _load_local_config(foundry_dir)
    local_services = (local_cfg or {}).get("services", {})

    # Also read manifest service configs for SSH tunnels defined in foundry.json
    raw_services = manifest.data.get("services", {})

    tunnels = []  # Track opened tunnels for cleanup

    try:
        success_count = 0
        fail_count = 0

        for db_name, db_config in databases.items():
            click.echo()
            click.echo(click.style(
                f"{'=' * 60}",
                fg="blue",
            ))
            click.echo(click.style(
                f"  [db] {db_name}  ({db_config.engine})",
                fg="blue", bold=True,
            ))
            click.echo(click.style(
                f"{'=' * 60}",
                fg="blue",
            ))

            # Resolve SSH tunnel config — local config takes precedence
            tunnel_cfg = None
            tunnel_local_port = None

            local_svc = local_services.get(db_name, {})
            if isinstance(local_svc, dict) and "sshTunnel" in local_svc:
                raw = local_svc["sshTunnel"]
                if isinstance(raw, dict):
                    tunnel_cfg = raw
            elif isinstance(raw_services.get(db_name), dict):
                raw_svc = raw_services[db_name]
                if "sshTunnel" in raw_svc and isinstance(raw_svc["sshTunnel"], dict):
                    tunnel_cfg = raw_svc["sshTunnel"]

            # Open tunnel if configured
            if tunnel_cfg:
                tunnel_local_port = tunnel_cfg.get("localPort")
                try:
                    tunnel = _open_tunnel(tunnel_cfg, workspace_root)
                    if tunnel:
                        tunnels.append(tunnel)
                except Exception as exc:
                    click.echo(click.style(f"  ✗ SSH tunnel failed: {exc}", fg="red"))
                    fail_count += 1
                    continue

            # Run Liquibase
            try:
                ok = _run_liquibase(db_config, workspace_root, liquibase_command, tunnel_local_port, extra_args)
            except Exception as exc:
                click.echo(click.style(f"  ✗ Liquibase failed: {exc}", fg="red"))
                fail_count += 1
                continue

            if ok:
                click.echo(click.style(f"  ✓ {liquibase_command} completed", fg="green", bold=True))
                success_count += 1
            else:
                click.echo(click.style(f"  ✗ {liquibase_command} failed", fg="red", bold=True))
                fail_count += 1

        # Summary
        click.echo()
        if fail_count == 0:
            click.echo(click.style(
                f"✓ All {success_count} database(s) processed successfully",
                fg="green", bold=True,
            ))
        else:
            click.echo(click.style(
                f"✗ {fail_count} failed, {success_count} succeeded",
                fg="red", bold=True,
            ))
            raise SystemExit(1)

    finally:
        # Close all tunnels
        for tunnel in tunnels:
            try:
                tunnel.stop()
            except Exception:
                pass


# ── Click commands ───────────────────────────────────────────────────


def _run_db_command_with_args(
    liquibase_command: str,
    filter_svc: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    """Convenience wrapper that forwards extra_args."""
    _run_db_command(liquibase_command, filter_svc, extra_args)


@click.group(cls=FoundryGroup, short_help="Database management")
def db() -> None:
    """Database management — Liquibase operations with automatic SSH tunnels."""
    pass


@db.command(short_help="Run pending migrations (liquibase update)")
@click.option("--filter", "filter_svc", default=None, help="Comma-separated list of database names to target.")
def migrate(filter_svc: str | None) -> None:
    """Run pending Liquibase migrations (``update``) for all configured databases.

    Opens SSH tunnels automatically if configured in ``.foundry/config.yml``.
    """
    _run_db_command("update", filter_svc)


@db.command("changelog-sync", short_help="Mark pending changesets as executed")
@click.option("--filter", "filter_svc", default=None, help="Comma-separated list of database names to target.")
def changelog_sync(filter_svc: str | None) -> None:
    """Mark all pending changesets as already executed (``changelog-sync``).

    Use this when changesets have been applied manually and Liquibase
    needs to catch up without re-running them.
    """
    click.echo(click.style(
        "⚠ changelog-sync will mark ALL pending changesets as executed without running them.",
        fg="yellow", bold=True,
    ))
    click.echo(click.style(
        "  Use this only if you have already applied the SQL manually.",
        fg="yellow",
    ))
    if not click.confirm("  Continue?", default=False):
        raise SystemExit(0)
    _run_db_command("changelog-sync", filter_svc)


@db.command(short_help="Show pending changeset count")
@click.option("--filter", "filter_svc", default=None, help="Comma-separated list of database names to target.")
def status(filter_svc: str | None) -> None:
    """Show how many changesets are pending (``status``)."""
    _run_db_command("status", filter_svc)


@db.command("changelog-sync-sql", short_help="Preview changelog-sync SQL (dry-run)")
@click.option("--filter", "filter_svc", default=None, help="Comma-separated list of database names to target.")
def changelog_sync_sql(filter_svc: str | None) -> None:
    """Preview the SQL that ``changelog-sync`` would execute (dry-run).

    Outputs INSERT statements for the DATABASECHANGELOG table without
    executing them.
    """
    _run_db_command("changelog-sync-sql", filter_svc)


@db.command("execute-sql", short_help="Run arbitrary SQL against a database")
@click.option("--filter", "filter_svc", required=True, help="Database name to target (required — single database only).")
@click.argument("sql")
def execute_sql(filter_svc: str, sql: str) -> None:
    """Execute arbitrary SQL against a database via Liquibase ``execute-sql``.

    Opens SSH tunnel automatically. Useful for maintenance operations like
    removing entries from DATABASECHANGELOG.

    Examples::

        foundry db execute-sql --filter microlith "SELECT COUNT(*) FROM DATABASECHANGELOG"
        foundry db execute-sql --filter microlith "DELETE FROM DATABASECHANGELOG WHERE ID='43'"
    """
    _run_db_command_with_args("execute-sql", filter_svc, extra_args=["--sql", sql])
