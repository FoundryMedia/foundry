"""Dev-run environment resolution for `foundry run dev`.

The CLI must know a service's effective dev environment BEFORE it starts it,
because the SSH tunnel (and credential injection) can only be decided from it.
This module implements that introspection:

1. **Env stack** (later wins): manifest ``run.env`` → committed
   ``.foundry/dev.env`` → gitignored ``.foundry/dev.local.env``. The process
   environment is consulted only for the explicit ``FOUNDRY_DEV_TARGET``
   override (child processes inherit it anyway).
2. **Target resolution** per service:
   - ``FOUNDRY_DEV_TARGET`` = ``prod`` | ``local`` — explicit wins.
   - Otherwise introspect: DB vars in the stack pointing at the manifest
     tunnel's ``localPort`` (or any non-local host) → ``prod``.
   - Nothing configured → ``local``: no tunnel, the service's own local
     defaults take over (full-local fallback).
3. **prod target** → autowire the tunnel (resolve bastion host by EC2 tag,
   fetch the pem from Secrets Manager if missing) and inject DB env pointed at
   the tunnel, with credentials pulled from the configured secret — into the
   service process only, never written to disk.

Everything AWS-flavored is opt-in manifest config (``bastionTag``,
``keySecret``, ``credentialsSecret``) — a tunnel with a plain host + pem path
keeps working with zero AWS involvement.
"""

from __future__ import annotations

import logging
import os
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project.manifest import SshTunnelConfig
from foundry_cli.core.project.workspace import DiscoveredService

logger = logging.getLogger(__name__)

# Default injected env-var -> credentials-secret field mapping. A manifest's
# sshTunnel.injectEnv extends/overrides this (ENV_VAR -> secret field).
_DEFAULT_CREDS_MAPPING = {
    "DB_NAME": "dbname",
    "DB_USER": "username",
    "DB_PASSWORD": "password",
}

_LOCAL_HOSTS = ("", "localhost", "127.0.0.1", "host.docker.internal")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal dotenv parsing: KEY=VALUE lines, '#' comments, no interpolation."""
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def load_env_files(workspace_root: Path) -> dict[str, str]:
    """The workspace's dev env-file layer (committed defaults, then local)."""
    foundry_dir = workspace_root / ".foundry"
    env: dict[str, str] = {}
    env.update(_parse_env_file(foundry_dir / "dev.env"))
    env.update(_parse_env_file(foundry_dir / "dev.local.env"))
    return env


def resolve_dev_target(
    stack: dict[str, str], tunnels: dict[str, SshTunnelConfig]
) -> str:
    """Decide ``prod`` vs ``local`` for one service from its resolved env stack."""
    explicit = os.environ.get("FOUNDRY_DEV_TARGET") or stack.get("FOUNDRY_DEV_TARGET")
    if explicit:
        explicit = explicit.strip().lower()
        if explicit in ("prod", "local"):
            return explicit
        raise FoundryError(
            f"Invalid FOUNDRY_DEV_TARGET '{explicit}' (expected 'prod' or 'local')."
        )

    if not tunnels:
        return "local"

    # Introspection: does the configured env already point at any tunnel /
    # a remote database? (Heuristic — a multi-tunnel service should set
    # FOUNDRY_DEV_TARGET explicitly in .foundry/dev.env.)
    local_ports = {str(t.local_port) for t in tunnels.values()}
    if stack.get("DB_PORT", "").strip() in local_ports:
        return "prod"
    db_url = stack.get("DB_URL", "")
    if any(port in db_url for port in local_ports):
        return "prod"
    db_host = stack.get("DB_HOST", "").strip().lower()
    if db_host and db_host not in _LOCAL_HOSTS:
        return "prod"

    return "local"


def _autowire_tunnel(tunnel: SshTunnelConfig, workspace_root: Path) -> SshTunnelConfig:
    """Resolve the tunnel's host + key material, using AWS only when configured."""
    host = (tunnel.host or "").strip()
    if not host or "${" in host:
        if not tunnel.bastion_tag:
            raise FoundryError(
                f"SSH tunnel host is unset (got '{tunnel.host or ''}').\n"
                "  Either export the referenced environment variable, or add\n"
                "  'bastionTag' to the sshTunnel block to resolve it by EC2 Name tag."
            )
        from foundry_cli.core.aws import resolve_instance_public_ip

        host = resolve_instance_public_ip(tunnel.bastion_tag, region=tunnel.aws_region)

    if tunnel.password:
        key_path = Path(tunnel.password)
        if not key_path.is_absolute():
            key_path = workspace_root / key_path
        if not key_path.exists() and tunnel.key_secret:
            from foundry_cli.core.aws import get_secret_json

            secret = get_secret_json(tunnel.key_secret, region=tunnel.aws_region)
            pem = secret.get("private_key_pem")
            if not pem:
                raise FoundryError(
                    f"Secret '{tunnel.key_secret}' has no 'private_key_pem' field."
                )
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_text(pem, encoding="utf-8", newline="\n")
            with suppress(OSError):
                os.chmod(key_path, 0o600)
            # Private key material in the working tree must never be
            # committable — cover it in .gitignore or warn loudly.
            try:
                from foundry_cli.core.project.dotfoundry import ensure_path_ignored

                ensure_path_ignored(workspace_root, key_path)
            except OSError:
                logger.warning(
                    "Could not update .gitignore to cover the tunnel key at %s "
                    "— make sure it is git-ignored before committing.",
                    key_path,
                )

    return replace(tunnel, host=host)


def _expand_tunnel_placeholders(value: str, tunnel: SshTunnelConfig) -> str:
    """``${localPort}``/``${localHost}`` in a tunnel's env templates."""
    return value.replace("${localPort}", str(tunnel.local_port)).replace(
        "${localHost}", "localhost"
    )


def _build_injected_env(tunnel: SshTunnelConfig, *, legacy: bool) -> dict[str, str]:
    """Env one tunnel contributes to the service.

    Legacy (singular ``sshTunnel``) keeps the implicit contract: DB_HOST/
    DB_PORT plus the default creds mapping. Map (``sshTunnels``) entries
    inject ONLY what they declare: their ``env`` templates, plus ``injectEnv``
    fields read from ``credentialsSecret``.
    """
    env: dict[str, str] = {}
    if legacy:
        env["DB_HOST"] = "localhost"
        env["DB_PORT"] = str(tunnel.local_port)
    for key, template in tunnel.env.items():
        env[key] = _expand_tunnel_placeholders(str(template), tunnel)
    if tunnel.credentials_secret:
        from foundry_cli.core.aws import get_secret_json

        secret = get_secret_json(tunnel.credentials_secret, region=tunnel.aws_region)
        mapping = {**(_DEFAULT_CREDS_MAPPING if legacy else {}), **tunnel.inject_env}
        for env_var, secret_field in mapping.items():
            value = secret.get(secret_field)
            if value is not None:
                env[env_var] = str(value)
    return env


def _merge_tunnel_envs(
    tunnels: dict[str, SshTunnelConfig], *, legacy: bool
) -> dict[str, str]:
    """Compose all tunnels' contributed env, failing loudly on collisions."""
    merged: dict[str, str] = {}
    owner: dict[str, str] = {}
    for name, tunnel in tunnels.items():
        for key, value in _build_injected_env(tunnel, legacy=legacy).items():
            if key in owner:
                raise FoundryError(
                    f"Env var '{key}' is injected by both tunnel "
                    f"'{owner[key]}' and tunnel '{name}' — rename one side's "
                    "env/injectEnv key."
                )
            merged[key] = value
            owner[key] = name
    return merged


def _check_local_port_collisions(tunnels: dict[str, SshTunnelConfig]) -> None:
    seen: dict[int, str] = {}
    for name, tunnel in tunnels.items():
        if tunnel.local_port in seen:
            raise FoundryError(
                f"Tunnels '{seen[tunnel.local_port]}' and '{name}' both use "
                f"localPort {tunnel.local_port} — every tunnel needs its own."
            )
        seen[tunnel.local_port] = name


def prepare_service_for_dev(
    service: DiscoveredService,
    workspace_root: Path,
) -> tuple[DiscoveredService, str, tuple[str, ...]]:
    """Resolve one service's dev target and return it ready to run.

    Returns ``(service, mode, injected_env_keys)`` where ``service`` carries
    the fully-merged env (and, in prod mode, a concrete tunnel config; in
    local mode, no tunnel at all).

    Env precedence (later wins): manifest run.env → prod-guard (prod only) →
    injected credentials (prod only) → .foundry/dev.env → .foundry/dev.local.env.
    Env files win over injection so a developer can deliberately override any
    injected value.
    """
    cfg = service.config
    file_env = load_env_files(workspace_root)
    stack = {**cfg.env, **file_env}
    mode = resolve_dev_target(stack, cfg.ssh_tunnels)

    if mode == "local" or not cfg.ssh_tunnels:
        env = {**cfg.env, **file_env, "FOUNDRY_DEV_MODE": "local"}
        new_cfg = replace(cfg, env=env, ssh_tunnels={})
        return replace(service, config=new_cfg), "local", ()

    _check_local_port_collisions(cfg.ssh_tunnels)
    tunnels = {
        name: _autowire_tunnel(t, workspace_root)
        for name, t in cfg.ssh_tunnels.items()
    }
    injected = _merge_tunnel_envs(tunnels, legacy=cfg.ssh_tunnels_legacy)
    env = {
        **cfg.env,
        **cfg.dev_prod_guard_env,
        **injected,
        **file_env,
        "FOUNDRY_DEV_MODE": "prod",
    }
    new_cfg = replace(cfg, env=env, ssh_tunnels=tunnels)
    injected_keys = tuple(sorted({*cfg.dev_prod_guard_env, *injected}))
    return replace(service, config=new_cfg), "prod", injected_keys


__all__ = [
    "load_env_files",
    "resolve_dev_target",
    "prepare_service_for_dev",
]
