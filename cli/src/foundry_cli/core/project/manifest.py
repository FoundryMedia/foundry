from __future__ import annotations

import json
import os
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
        def _expand(value: Any) -> Any:
            if isinstance(value, str):
                return os.path.expandvars(value)
            return value

        return cls(
            local_port=data["localPort"],
            remote_host=_expand(data["remoteHost"]),
            remote_port=data["remotePort"],
            host=_expand(data["host"]),
            user=_expand(data.get("user", "ec2-user")),
            password=_expand(data.get("password")),
        )


@dataclass(frozen=True)
class SidecarConfig:
    """Configuration for a sidecar service (e.g., OPA, Redis, etc.)."""

    command: str
    args: tuple[str, ...] = field(default_factory=tuple)
    cwd: str | None = None  # Relative to manifest directory
    port: int | None = None
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    health_path: str | None = None  # HTTP health check endpoint (e.g., "/health")
    ready_patterns: tuple[str, ...] = field(default_factory=tuple)  # Log patterns indicating readiness

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SidecarConfig":
        return cls(
            command=data["command"],
            args=tuple(data.get("args", [])),
            cwd=data.get("cwd"),
            port=data.get("port"),
            env=dict(data.get("env", {})),
            enabled=data.get("enabled", True),
            health_path=data.get("healthPath"),
            ready_patterns=tuple(data.get("readyPatterns", [])),
        )


@dataclass(frozen=True)
class DebugConfig:
    """Remote debugger configuration for local development.

    Enables IDE debugger attachment (e.g. JDWP for Java, --inspect for Node).
    """

    port: int
    suspend: bool = False

    @classmethod
    def from_value(cls, value: int | dict[str, Any]) -> "DebugConfig":
        """Parse from an integer (port only) or a dict with port/suspend."""
        if isinstance(value, int):
            return cls(port=value)
        return cls(
            port=value["port"],
            suspend=value.get("suspend", False),
        )


@dataclass(frozen=True)
class HealthCheckConfig:
    """Health check endpoint configuration for deployment readiness and monitoring."""

    path: str
    port: int | None = None
    expected_status: int = 200

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HealthCheckConfig":
        return cls(
            path=data["path"],
            port=data.get("port"),
            expected_status=data.get("expectedStatus", 200),
        )


@dataclass(frozen=True)
class ApiLibModuleConfig:
    """A single module within the api-lib repository."""

    artifact_id: str
    version: str
    spec_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiLibModuleConfig":
        return cls(
            artifact_id=data["artifactId"],
            version=data["version"],
            spec_path=data.get("specPath"),
        )


@dataclass(frozen=True)
class ApiLibConfig:
    """Configuration for the platform's API library repository."""

    repository: str
    package_registry: str | None = None
    group_id: str | None = None
    modules: dict[str, ApiLibModuleConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiLibConfig":
        modules = {}
        raw_modules = data.get("modules", {})
        if isinstance(raw_modules, dict):
            for name, mod_data in raw_modules.items():
                if isinstance(mod_data, dict):
                    modules[name] = ApiLibModuleConfig.from_dict(mod_data)
        return cls(
            repository=data["repository"],
            package_registry=data.get("packageRegistry"),
            group_id=data.get("groupId"),
            modules=modules,
        )


@dataclass(frozen=True)
class EcosystemConfig:
    """Describes the broader platform ecosystem — related repositories and shared libraries."""

    organization: str | None = None
    prefix: str | None = None
    api_lib: ApiLibConfig | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EcosystemConfig":
        api_lib = None
        if "apiLib" in data and isinstance(data["apiLib"], dict):
            api_lib = ApiLibConfig.from_dict(data["apiLib"])
        return cls(
            organization=data.get("organization"),
            prefix=data.get("prefix"),
            api_lib=api_lib,
        )


@dataclass(frozen=True)
class DatabaseConfig:
    """Configuration for a database schema managed via Liquibase."""

    engine: str
    changelog: str
    schema: str | None = None
    properties_path: str | None = None
    credentials_secret_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatabaseConfig":
        # Resolve credentials secret ID from nested "credentials" block
        credentials = data.get("credentials", {})
        secret_id = credentials.get("secretId") if isinstance(credentials, dict) else None

        return cls(
            engine=data["engine"],
            changelog=data["changelog"],
            schema=data.get("schema"),
            properties_path=data.get("properties"),
            credentials_secret_id=secret_id,
        )


# ── Deploy-related dataclasses (v0.3.0+) ────────────────────────────────


@dataclass(frozen=True)
class SecretMapping:
    """Maps a secret from Secrets Manager to a file in the build context.

    Supports interpolation: ``{prefix}``, ``{env}``, ``{service}``.
    """

    source: str
    target: str
    format: str = "raw"        # raw, dotenv, extract-key
    extract_key: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecretMapping":
        return cls(
            source=data["source"],
            target=data["target"],
            format=data.get("format", "raw"),
            extract_key=data.get("extractKey"),
        )


@dataclass(frozen=True)
class CdnConfig:
    """CDN configuration for static or frontend deployments."""

    distribution_id_output: str | None = None
    invalidation_paths: tuple[str, ...] = ("/*",)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CdnConfig":
        paths = data.get("invalidationPaths", ["/*"])
        return cls(
            distribution_id_output=data.get("distributionIdOutput"),
            invalidation_paths=tuple(paths) if isinstance(paths, list) else ("/*",),
        )


@dataclass(frozen=True)
class SidecarDeployConfig:
    """Configuration for a sidecar container in ECS deployment."""

    image: str
    port: int | None = None
    cpu: int = 128
    memory: int = 256
    command: tuple[str, ...] = field(default_factory=tuple)
    environment: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SidecarDeployConfig":
        return cls(
            image=data["image"],
            port=data.get("port"),
            cpu=data.get("cpu", 128),
            memory=data.get("memory", 256),
            command=tuple(data.get("command", [])),
            environment=dict(data.get("environment", {})),
        )


@dataclass(frozen=True)
class DeployConfig:
    """Deployment configuration overrides from the ``deploy`` block.

    The convention engine derives defaults from ``kind + type + role``.
    Only fields that deviate from convention need to be specified here.
    """

    strategy: str | None = None          # ecs, s3-static, lambda, none
    dockerfile: str | None = None
    build_context: str | None = None
    build_command: str | None = None
    secrets: tuple[SecretMapping, ...] = field(default_factory=tuple)
    cdn: bool | CdnConfig | None = None
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    sidecars: dict[str, SidecarDeployConfig] = field(default_factory=dict)
    iac: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeployConfig":
        # Parse secrets
        raw_secrets = data.get("secrets", [])
        secrets = tuple(
            SecretMapping.from_dict(s) for s in raw_secrets if isinstance(s, dict)
        )

        # Parse cdn — can be bool or object
        raw_cdn = data.get("cdn")
        cdn: bool | CdnConfig | None = None
        if isinstance(raw_cdn, bool):
            cdn = raw_cdn
        elif isinstance(raw_cdn, dict):
            cdn = CdnConfig.from_dict(raw_cdn)

        # Parse sidecars
        raw_sidecars = data.get("sidecars", {})
        sidecars = {}
        if isinstance(raw_sidecars, dict):
            for name, sc_data in raw_sidecars.items():
                if isinstance(sc_data, dict):
                    sidecars[name] = SidecarDeployConfig.from_dict(sc_data)

        return cls(
            strategy=data.get("strategy"),
            dockerfile=data.get("dockerfile"),
            build_context=data.get("buildContext"),
            build_command=data.get("buildCommand"),
            secrets=secrets,
            cdn=cdn,
            depends_on=tuple(data.get("dependsOn", [])),
            sidecars=sidecars,
            iac=dict(data.get("iac", {})),
        )


@dataclass(frozen=True)
class EnvironmentConfig:
    """Maps a deployment environment to a Git branch."""

    branch: str
    enabled: bool = True
    auto_approve: bool = False
    iac: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentConfig":
        return cls(
            branch=data["branch"],
            enabled=data.get("enabled", True),
            auto_approve=data.get("autoApprove", False),
            iac=dict(data.get("iac", {})),
        )


@dataclass(frozen=True)
class ServiceConfig:
    """Service definition from ``foundry.json``.

    v0.5.0 schema (current):
        ``scope`` (public/internal), ``stack`` block (type/framework/language),
        ``deploy`` block (strategy, sidecars, secrets, cdn, etc.),
        ``run`` block (port, actuatorPort, args, env, healthCheck),
        ``database`` (inline config).

    v0.4.0 backward compat:
        ``kind``→``stack.type``, ``type``→``stack.framework``,
        ``role``→``scope``, flat ``strategy``→``deploy.strategy``.
    """

    # v0.5.0 identity
    scope: str | None = None              # public, internal

    # Stack (nested block in v0.5.0; derived from kind/type in v0.4.0)
    stack_type: str | None = None         # backend, frontend, package
    stack_framework: str | None = None    # spring-boot, uvicorn, nextjs, etc.
    stack_language: str | None = None     # java, python, typescript, etc.

    # Deploy block (v0.5.0: mandatory for services; v0.4.0: optional wrapper)
    deploy: DeployConfig | None = None

    # Database — inline dict
    database: str | dict[str, Any] | None = None

    # Run block — local development configuration
    enabled: bool = True
    port: int | None = None
    actuator_port: int | None = None
    health_check: HealthCheckConfig | None = None
    debug: DebugConfig | None = None
    args: tuple[str, ...] = field(default_factory=tuple)
    env: dict[str, str] = field(default_factory=dict)
    # Run strictness controls (local/workspace overrides or manifest run block)
    strict_mode_enabled: bool | None = None
    strict_health_ports: bool | None = None
    ssh_tunnel: SshTunnelConfig | None = None
    sidecars: dict[str, "SidecarConfig"] = field(default_factory=dict)

    # ── Convenience aliases (backward compat) ────────────────────────────

    @property
    def kind(self) -> str | None:
        """Alias for ``stack_type`` (backward compat with v0.4.0 ``kind``)."""
        return self.stack_type

    @property
    def type(self) -> str | None:
        """Alias for ``stack_framework`` (backward compat with v0.4.0 ``type``)."""
        return self.stack_framework

    @property
    def role(self) -> str | None:
        """Alias for ``scope`` (backward compat with v0.4.0 ``role``)."""
        return self.scope

    @property
    def strategy(self) -> str | None:
        """Deployment strategy from the deploy block."""
        return self.deploy.strategy if self.deploy else None

    @property
    def database_name(self) -> str | None:
        """Logical database name for cross-reference."""
        if isinstance(self.database, str):
            return self.database
        if isinstance(self.database, dict):
            return None  # caller uses service name
        return None

    @property
    def database_config(self) -> dict[str, Any] | None:
        """Inline database configuration dict, or None."""
        return self.database if isinstance(self.database, dict) else None

    @property
    def effective_strategy(self) -> str | None:
        """Deployment strategy (deploy block > legacy flat field)."""
        if self.deploy and self.deploy.strategy:
            return self.deploy.strategy
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceConfig":
        ssh_tunnel = None
        if "sshTunnel" in data and data["sshTunnel"]:
            ssh_tunnel = SshTunnelConfig.from_dict(data["sshTunnel"])

        # ── Stack resolution ─────────────────────────────────────────
        # v0.5.0: nested "stack" block
        # v0.4.0 fallback: flat "kind"/"type" fields
        stack = data.get("stack", {})
        if isinstance(stack, dict) and stack:
            stack_type = stack.get("type")
            stack_framework = stack.get("framework")
            stack_language = stack.get("language")
        else:
            stack_type = data.get("kind")
            stack_framework = data.get("type")
            stack_language = None

        # ── Scope resolution ─────────────────────────────────────────
        # v0.5.0: "scope"; v0.4.0 fallback: "role"
        scope = data.get("scope") or data.get("role")

        # ── Deploy block ─────────────────────────────────────────────
        deploy = None
        if "deploy" in data and isinstance(data["deploy"], dict):
            deploy = DeployConfig.from_dict(data["deploy"])
        elif data.get("strategy"):
            # v0.4.0 flat strategy → synthesize a DeployConfig
            deploy = DeployConfig(strategy=data["strategy"])

        # ── Sidecars (v0.4.0 flat → already in deploy for v0.5.0) ────
        sidecars: dict[str, SidecarConfig] = {}
        # v0.5.0: sidecars live inside deploy block (parsed by DeployConfig)
        # v0.4.0: sidecars at service level
        svc_sidecars = data.get("sidecars", {})
        if isinstance(svc_sidecars, dict) and svc_sidecars:
            for name, sidecar_data in svc_sidecars.items():
                if isinstance(sidecar_data, dict):
                    sidecars[name] = SidecarConfig.from_dict(sidecar_data)
        # Also merge from deploy block if present (v0.3.0 compat)
        # Deploy sidecars are Docker images; synthesize a `docker run` command
        # so the local sidecar runner can start them.
        if deploy and deploy.sidecars and not sidecars:
            for name, sc in deploy.sidecars.items():
                docker_args = ["run", "--rm"]
                if sc.port:
                    docker_args.extend(["-p", f"{sc.port}:{sc.port}"])
                for env_key, env_val in (sc.environment or {}).items():
                    docker_args.extend(["-e", f"{env_key}={env_val}"])
                docker_args.append(sc.image)
                if sc.command:
                    docker_args.extend(sc.command)
                sidecars[name] = SidecarConfig(
                    command="docker",
                    args=tuple(docker_args),
                    port=sc.port,
                    env=sc.environment or {},
                )

        # ── Run block ────────────────────────────────────────────────
        # v0.5.0: nested "run" block
        # v0.4.0 fallback: flat port/actuatorPort/args/env fields
        run = data.get("run", {})
        if isinstance(run, dict) and run:
            port = run.get("port")
            actuator_port = run.get("actuatorPort")
            args = tuple(run.get("args", []))
            env = dict(run.get("env", {}))

            strict_mode_enabled = None
            strict_health_ports = None
            strict_mode = run.get("strictMode")
            if isinstance(strict_mode, bool):
                strict_mode_enabled = strict_mode
            elif isinstance(strict_mode, dict):
                enabled = strict_mode.get("enabled")
                strict_health = strict_mode.get("strictHealthPorts")
                if isinstance(enabled, bool):
                    strict_mode_enabled = enabled
                if isinstance(strict_health, bool):
                    strict_health_ports = strict_health
        else:
            port = data.get("port")
            actuator_port = data.get("actuatorPort")
            args = tuple(data.get("args", []))
            env = dict(data.get("env", {}))
            strict_mode_enabled = None
            strict_health_ports = None

        # Parse health check (from run block or flat)
        health_check = None
        hc_data = (run if isinstance(run, dict) else data).get("healthCheck")
        if isinstance(hc_data, dict):
            health_check = HealthCheckConfig.from_dict(hc_data)

        # Parse debug configuration (from run block)
        debug = None
        debug_data = (run if isinstance(run, dict) else data).get("debug")
        if debug_data is not None:
            debug = DebugConfig.from_value(debug_data)

        return cls(
            scope=scope,
            stack_type=stack_type,
            stack_framework=stack_framework,
            stack_language=stack_language,
            deploy=deploy,
            database=data.get("database"),
            enabled=data.get("enabled", True),
            port=port,
            actuator_port=actuator_port,
            health_check=health_check,
            debug=debug,
            args=args,
            env=env,
            strict_mode_enabled=strict_mode_enabled,
            strict_health_ports=strict_health_ports,
            ssh_tunnel=ssh_tunnel,
            sidecars=sidecars,
        )


@dataclass(frozen=True)
class StructureConfig:
    """Directory layout configuration from the ``structure`` block."""

    apps_dir: str = "apps"
    ci_dir: str = "ci"
    packages_dir: str = "packages"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructureConfig":
        return cls(
            apps_dir=data.get("appsDir", "apps"),
            ci_dir=data.get("ciDir", "ci"),
            packages_dir=data.get("packagesDir", "packages"),
        )


def serialize_name(name: str) -> str:
    """Convert a human-readable platform name to a repository slug.

    ``"Acme Cloud Platform"`` → ``"acme-cloud-platform"``
    """
    return "-".join(name.lower().split())


def derive_prefix(name: str) -> str:
    """Derive a short prefix from a platform name.

    Takes the first letter of each word::

        "Acme Cloud Platform" → "aap"
        "My Cool Service"     → "mcs"

    The result is always lowercase.  Returns an empty string only if
    *name* has fewer than 2 words with leading alpha chars.
    """
    letters = [w[0] for w in name.split() if w and w[0].isalpha()]
    return "".join(letters).lower()


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
    def repository(self) -> str | None:
        """Repository slug.  Falls back to serialising the name if not set."""
        v = self.data.get("repository")
        if isinstance(v, str) and v.strip():
            return v
        if self.name:
            return serialize_name(self.name)
        return None

    @property
    def prefix(self) -> str | None:
        """Short prefix for cross-repo naming.

        v0.4.0: Top-level ``prefix`` field.
        v0.3.0 fallback: ``ecosystem.prefix``.
        Final fallback: derived from platform name initials.
        """
        # v0.4.0: top-level prefix
        v = self.data.get("prefix")
        if isinstance(v, str) and v.strip():
            return v
        # v0.3.0 fallback: ecosystem.prefix
        eco = self.data.get("ecosystem")
        if isinstance(eco, dict):
            v = eco.get("prefix")
            if isinstance(v, str) and v.strip():
                return v
        if self.name:
            p = derive_prefix(self.name)
            return p if len(p) >= 2 else None
        return None

    @property
    def structure(self) -> StructureConfig:
        """Directory layout configuration.  Returns defaults if not specified."""
        raw = self.data.get("structure")
        if isinstance(raw, dict):
            return StructureConfig.from_dict(raw)
        return StructureConfig()

    @property
    def services_dir_name(self) -> str:
        """Directory containing runnable services.

        Reads from ``structure.appsDir`` first, then legacy ``servicesDir``,
        then defaults to ``apps``.
        """
        # v0.3.0+: structure block
        raw_structure = self.data.get("structure")
        if isinstance(raw_structure, dict):
            v = raw_structure.get("appsDir")
            if isinstance(v, str) and v.strip():
                return v
        # Legacy
        v = self.data.get("servicesDir")
        return v if isinstance(v, str) and v.strip() else "apps"

    @property
    def ecosystem(self) -> EcosystemConfig | None:
        """Cross-repository ecosystem topology.

        v0.4.0: Reads from ``github`` block.
        v0.3.0 fallback: Reads from ``ecosystem`` block.
        """
        # v0.4.0: github block
        raw = self.data.get("github")
        if isinstance(raw, dict):
            return EcosystemConfig.from_dict(raw)
        # v0.3.0 fallback
        raw = self.data.get("ecosystem")
        if isinstance(raw, dict):
            return EcosystemConfig.from_dict(raw)
        return None

    @property
    def github(self) -> dict[str, Any]:
        """GitHub organization and repository configuration (v0.4.0).

        Returns the ``github`` block, falling back to ``ecosystem``.
        """
        raw = self.data.get("github")
        if isinstance(raw, dict):
            return raw
        raw = self.data.get("ecosystem")
        return raw if isinstance(raw, dict) else {}

    @property
    def organization(self) -> str | None:
        """GitHub organization name."""
        gh = self.github
        return gh.get("organization")

    @property
    def databases(self) -> dict[str, DatabaseConfig]:
        """Database configurations keyed by logical database name.

        v0.4.0: Aggregates inline ``database`` blocks from each service.
        v0.3.0 fallback: Reads from the top-level ``databases`` block.

        The logical name is the service name that owns the database.
        """
        # v0.4.0: aggregate from per-service database blocks
        raw_services = self.data.get("services", {})
        dbs: dict[str, DatabaseConfig] = {}

        if isinstance(raw_services, dict):
            for svc_name, svc_data in raw_services.items():
                if not isinstance(svc_data, dict):
                    continue
                db_cfg = svc_data.get("database")
                if isinstance(db_cfg, dict):
                    dbs[svc_name] = DatabaseConfig.from_dict(db_cfg)

        if dbs:
            return dbs

        # v0.3.0 fallback: top-level databases block
        raw = self.data.get("databases", {})
        if isinstance(raw, dict):
            return {
                name: DatabaseConfig.from_dict(cfg)
                for name, cfg in raw.items()
                if isinstance(cfg, dict)
            }
        return {}

    @property
    def environments(self) -> dict[str, EnvironmentConfig]:
        """Deployment environments from ``ci.environments``.

        Returns Foundry defaults (prod→release, dev→develop, test→qa) if
        the manifest omits the environments block.
        """
        ci = self.data.get("ci", {})
        raw = ci.get("environments", {}) if isinstance(ci, dict) else {}
        if not isinstance(raw, dict) or not raw:
            # Foundry CLI defaults
            return {
                "prod": EnvironmentConfig(branch="release"),
                "dev": EnvironmentConfig(branch="develop"),
                "test": EnvironmentConfig(branch="qa"),
            }
        return {
            name: EnvironmentConfig.from_dict(cfg)
            for name, cfg in raw.items()
            if isinstance(cfg, dict)
        }

    def resolve_environment(self, branch: str) -> str | None:
        """Resolve a Git branch name to a deployment environment name.

        Returns ``None`` if the branch doesn't match any *enabled* environment.
        """
        for env_name, env_cfg in self.environments.items():
            if env_cfg.branch == branch and env_cfg.enabled:
                return env_name
        return None

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


__all__ = [
    "ApiLibConfig",
    "ApiLibModuleConfig",
    "CdnConfig",
    "DatabaseConfig",
    "DeployConfig",
    "EcosystemConfig",
    "EnvironmentConfig",
    "HealthCheckConfig",
    "ProjectManifest",
    "SecretMapping",
    "ServiceConfig",
    "SidecarConfig",
    "SidecarDeployConfig",
    "StructureConfig",
    "derive_prefix",
    "load_manifest",
    "load_manifest_from_path",
    "serialize_name",
]
