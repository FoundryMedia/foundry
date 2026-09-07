"""Wave-4 Phase 2: per-environment dev overlays + concurrent envs.

Locks: environments.<env> run/env/sshTunnels overlay merge semantics,
per-env env-file layering, FOUNDRY_DEV_ENV plumb, and dev-only (branchless)
environments staying invisible to the CI generators.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundry_cli.core.project import dev_env
from foundry_cli.core.project.manifest import (
    ProjectManifest,
    ServiceConfig,
    load_manifest_from_path,
)
from foundry_cli.core.project.workspace import DiscoveredService

TUNNEL_BASE = {
    "localPort": 15432,
    "remoteHost": "db.internal",
    "remotePort": 5432,
    "host": "1.2.3.4",
}


def _svc_cfg(data: dict) -> ServiceConfig:
    return ServiceConfig.from_dict(data)


def _service(cfg: ServiceConfig) -> DiscoveredService:
    return DiscoveredService(
        name="api", path=Path("."), runtime=None, kind=None, config=cfg  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Overlay merge semantics
# ---------------------------------------------------------------------------

BASE_SVC = {
    "run": {"port": 8091, "env": {"BASE": "1", "SHARED": "base"}},
    "sshTunnels": {
        "db": {**TUNNEL_BASE, "credentialsSecret": "acme-prod/db"},
        "auth": {**TUNNEL_BASE, "localPort": 18080},
    },
    "environments": {
        "staging": {
            "run": {"port": 9091, "env": {"SHARED": "staging"}},
            "env": {"STAGE_ONLY": "yes"},
            "sshTunnels": {
                "db": {"localPort": 25432, "credentialsSecret": "acme-staging/db"},
                "auth": None,
                "cache": {**TUNNEL_BASE, "localPort": 26379},
            },
        }
    },
}


def test_overlay_applies_run_env_and_tunnels() -> None:
    cfg = dev_env.apply_env_overlay(_svc_cfg(BASE_SVC), "staging")
    assert cfg.port == 9091
    assert cfg.env["SHARED"] == "staging"
    assert cfg.env["STAGE_ONLY"] == "yes"
    assert cfg.env["BASE"] == "1"

    # db: FIELD-level merge — only the two given keys changed
    db = cfg.ssh_tunnels["db"]
    assert db.local_port == 25432
    assert db.credentials_secret == "acme-staging/db"
    assert db.remote_host == "db.internal"  # untouched base field survives

    # auth removed; cache added as a full new tunnel
    assert "auth" not in cfg.ssh_tunnels
    assert cfg.ssh_tunnels["cache"].local_port == 26379


def test_no_env_selected_is_identity() -> None:
    base = _svc_cfg(BASE_SVC)
    assert dev_env.apply_env_overlay(base, None) is base


def test_unknown_env_is_passthrough() -> None:
    base = _svc_cfg(BASE_SVC)
    assert dev_env.apply_env_overlay(base, "nope") is base


def test_overlay_added_tunnel_clears_legacy_flag() -> None:
    cfg = _svc_cfg({
        "sshTunnel": dict(TUNNEL_BASE),  # legacy singular
        "environments": {"staging": {"sshTunnels": {"extra": {**TUNNEL_BASE, "localPort": 25432}}}},
    })
    assert cfg.ssh_tunnels_legacy is True
    out = dev_env.apply_env_overlay(cfg, "staging")
    assert set(out.ssh_tunnels) == {"default", "extra"}
    assert out.ssh_tunnels_legacy is False


def test_overlay_field_merge_keeps_legacy_flag() -> None:
    cfg = _svc_cfg({
        "sshTunnel": dict(TUNNEL_BASE),
        "environments": {"staging": {"sshTunnels": {"default": {"localPort": 25432}}}},
    })
    out = dev_env.apply_env_overlay(cfg, "staging")
    assert out.ssh_tunnels["default"].local_port == 25432
    assert out.ssh_tunnels_legacy is True


# ---------------------------------------------------------------------------
# Per-env env files + FOUNDRY_DEV_ENV plumb
# ---------------------------------------------------------------------------

def test_env_file_layering(tmp_path: Path) -> None:
    fd = tmp_path / ".foundry"
    fd.mkdir()
    (fd / "dev.env").write_text("A=base\nB=base\nC=base\nD=base\n", encoding="utf-8")
    (fd / "dev.staging.env").write_text("B=stage\nC=stage\nD=stage\n", encoding="utf-8")
    (fd / "dev.local.env").write_text("C=local\nD=local\n", encoding="utf-8")
    (fd / "dev.staging.local.env").write_text("D=stage-local\n", encoding="utf-8")

    env = dev_env.load_env_files(tmp_path, "staging")
    assert (env["A"], env["B"], env["C"], env["D"]) == ("base", "stage", "local", "stage-local")

    # No env selected: the per-env files are ignored entirely
    env = dev_env.load_env_files(tmp_path)
    assert (env["B"], env["D"]) == ("base", "local")


def _mock_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    import foundry_cli.core.aws as aws_mod

    monkeypatch.setattr(
        aws_mod, "get_secret_json",
        lambda secret_id, region=None: {"dbname": "app", "username": "u", "password": "p"},
    )


def test_prepare_uses_selected_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _mock_secrets(monkeypatch)
    monkeypatch.setenv("FOUNDRY_DEV_ENV", "staging")
    monkeypatch.setenv("FOUNDRY_DEV_TARGET", "prod")
    svc, mode, _ = dev_env.prepare_service_for_dev(_service(_svc_cfg(BASE_SVC)), tmp_path)
    assert mode == "prod"
    assert svc.config.port == 9091
    assert svc.config.env["FOUNDRY_DEV_ENV"] == "staging"
    assert svc.config.ssh_tunnels["db"].local_port == 25432
    assert "auth" not in svc.config.ssh_tunnels


def test_prepare_without_env_untouched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _mock_secrets(monkeypatch)
    monkeypatch.delenv("FOUNDRY_DEV_ENV", raising=False)
    monkeypatch.setenv("FOUNDRY_DEV_TARGET", "prod")
    svc, _, _ = dev_env.prepare_service_for_dev(_service(_svc_cfg(BASE_SVC)), tmp_path)
    assert svc.config.port == 8091
    assert "FOUNDRY_DEV_ENV" not in svc.config.env
    assert set(svc.config.ssh_tunnels) == {"db", "auth"}


# ---------------------------------------------------------------------------
# Dev-only (branchless) environments are invisible to CI generators
# ---------------------------------------------------------------------------

def test_branchless_env_excluded_from_resolve_environments(tmp_path: Path) -> None:
    manifest_path = tmp_path / "foundry.json"
    manifest_path.write_text(json.dumps({
        "schemaVersion": "0.7.0",
        "name": "acme",
        "ci": {"environments": {"prod": {"branch": "release"}}},
        "services": {
            "api": {"environments": {
                "staging": {"env": {"X": "1"}},              # dev-only
                "prod": {"branch": "main"},                   # CI override
            }},
        },
    }), encoding="utf-8")
    manifest: ProjectManifest = load_manifest_from_path(manifest_path)
    envs = manifest.resolve_environments("api")
    assert "staging" not in envs           # branchless → CI never sees it
    assert envs["prod"].branch == "main"   # branch override still works
    # but the SERVICE config still carries the overlay for run dev
    assert "staging" in manifest.services_config["api"].environments
