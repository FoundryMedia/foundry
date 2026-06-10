"""Convention engine — pure-function module for deployment profile resolution.

The convention engine takes a service config from ``foundry.json`` and returns
a fully-resolved ``DeploymentProfile``.  It encodes all the "if you're a
Spring Boot backend, you get these defaults" logic in one place.

**Key design principle:** No I/O, no AWS calls, no file system access.  This
module is pure data transformation — input is manifest data, output is a
resolved profile.  Side-effect-free and trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from foundry_cli.core.project.manifest import (
    CdnConfig,
    DeployConfig,
    SecretMapping,
    ServiceConfig,
    SidecarDeployConfig,
    StructureConfig,
)


# ── Deployment Profile ───────────────────────────────────────────────────


@dataclass(frozen=True)
class DeploymentProfile:
    """Fully-resolved deployment configuration for a single service.

    This is the output of the convention engine.  It contains every detail
    the deployment engines need — no convention lookups at deploy time.
    """

    name: str
    kind: str                             # backend, frontend, package
    type: str                             # spring-boot, uvicorn, nextjs, etc.
    role: str                             # microlith, auth, hub, public, etc.
    strategy: str                         # ecs, s3-static, lambda, none
    dockerfile: str | None                # Relative path to Dockerfile (None for non-Docker)
    build_context: str                    # Relative path to Docker/build context
    build_command: str | None             # For non-Docker builds (static sites)
    secrets: tuple[SecretMapping, ...]    # Secrets to fetch before build/deploy
    cdn: bool | CdnConfig | None         # CDN config (True=auto, False=none, obj=custom)
    depends_on: tuple[str, ...]           # Deployment dependencies
    sidecars: dict[str, SidecarDeployConfig]  # ECS sidecar containers
    watch_paths: tuple[str, ...]          # Paths that trigger deployment on change
    database: str | None                  # Logical database name (for migration ordering)

    # Multi-repo (v0.7.0). ``repository`` is the owner/repo the service lives in
    # (None = same repo as the manifest / monorepo). ``path`` is its location
    # within that repo (``"."`` = repo root). Paths above are relative to the repo.
    repository: str | None = None
    path: str = "."

    @property
    def is_deployable(self) -> bool:
        """Whether this service has a real deployment strategy."""
        return self.strategy != "none"

    @property
    def needs_docker(self) -> bool:
        """Whether this service requires a Docker build."""
        return self.strategy == "service"

    @property
    def needs_node(self) -> bool:
        """Whether this service requires a Node.js build step."""
        return self.type in ("nextjs", "vite", "react", "vue", "angular")

    @property
    def needs_database_migration(self) -> bool:
        """Whether this service depends on a database migration phase."""
        return self.database is not None

    @property
    def has_sidecars(self) -> bool:
        """Whether this service has sidecar containers."""
        return len(self.sidecars) > 0


# ── Convention Defaults ──────────────────────────────────────────────────

# Strategy defaults: (stack_type, framework) → strategy
# v0.5.0: "service" (containerized) and "static" (S3/CDN hosted).
_STRATEGY_DEFAULTS: dict[tuple[str, str | None], str] = {
    ("backend", "spring-boot"): "service",
    ("backend", "uvicorn"): "service",
    ("backend", "gunicorn"): "service",
    ("backend", "express"): "service",
    ("backend", "django"): "service",
    ("backend", "flask"): "service",
    ("backend", None): "service",           # Fallback: any backend → service
    ("frontend", "vite"): "static",
    ("frontend", "react"): "static",
    ("frontend", "vue"): "static",
    ("frontend", "angular"): "static",
    ("frontend", "nextjs"): "service",       # nextjs defaults to service (SSR)
    ("frontend", None): "service",           # Fallback: any frontend → service
    ("package", None): "none",               # Packages are never deployed
}

# Build context defaults: (stack_type, framework) → context path template
# Templates support {apps_dir}, {kind}, {name}
_BUILD_CONTEXT_DEFAULTS: dict[tuple[str, str | None], str] = {
    ("backend", "spring-boot"): ".",                          # Monorepo root (Maven/Gradle)
    ("backend", "uvicorn"): "{apps_dir}/backend/{name}",     # Service directory
    ("backend", "gunicorn"): "{apps_dir}/backend/{name}",
    ("backend", "express"): ".",                              # Monorepo root (pnpm workspace)
    ("backend", None): "{apps_dir}/backend/{name}",
    ("frontend", "nextjs"): ".",                              # Monorepo root for Docker
    ("frontend", None): "{apps_dir}/frontend/{name}",
}


def _default_strategy(kind: str, type_: str | None) -> str:
    """Resolve the default deployment strategy from kind + type."""
    # Try exact match first, then kind-only fallback
    return _STRATEGY_DEFAULTS.get(
        (kind, type_),
        _STRATEGY_DEFAULTS.get((kind, None), "none"),
    )


def _default_dockerfile(
    kind: str,
    name: str,
    strategy: str,
    structure: StructureConfig,
) -> str | None:
    """Derive the default Dockerfile path.  None for non-Docker strategies."""
    if strategy != "service":
        return None
    apps_dir = structure.apps_dir
    if kind == "backend":
        return f"{apps_dir}/backend/{name}/Dockerfile"
    elif kind == "frontend":
        return f"{apps_dir}/frontend/{name}/Dockerfile"
    return None


def _default_build_context(
    kind: str,
    type_: str | None,
    name: str,
    strategy: str,
    structure: StructureConfig,
) -> str:
    """Derive the default build context path."""
    if strategy == "none":
        return "."
    apps_dir = structure.apps_dir
    # Try exact match, then kind-only fallback
    template = _BUILD_CONTEXT_DEFAULTS.get(
        (kind, type_),
        _BUILD_CONTEXT_DEFAULTS.get((kind, None), "{apps_dir}/{kind}/{name}"),
    )
    return template.format(apps_dir=apps_dir, kind=kind, name=name)


def _default_build_command(
    type_: str | None,
    strategy: str,
) -> str | None:
    """Derive the default build command for non-Docker builds."""
    if strategy != "static":
        return None
    # Static sites need a build command
    if type_ in ("nextjs", "vite", "react", "vue", "angular"):
        return "pnpm build"
    return None


def _default_secrets(
    kind: str,
    type_: str | None,
    role: str | None,
    name: str,
    strategy: str,
    structure: StructureConfig,
) -> tuple[SecretMapping, ...]:
    """Derive the default secret mappings from service identity."""
    if strategy == "none":
        return ()

    apps_dir = structure.apps_dir
    secrets: list[SecretMapping] = []

    if type_ == "spring-boot":
        # Spring profile secret
        secrets.append(SecretMapping(
            source="{prefix}-{env}/microlith-spring-properties",
            target=f"{apps_dir}/backend/{{service}}/src/main/resources/application-{{env}}.yml",
        ))
        # Auth role gets an additional EFGA config secret
        if role == "auth":
            secrets.append(SecretMapping(
                source="{prefix}-{env}/efga-spring-properties",
                target=f"{apps_dir}/backend/{{service}}/src/main/resources/efga-{{env}}.yml",
            ))
    elif type_ in ("uvicorn", "gunicorn", "flask", "django"):
        # Python backend env file
        secrets.append(SecretMapping(
            source="{prefix}-{env}/{service}-env",
            target=f"{apps_dir}/backend/{{service}}/.env",
            format="raw",
        ))
    elif kind == "frontend":
        # Frontend env file
        if strategy == "service":
            secrets.append(SecretMapping(
                source="{prefix}-{env}/{service}-env",
                target=f"{apps_dir}/frontend/{{service}}/.env.production",
            ))
        elif strategy == "static":
            secrets.append(SecretMapping(
                source="{prefix}-{env}/{service}-env",
                target=f"{apps_dir}/frontend/{{service}}/.env.production",
            ))

    return tuple(secrets)


def _default_cdn(
    kind: str,
    strategy: str,
) -> bool | CdnConfig | None:
    """Derive the default CDN configuration."""
    if strategy == "static":
        return True   # Auto — read distribution ID from IaC outputs
    if kind == "frontend" and strategy == "service":
        return True   # Frontend ECS services typically sit behind CloudFront
    return False


def _default_depends_on(
    database: str | None,
    sidecars: dict[str, SidecarDeployConfig],
    strategy: str,
) -> tuple[str, ...]:
    """Derive the default deployment dependencies."""
    if strategy == "none":
        return ()

    deps: list[str] = ["iac"]

    if database:
        deps.append(f"database:{database}")

    # Sidecar-based dependencies
    for sidecar_name in sidecars:
        deps.append(f"sidecar:{sidecar_name}")

    return tuple(deps)


def _derive_watch_paths(
    name: str,
    kind: str,
    structure: StructureConfig,
) -> tuple[str, ...]:
    """Derive file-change watch paths from service identity."""
    apps_dir = structure.apps_dir
    packages_dir = structure.packages_dir

    if kind == "backend":
        return (f"^{apps_dir}/backend/{name}/",)
    elif kind == "frontend":
        # Frontend services also trigger on shared package changes
        return (
            f"^{apps_dir}/frontend/{name}/",
            f"^{packages_dir}/",
        )
    elif kind == "package":
        return (f"^{packages_dir}/{name}/",)
    return ()


# ── Profile Resolution ───────────────────────────────────────────────────


def resolve_deployment_profile(
    name: str,
    service: ServiceConfig,
    structure: StructureConfig,
    database: str | None = None,
) -> DeploymentProfile:
    """Resolve a complete ``DeploymentProfile`` from service config + conventions.

    Priority (highest wins):

    1. Explicit ``deploy`` block fields (v0.5.0)
    2. Legacy flat fields (v0.4.0 backward compat)
    3. Convention defaults from ``stack.type + stack.framework``
    4. Global defaults

    Args:
        name: Service name (directory name within apps/backend/ etc.)
        service: Parsed ``ServiceConfig`` from the manifest.
        structure: Parsed ``StructureConfig`` for directory layout.
        database: Logical database name (for migration ordering).

    Returns:
        A fully-resolved ``DeploymentProfile`` ready for deployment engines.
    """
    # v0.5.0: stack block; v0.4.0: kind/type
    kind = service.kind or "backend"
    type_ = service.type
    role = service.role or "other"
    deploy = service.deploy or DeployConfig()

    # Resolve database name — inline dict uses service name; string is a ref
    if database:
        db = database
    elif isinstance(service.database, dict):
        db = name
    elif isinstance(service.database, str):
        db = service.database
    else:
        db = None

    # 1. Strategy — deploy block > convention default
    raw_strategy = service.effective_strategy or _default_strategy(kind, type_)
    # Normalise legacy names: ecs→service, s3-static→static
    strategy = {"ecs": "service", "s3-static": "static"}.get(raw_strategy, raw_strategy)

    # Multi-repo (v0.7.0): when a service declares its own repo and/or an
    # explicit path, derive paths relative to that location (repo-relative)
    # instead of the monorepo ``apps/{kind}/{name}`` convention. Pure monorepo
    # services (no repository, no path) keep the existing behavior byte-for-byte.
    repo_relative = service.is_multi_repo or bool(service.path)
    loc = (service.path or ".").rstrip("/") or "."

    # 2. Dockerfile
    if deploy.dockerfile:
        dockerfile = deploy.dockerfile
    elif repo_relative:
        dockerfile = (
            (f"{loc}/Dockerfile" if loc != "." else "Dockerfile")
            if strategy == "service"
            else None
        )
    else:
        dockerfile = _default_dockerfile(kind, name, strategy, structure)

    # 3. Build context
    if deploy.build_context:
        build_context = deploy.build_context
    elif repo_relative:
        build_context = loc
    else:
        build_context = _default_build_context(
            kind, type_, name, strategy, structure,
        )

    # 4. Build command
    build_command = deploy.build_command or _default_build_command(type_, strategy)

    # 5. Sidecars (explicit overrides merge with defaults)
    sidecars = dict(deploy.sidecars) if deploy.sidecars else {}

    # 6. Secrets (explicit overrides REPLACE defaults — no merge)
    if deploy.secrets:
        secrets = deploy.secrets
    else:
        secrets = _default_secrets(kind, type_, role, name, strategy, structure)

    # 7. CDN
    cdn = deploy.cdn if deploy.cdn is not None else _default_cdn(kind, strategy)

    # 8. Dependencies
    if deploy.depends_on:
        depends_on = deploy.depends_on
    else:
        depends_on = _default_depends_on(db, sidecars, strategy)

    # 9. Watch paths (always derived — not overridable)
    if repo_relative:
        # Repo-relative: a service at the repo root watches the whole repo;
        # at a subdir, just that subdir.
        watch_paths = ("^",) if loc == "." else (f"^{loc}/",)
    else:
        watch_paths = _derive_watch_paths(name, kind, structure)

    return DeploymentProfile(
        name=name,
        kind=kind,
        type=type_ or "other",
        role=role,
        strategy=strategy,
        dockerfile=dockerfile,
        build_context=build_context,
        build_command=build_command,
        secrets=secrets,
        cdn=cdn,
        depends_on=depends_on,
        sidecars=sidecars,
        watch_paths=watch_paths,
        database=db,
        repository=service.repository,
        path=loc,
    )


def resolve_all_profiles(
    manifest_data: dict[str, Any],
) -> dict[str, DeploymentProfile]:
    """Resolve deployment profiles for ALL services in a manifest.

    This is the main entry point for the convention engine.  It reads
    the raw manifest dict (``foundry.json`` data) and returns a map of
    service name → fully-resolved ``DeploymentProfile``.

    Args:
        manifest_data: Raw ``foundry.json`` data (the ``data`` attribute
            of a ``ProjectManifest``).

    Returns:
        Dict mapping service name to ``DeploymentProfile``.
    """
    # Parse structure
    raw_structure = manifest_data.get("structure", {})
    structure = StructureConfig.from_dict(raw_structure) if isinstance(raw_structure, dict) else StructureConfig()

    # Parse services
    raw_services = manifest_data.get("services", {})
    if not isinstance(raw_services, dict):
        return {}

    profiles: dict[str, DeploymentProfile] = {}
    for name, raw_svc in raw_services.items():
        if not isinstance(raw_svc, dict):
            continue
        svc = ServiceConfig.from_dict(raw_svc)

        # Resolve database name:
        # v0.4.0: inline dict → service name is the logical DB name
        # v0.3.0: string reference to top-level databases
        if isinstance(svc.database, dict):
            db_name = name
        elif isinstance(svc.database, str):
            db_name = svc.database
        else:
            db_name = None

        profiles[name] = resolve_deployment_profile(
            name=name,
            service=svc,
            structure=structure,
            database=db_name,
        )

    return profiles


__all__ = [
    "DeploymentProfile",
    "resolve_all_profiles",
    "resolve_deployment_profile",
]
