from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundry_cli.core.errors import FoundryError


@dataclass(frozen=True)
class SshTunnelConfig:
    """SSH tunnel configuration for a service."""

    local_port: int
    remote_host: str
    remote_port: int
    host: str
    user: str = "ec2-user"
    password: str | None = None  # Path to SSH private key file

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SshTunnelConfig":
        return cls(
            local_port=data["localPort"],
            remote_host=data["remoteHost"],
            remote_port=data["remotePort"],
            host=data["host"],
            user=data.get("user", "ec2-user"),
            password=data.get("password"),
        )


@dataclass(frozen=True)
class ServiceConfig:
    """Launch configuration for a single service."""

    enabled: bool = True
    port: int | None = None
    actuator_port: int | None = None
    args: tuple[str, ...] = field(default_factory=tuple)
    env: dict[str, str] = field(default_factory=dict)
    ssh_tunnel: SshTunnelConfig | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceConfig":
        ssh_tunnel = None
        if "sshTunnel" in data and data["sshTunnel"]:
            ssh_tunnel = SshTunnelConfig.from_dict(data["sshTunnel"])
        
        return cls(
            enabled=data.get("enabled", True),
            port=data.get("port"),
            actuator_port=data.get("actuatorPort"),
            args=tuple(data.get("args", [])),
            env=dict(data.get("env", {})),
            ssh_tunnel=ssh_tunnel,
        )


@dataclass(frozen=True)
class ProjectManifest:
    """Represents a single Foundry project manifest file (typically `foundry.json`).

    Note: A future "platform" concept may aggregate multiple `ProjectManifest` instances
    across repositories.
    """

    path: Path
    data: dict[str, Any]

    @property
    def name(self) -> str | None:
        v = self.data.get("name")
        return v if isinstance(v, str) else None

    @property
    def services_dir_name(self) -> str:
        """Directory name (or relative path) containing runnable services.

        Configurable via `servicesDir` in `foundry.json`. Defaults to `apps`.
        """

        v = self.data.get("servicesDir")
        return v if isinstance(v, str) and v.strip() else "apps"

    @property
    def services_config(self) -> dict[str, ServiceConfig]:
        """Service launch configurations keyed by service name."""

        raw = self.data.get("services", {})
        if not isinstance(raw, dict):
            return {}

        return {
            name: ServiceConfig.from_dict(cfg) if isinstance(cfg, dict) else ServiceConfig()
            for name, cfg in raw.items()
        }

    def get_service_config(self, service_name: str) -> ServiceConfig:
        """Get the launch config for a service, or defaults if not specified."""
        return self.services_config.get(service_name, ServiceConfig())


def load_manifest() -> ProjectManifest:
    """Load `foundry.json` from the current working directory."""

    cwd = Path.cwd()
    manifest_path = cwd / "foundry.json"
    if not manifest_path.exists():
        raise FoundryError(
            "Could not locate project manifest (foundry.json) in the current directory."
        )

    return load_manifest_from_path(manifest_path)


def load_manifest_from_path(manifest_path: Path) -> ProjectManifest:
    """Load a manifest from a specific path."""

    if not manifest_path.exists():
        raise FoundryError(f"Manifest file does not exist: {manifest_path}")

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise FoundryError(f"Invalid foundry.json (failed to parse JSON): {e}") from e

    if not isinstance(data, dict):
        raise FoundryError("Invalid foundry.json (root must be a JSON object).")

    return ProjectManifest(path=manifest_path, data=data)


__all__ = ["ProjectManifest", "ServiceConfig", "load_manifest", "load_manifest_from_path"]
