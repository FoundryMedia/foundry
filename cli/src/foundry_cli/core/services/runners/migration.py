"""Migration-aware runner that runs Liquibase before starting a service.

When ``--migrate-db`` is passed, this runner wraps the inner service runner:

1. Resolves database credentials (AWS Secrets Manager or env vars)
2. Runs ``liquibase update`` against the configured changelog
3. Starts the inner service only after migration succeeds

This runner integrates with ``TunnelAwareRunner`` — the wrapping order is:

    TunnelAwareRunner(                    # 1. SSH tunnel established
        MigrationAwareRunner(             # 2. Liquibase runs
            SpringBootServiceRunner(...)  # 3. Service starts
        )
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, AsyncIterator

from foundry_cli.core.project.manifest import DatabaseConfig
from foundry_cli.core.services.runners.base import (
    ServiceLogEvent,
    ServiceRunner,
    ServiceStatus,
    ServiceStatusEvent,
)

logger = logging.getLogger(__name__)


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


class MigrationAwareRunner(ServiceRunner):
    """Wraps a service runner with Liquibase migration support.

    The migration is run before the service starts. If it fails, the
    service is NOT started and the runner emits a ``failed`` status.
    """

    def __init__(
        self,
        inner_runner: ServiceRunner,
        db_config: DatabaseConfig,
        workspace_root: Path,
        *,
        tunnel_local_port: int | None = None,
    ) -> None:
        # Don't call super().__init__ — we're wrapping another runner
        self._inner = inner_runner
        self._db_config = db_config
        self._workspace_root = workspace_root
        self._tunnel_local_port = tunnel_local_port

        self._inner_log_task: asyncio.Task | None = None
        self._inner_status_task: asyncio.Task | None = None
        self._combined_log_queue: asyncio.Queue[ServiceLogEvent] = asyncio.Queue()
        self._combined_status_queue: asyncio.Queue[ServiceStatusEvent] = asyncio.Queue()

    # ── ServiceRunner interface ──────────────────────────────────────

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def display_name(self) -> str:
        return self._inner.display_name

    @property
    def cwd(self) -> Path:
        return self._inner.cwd

    @property
    def service(self):
        return self._inner.service

    async def start(self) -> None:
        """Run migration, then start the inner service."""
        await self._emit_status(
            ServiceStatus.starting,
            detail="Running database migration...",
        )

        try:
            success = await self._run_migration()
        except Exception as exc:
            await self._log(f"[migration] Unexpected error: {exc}", "ERROR")
            await self._emit_status(
                ServiceStatus.failed,
                detail="Database migration failed",
                error=str(exc),
            )
            return

        if not success:
            await self._emit_status(
                ServiceStatus.failed,
                detail="Database migration failed — service not started",
                error="Liquibase update returned a non-zero exit code. Check logs above.",
            )
            return

        await self._log("[migration] Database migration completed successfully", "INFO")
        await self._emit_status(
            ServiceStatus.starting,
            detail="Migration complete, starting service...",
        )

        # Forward inner runner events before starting it
        self._inner_log_task = asyncio.create_task(self._forward_inner_logs())
        self._inner_status_task = asyncio.create_task(self._forward_inner_status())

        await self._inner.start()

    async def stop(self) -> None:
        """Stop the inner service."""
        if self._inner_log_task:
            self._inner_log_task.cancel()
        if self._inner_status_task:
            self._inner_status_task.cancel()
        await self._inner.stop()

    def events(self) -> AsyncIterator[ServiceLogEvent]:
        async def _gen() -> AsyncIterator[ServiceLogEvent]:
            while True:
                yield await self._combined_log_queue.get()
        return _gen()

    def status_events(self) -> AsyncIterator[ServiceStatusEvent]:
        async def _gen() -> AsyncIterator[ServiceStatusEvent]:
            while True:
                yield await self._combined_status_queue.get()
        return _gen()

    # ── Migration logic ──────────────────────────────────────────────

    async def _run_migration(self) -> bool:
        """Execute Liquibase against the configured database.

        Credential resolution order:
        1. AWS Secrets Manager (if ``credentials_secret_id`` is set)
        2. Environment variables (``DB_HOST``, ``DB_USERNAME``, etc.)
        3. Defaults from ``liquibase.properties``

        Returns True if migration succeeded.
        """

        liquibase_bin = shutil.which("liquibase")
        if not liquibase_bin:
            await self._log(
                "[migration] Liquibase CLI not found on PATH. "
                "Install it: https://docs.liquibase.com/start/install/home.html",
                "ERROR",
            )
            return False

        cfg = self._db_config
        changelog = cfg.changelog
        properties = cfg.properties_path
        engine = cfg.engine

        if not changelog:
            await self._log("[migration] No changelog path configured — skipping", "WARN")
            return True

        # Resolve absolute paths from workspace root
        changelog_abs = self._workspace_root / changelog
        if not changelog_abs.exists():
            await self._log(
                f"[migration] Changelog not found: {changelog_abs}",
                "ERROR",
            )
            return False

        await self._log(f"[migration] Engine: {engine}", "DEBUG")
        await self._log(f"[migration] Changelog: {changelog}", "INFO")

        # Build the Liquibase command — use resolved path so .bat/.cmd
        # wrappers work on Windows without shell=True.
        # --log-level=OFF suppresses Liquibase's timestamped stderr
        # output which duplicates the clean stdout output.
        args = [liquibase_bin, "--log-level=OFF"]

        if properties:
            properties_abs = self._workspace_root / properties
            if properties_abs.exists():
                args.append(f"--defaults-file={properties_abs}")
                await self._log(f"[migration] Properties: {properties}", "DEBUG")
            else:
                await self._log(
                    f"[migration] Properties file not found: {properties_abs} — using CLI args only",
                    "WARN",
                )

        # Liquibase expects a path relative to its search-path (cwd).
        args.append(f"--changelog-file={changelog}")

        # Resolve credentials — passed via env vars to avoid cmd.exe
        # mangling special characters in passwords on Windows.
        cred_overrides = await self._resolve_credentials()
        env_overrides: dict[str, str] = {}

        # Map credential keys to Liquibase env var names
        _ENV_MAP = {
            "url": "LIQUIBASE_COMMAND_URL",
            "username": "LIQUIBASE_COMMAND_USERNAME",
            "password": "LIQUIBASE_COMMAND_PASSWORD",
            "default-schema-name": "LIQUIBASE_COMMAND_DEFAULT_SCHEMA_NAME",
        }
        for key, value in cred_overrides.items():
            env_name = _ENV_MAP.get(key)
            if env_name:
                env_overrides[env_name] = str(value)
            else:
                # Unknown keys go as CLI args (safe ones without special chars)
                args.append(f"--{key}={value}")

        args.append("update")

        # Run Liquibase as a subprocess
        await self._log("[migration] Running: liquibase ... update", "INFO")

        # Run in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        exit_code = await loop.run_in_executor(
            None, self._execute_liquibase, args, env_overrides,
        )

        return exit_code == 0

    def _execute_liquibase(self, args: list[str], env_overrides: dict[str, str] | None = None) -> int:
        """Synchronous Liquibase execution — runs in a thread."""
        import os

        # Build env: inherit current env + credential overrides
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(self._workspace_root),
                env=env,
            )

            # Stream output line by line
            for line in iter(process.stdout.readline, ""):  # type: ignore[union-attr]
                stripped = line.rstrip()
                if not stripped:
                    continue
                # Queue log event (will be picked up by event loop).
                # Use INFO so output is visible without --debug.
                self._combined_log_queue.put_nowait(
                    ServiceLogEvent(
                        service_name=self.name,
                        stream="stdout",
                        line=f"[liquibase] {stripped}",
                        level="INFO",
                    )
                )

            process.wait()
            return process.returncode

        except FileNotFoundError:
            self._combined_log_queue.put_nowait(
                ServiceLogEvent(
                    service_name=self.name,
                    stream="stderr",
                    line="[migration] liquibase command not found",
                    level="ERROR",
                )
            )
            return 1
        except Exception as exc:
            self._combined_log_queue.put_nowait(
                ServiceLogEvent(
                    service_name=self.name,
                    stream="stderr",
                    line=f"[migration] Error: {exc}",
                    level="ERROR",
                )
            )
            return 1

    async def _resolve_credentials(self) -> dict[str, str]:
        """Resolve database credentials for Liquibase.

        Tries AWS Secrets Manager first (if configured), then falls back
        to environment variables.
        """
        cfg = self._db_config
        overrides: dict[str, str] = {}

        # 1. Try AWS Secrets Manager
        if cfg.credentials_secret_id:
            try:
                creds = await self._fetch_aws_credentials(cfg.credentials_secret_id)
                if creds:
                    host = creds.get("host", "localhost")
                    port = creds.get("port", _DEFAULT_PORTS.get(cfg.engine, 5432))
                    dbname = creds.get("dbname", "")

                    # Apply tunnel override — use localhost + tunnel port.
                    # For MariaDB/MySQL, use trust SSL mode since the SSH
                    # tunnel already encrypts the connection but RDS may
                    # enforce require_secure_transport. PostgreSQL RDS
                    # requires encryption (pg_hba.conf) even through a
                    # tunnel, so leave its default SSL negotiation intact.
                    ssl_params = ""
                    if self._tunnel_local_port:
                        host = "localhost"
                        port = self._tunnel_local_port
                        if cfg.engine in ("mariadb", "mysql"):
                            ssl_params = "?sslMode=trust"

                    template = _JDBC_TEMPLATES.get(cfg.engine)
                    if template:
                        overrides["url"] = template.format(
                            host=host, port=port, dbname=dbname,
                        ) + ssl_params

                    if creds.get("username"):
                        overrides["username"] = creds["username"]
                    if creds.get("password"):
                        overrides["password"] = creds["password"]

                    # Pass schema as a separate CLI arg rather than
                    # appending to the URL — avoids '&' in args which
                    # cmd.exe interprets as a command separator on Windows.
                    if cfg.schema:
                        overrides["default-schema-name"] = cfg.schema

                    await self._log(
                        f"[migration] Credentials resolved from AWS Secrets Manager: {cfg.credentials_secret_id}",
                        "INFO",
                    )
                    return overrides

            except Exception as exc:
                await self._log(
                    f"[migration] AWS Secrets Manager lookup failed: {exc}. "
                    "Falling back to environment variables / properties file.",
                    "WARN",
                )

        # 2. No secret configured — rely on env vars in liquibase.properties
        # The properties file uses ${DB_HOST}, ${DB_USERNAME}, ${DB_PASSWORD}
        await self._log(
            "[migration] No credentials secret configured — "
            "using liquibase.properties defaults / env vars",
            "DEBUG",
        )
        return overrides

    async def _fetch_aws_credentials(
        self, secret_id: str,
    ) -> dict[str, Any] | None:
        """Fetch database credentials from AWS Secrets Manager.

        Uses the ``aws`` CLI (via foundry_cli.core.aws) so credential
        resolution inherits the developer's AWS configuration.
        """
        from foundry_cli.core.aws import get_secret_json

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, get_secret_json, secret_id)

    # ── Helpers ──────────────────────────────────────────────────────

    async def _log(self, message: str, level: str = "DEBUG") -> None:
        await self._combined_log_queue.put(
            ServiceLogEvent(
                service_name=self.name,
                stream="stdout",
                line=message,
                level=level,
            )
        )

    async def _emit_status(
        self,
        status: ServiceStatus,
        detail: str = "",
        error: str | None = None,
    ) -> None:
        await self._combined_status_queue.put(
            ServiceStatusEvent(
                self.name,
                status,
                detail=detail,
                error=error,
                level="ERROR" if error else "INFO",
            )
        )

    async def _forward_inner_logs(self) -> None:
        try:
            async for event in self._inner.events():
                await self._combined_log_queue.put(event)
        except asyncio.CancelledError:
            pass

    async def _forward_inner_status(self) -> None:
        try:
            async for event in self._inner.status_events():
                await self._combined_status_queue.put(event)
        except asyncio.CancelledError:
            pass


__all__ = ["MigrationAwareRunner"]
