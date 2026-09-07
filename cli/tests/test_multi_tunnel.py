"""Wave-4 Phase 1: multiple SSH tunnels per service.

Locks the contracts: legacy singular `sshTunnel` behavior byte-identical
(implicit DB_* + default creds mapping), named-map `sshTunnels` explicit-only
injection with ${localPort} templates, collision fail-closed, config.yml
merge-by-name, and the db-tunnel pick convention.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import foundry_cli.core.aws as aws_mod
from foundry_cli.core.errors import FoundryError
from foundry_cli.core.project import dev_env
from foundry_cli.core.project.manifest import ServiceConfig, SshTunnelConfig
from foundry_cli.core.project.workspace import (
    DiscoveredService,
    _apply_local_service_overrides,
)

TUNNEL_BASE = {
    "localPort": 15432,
    "remoteHost": "db.internal",
    "remotePort": 5432,
    "host": "1.2.3.4",
}


def _svc_cfg(data: dict) -> ServiceConfig:
    return ServiceConfig.from_dict(data)


def _service(cfg: ServiceConfig, name: str = "api") -> DiscoveredService:
    return DiscoveredService(
        name=name, path=Path("."), runtime=None, kind=None, config=cfg  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_parse_legacy_singular() -> None:
    cfg = _svc_cfg({"sshTunnel": dict(TUNNEL_BASE)})
    assert set(cfg.ssh_tunnels) == {"default"}
    assert cfg.ssh_tunnels_legacy is True
    assert cfg.ssh_tunnels["default"].local_port == 15432


def test_parse_named_map() -> None:
    cfg = _svc_cfg({
        "sshTunnels": {
            "authService": {**TUNNEL_BASE, "localPort": 18080,
                            "env": {"AUTH_BASE_URL": "http://localhost:${localPort}"}},
            "primaryDb": dict(TUNNEL_BASE),
        }
    })
    assert set(cfg.ssh_tunnels) == {"authService", "primaryDb"}
    assert cfg.ssh_tunnels_legacy is False
    assert cfg.ssh_tunnels["authService"].env == {
        "AUTH_BASE_URL": "http://localhost:${localPort}"
    }


def test_parse_both_forms_is_an_error() -> None:
    with pytest.raises(FoundryError):
        _svc_cfg({
            "sshTunnel": dict(TUNNEL_BASE),
            "sshTunnels": {"db": dict(TUNNEL_BASE)},
        })


# ---------------------------------------------------------------------------
# db_tunnel pick convention (foundry db / migration wrapper)
# ---------------------------------------------------------------------------

def test_db_tunnel_legacy_and_named_and_sole_credentialed() -> None:
    legacy = _svc_cfg({"sshTunnel": dict(TUNNEL_BASE)})
    assert legacy.db_tunnel is not None

    named = _svc_cfg({"sshTunnels": {
        "auth": {**TUNNEL_BASE, "localPort": 18080},
        "db": dict(TUNNEL_BASE),
    }})
    assert named.db_tunnel is not None and named.db_tunnel.local_port == 15432

    sole = _svc_cfg({"sshTunnels": {
        "auth": {**TUNNEL_BASE, "localPort": 18080},
        "primary": {**TUNNEL_BASE, "credentialsSecret": "acme/db"},
    }})
    assert sole.db_tunnel is not None and sole.db_tunnel.credentials_secret == "acme/db"

    ambiguous = _svc_cfg({"sshTunnels": {
        "a": {**TUNNEL_BASE, "credentialsSecret": "acme/a"},
        "b": {**TUNNEL_BASE, "localPort": 15433, "credentialsSecret": "acme/b"},
    }})
    assert ambiguous.db_tunnel is None


# ---------------------------------------------------------------------------
# Injection semantics
# ---------------------------------------------------------------------------

def test_legacy_injection_byte_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Singular form keeps DB_HOST/DB_PORT + default creds mapping exactly."""
    monkeypatch.setattr(
        aws_mod, "get_secret_json",
        lambda secret_id, region=None: {"dbname": "app", "username": "u", "password": "p"},
    )
    tunnel = SshTunnelConfig.from_dict({**TUNNEL_BASE, "credentialsSecret": "s"})
    env = dev_env._build_injected_env(tunnel, legacy=True)
    assert env == {
        "DB_HOST": "localhost",
        "DB_PORT": "15432",
        "DB_NAME": "app",
        "DB_USER": "u",
        "DB_PASSWORD": "p",
    }


def test_map_entry_injects_only_what_it_declares(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        aws_mod, "get_secret_json",
        lambda secret_id, region=None: {"username": "u", "password": "p", "dbname": "app"},
    )
    tunnel = SshTunnelConfig.from_dict({
        **TUNNEL_BASE,
        "credentialsSecret": "s",
        "env": {"DB1_HOST": "${localHost}", "DB1_PORT": "${localPort}"},
        "injectEnv": {"DB1_USER": "username", "DB1_PASSWORD": "password"},
    })
    env = dev_env._build_injected_env(tunnel, legacy=False)
    # No implicit DB_HOST/DB_PORT/DB_NAME — explicit keys only.
    assert env == {
        "DB1_HOST": "localhost",
        "DB1_PORT": "15432",
        "DB1_USER": "u",
        "DB1_PASSWORD": "p",
    }


def test_env_collision_across_tunnels_fails_loudly() -> None:
    tunnels = {
        "a": SshTunnelConfig.from_dict({**TUNNEL_BASE, "env": {"X": "1"}}),
        "b": SshTunnelConfig.from_dict(
            {**TUNNEL_BASE, "localPort": 15433, "env": {"X": "2"}}
        ),
    }
    with pytest.raises(FoundryError, match="'X'"):
        dev_env._merge_tunnel_envs(tunnels, legacy=False)


def test_local_port_collision_fails_loudly() -> None:
    tunnels = {
        "a": SshTunnelConfig.from_dict(dict(TUNNEL_BASE)),
        "b": SshTunnelConfig.from_dict(dict(TUNNEL_BASE)),
    }
    with pytest.raises(FoundryError, match="localPort 15432"):
        dev_env._check_local_port_collisions(tunnels)


# ---------------------------------------------------------------------------
# prepare_service_for_dev end-to-end (no AWS: plain hosts, no secrets)
# ---------------------------------------------------------------------------

def test_prepare_three_tunnels_prod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FOUNDRY_DEV_TARGET", "prod")
    cfg = _svc_cfg({
        "run": {"env": {"BASE": "1"}},
        "sshTunnels": {
            "authService": {**TUNNEL_BASE, "localPort": 18080,
                            "env": {"AUTH_BASE_URL": "http://localhost:${localPort}"}},
            "primaryDb": {**TUNNEL_BASE,
                          "env": {"DB1_PORT": "${localPort}"}},
            "replicaDb": {**TUNNEL_BASE, "localPort": 15433,
                          "env": {"DB2_PORT": "${localPort}"}},
        },
    })
    svc, mode, injected_keys = dev_env.prepare_service_for_dev(_service(cfg), tmp_path)
    assert mode == "prod"
    env = svc.config.env
    assert env["AUTH_BASE_URL"] == "http://localhost:18080"
    assert env["DB1_PORT"] == "15432"
    assert env["DB2_PORT"] == "15433"
    assert env["BASE"] == "1"
    assert env["FOUNDRY_DEV_MODE"] == "prod"
    assert set(svc.config.ssh_tunnels) == {"authService", "primaryDb", "replicaDb"}
    assert "AUTH_BASE_URL" in injected_keys


def test_prepare_local_strips_all_tunnels(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FOUNDRY_DEV_TARGET", "local")
    cfg = _svc_cfg({"sshTunnels": {"db": dict(TUNNEL_BASE)}})
    svc, mode, _ = dev_env.prepare_service_for_dev(_service(cfg), tmp_path)
    assert mode == "local"
    assert svc.config.ssh_tunnels == {}


def test_resolve_dev_target_matches_any_tunnel_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOUNDRY_DEV_TARGET", raising=False)
    tunnels = {
        "a": SshTunnelConfig.from_dict({**TUNNEL_BASE, "localPort": 18080}),
        "b": SshTunnelConfig.from_dict({**TUNNEL_BASE, "localPort": 15433}),
    }
    assert dev_env.resolve_dev_target({"DB_PORT": "15433"}, tunnels) == "prod"
    assert dev_env.resolve_dev_target({}, {}) == "local"


# ---------------------------------------------------------------------------
# config.yml override merge-by-name
# ---------------------------------------------------------------------------

def _write_config_yml(foundry_dir: Path, body: str) -> None:
    foundry_dir.mkdir(parents=True, exist_ok=True)
    (foundry_dir / "config.yml").write_text(body, encoding="utf-8")


def test_config_yml_sshtunnels_merge_by_name(tmp_path: Path) -> None:
    cfg = _svc_cfg({"sshTunnels": {
        "db": dict(TUNNEL_BASE),
        "auth": {**TUNNEL_BASE, "localPort": 18080},
    }})
    _write_config_yml(tmp_path / ".foundry", (
        "services:\n"
        "  api:\n"
        "    sshTunnels:\n"
        "      auth: null\n"
        "      db:\n"
        "        localPort: 25432\n"
        "        remoteHost: other.internal\n"
        "        remotePort: 5432\n"
        "        host: 5.6.7.8\n"
    ))
    [out] = _apply_local_service_overrides([_service(cfg)], tmp_path / ".foundry")
    assert set(out.config.ssh_tunnels) == {"db"}
    assert out.config.ssh_tunnels["db"].local_port == 25432
    assert out.config.ssh_tunnels_legacy is False


def test_config_yml_disable_all(tmp_path: Path) -> None:
    cfg = _svc_cfg({"sshTunnels": {"db": dict(TUNNEL_BASE)}})
    _write_config_yml(tmp_path / ".foundry", "services:\n  api:\n    sshTunnels: false\n")
    [out] = _apply_local_service_overrides([_service(cfg)], tmp_path / ".foundry")
    assert out.config.ssh_tunnels == {}


def test_config_yml_legacy_override_still_works(tmp_path: Path) -> None:
    cfg = _svc_cfg({"sshTunnels": {"db": dict(TUNNEL_BASE)}})
    _write_config_yml(tmp_path / ".foundry", (
        "services:\n"
        "  api:\n"
        "    sshTunnel:\n"
        "      localPort: 15432\n"
        "      remoteHost: db.internal\n"
        "      remotePort: 5432\n"
        "      host: 9.9.9.9\n"
    ))
    [out] = _apply_local_service_overrides([_service(cfg)], tmp_path / ".foundry")
    assert set(out.config.ssh_tunnels) == {"default"}
    assert out.config.ssh_tunnels_legacy is True
