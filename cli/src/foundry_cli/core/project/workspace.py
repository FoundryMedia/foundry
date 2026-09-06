from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
import yaml

from foundry_cli.core.errors import FoundryError

from foundry_cli.core.project.manifest import ProjectManifest, ServiceConfig, SidecarConfig, SshTunnelConfig, load_manifest_from_path
from foundry_cli.core.project.service_runtime import RuntimeMatch, ServiceRuntime, detect_runtime
from foundry_cli.core.project.workspace_config import load_workspace_yml


@dataclass(frozen=True)
class FoundryWorkspace:
    """A local Foundry workspace.

    This is the future replacement for the ambiguous term "platform".

    A workspace may aggregate multiple repositories and multiple `foundry.json`
    manifests into a single runnable view (services, CI/IaC, environments, etc.).

    For now this is intentionally minimal; higher-level service discovery and
    multi-manifest resolution will be built on top of this type.
    """

    root: Path
    manifests: tuple[ProjectManifest, ...]


@dataclass(frozen=True)
class DiscoveredService:
    name: str
    path: Path
    runtime: RuntimeMatch
    kind: "ServiceKind"
    config: ServiceConfig = ServiceConfig()


@dataclass(frozen=True)
class DiscoveredSidecar:
    """A sidecar service configured within a service's config in foundry.json."""
    name: str
    config: SidecarConfig
    parent_service: str  # Name of the service this sidecar belongs to


class ServiceKind(str, Enum):
    frontend = "frontend"
    backend = "backend"
    worker = "worker"
    sidecar = "sidecar"
    package = "package"  # Shared workspace package — built locally, not deployed
    unknown = "unknown"


def infer_service_kind(services_root: Path, service_dir: Path) -> ServiceKind:
    """Infer service kind from directory conventions.

    Convention (optional):
      apps/frontend/<service>
      apps/backend/<service>
      apps/worker/<service>

    If the repo doesn't use that structure, we return unknown.
    """

    try:
        rel = service_dir.relative_to(services_root)
    except Exception:
        return ServiceKind.unknown

    parts = rel.parts
    if len(parts) >= 2:
        head = parts[0].lower()
        if head == "frontend":
            return ServiceKind.frontend
        if head == "backend":
            return ServiceKind.backend
        if head in ("worker", "workers"):
            return ServiceKind.worker
        if head in ("packages", "libs", "libraries"):
            return ServiceKind.package

    return ServiceKind.unknown


def find_manifest_path(start: Path | None = None) -> Path:
    """Find the nearest manifest by walking up from `start` (or CWD).

    Per directory, `.foundry/foundry.json` is preferred (the multi-repo
    convention for repos opted into an ops repo); a root-level `foundry.json`
    is the legacy/monorepo location and remains fully supported.
    """

    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent

    while True:
        for candidate in (cur / ".foundry" / "foundry.json", cur / "foundry.json"):
            if candidate.exists():
                return candidate
        if cur.parent == cur:
            break
        cur = cur.parent

    raise FoundryError(
        "Could not locate project manifest (.foundry/foundry.json or foundry.json) "
        "in the current directory or any parent directory."
    )


def manifest_workspace_root(manifest_path: Path) -> Path:
    """The workspace/repo root a manifest governs.

    A manifest at `<repo>/.foundry/foundry.json` governs `<repo>`, not the
    `.foundry` directory itself.
    """
    root = manifest_path.parent
    if root.name == ".foundry":
        return root.parent
    return root


def resolve_services_root(manifest: ProjectManifest) -> Path:
    """Resolve the directory containing runnable services.

    - Uses manifest.services_dir_name (defaults to `apps`).
    - Must be a relative path inside the manifest directory.
    - If it doesn't exist, that's a fatal error.
    """

    raw = manifest.services_dir_name
    rel = Path(raw)

    if rel.is_absolute():
        raise FoundryError(
            f"Invalid `servicesDir` in {manifest.path.name}: must be a relative path, got '{raw}'."
        )

    root = (manifest_workspace_root(manifest.path) / rel).resolve()
    if not root.exists() or not root.is_dir():
        raise FoundryError(
            f"Could not locate services directory '{raw}' next to {manifest.path.name}. "
            "Create it (default: 'apps') or set `servicesDir` in foundry.json."
        )

    return root


_STACK_TYPE_TO_KIND = {
    "backend": ServiceKind.backend,
    "frontend": ServiceKind.frontend,
    "worker": ServiceKind.worker,
}


def discover_manifest_services(manifest: ProjectManifest) -> list[DiscoveredService]:
    """Resolve services straight from the manifest's service declarations.

    Multi-repo manifests (schemaVersion >= 0.7.0) place each service at
    ``services.<name>.path`` inside its own repository — there is no ``apps/``
    directory to scan. A declared service whose directory is missing is
    skipped so a partially-checked-out workspace still loads.
    """
    base = manifest_workspace_root(manifest.path)
    services: list[DiscoveredService] = []
    for name, cfg in manifest.services_config.items():
        svc_dir = (base / Path(cfg.effective_path)).resolve()
        if not svc_dir.is_dir():
            continue
        services.append(
            DiscoveredService(
                name=name,
                path=svc_dir,
                runtime=detect_runtime(svc_dir),
                kind=_STACK_TYPE_TO_KIND.get(cfg.stack_type or "", ServiceKind.unknown),
                config=cfg,
            )
        )
    return services


def _build_path_to_key_map(
    workspace_root: Path,
    path_map: dict[str, str | None],
) -> dict[str, str]:
    """Build a reverse lookup from resolved dir path → manifest key.

    ``path_map`` is ``workspace.yml``'s ``services`` section:
    ``{"microlith": "apps/backend/platform-microlith", ...}``.

    Returns e.g. ``{"platform-microlith": "microlith", ...}``
    keyed by directory name for fast lookup during discovery.
    """
    result: dict[str, str] = {}
    for manifest_key, rel_path in path_map.items():
        if rel_path is None:
            continue
        # The last segment of the path is the directory name.
        dir_name = rel_path.rstrip("/").rsplit("/", 1)[-1]
        result[dir_name] = manifest_key
    return result


def discover_services(
    services_root: Path,
    manifest: ProjectManifest | None = None,
    *,
    path_to_key: dict[str, str] | None = None,
) -> list[DiscoveredService]:
    """Discover service folders inside the services root.

    Current heuristic: immediate child directories that do not start with '.' or '_'.

    If a manifest is provided, service configs from foundry.json are merged in.
    When ``path_to_key`` is given (built from ``workspace.yml``), directory names
    are mapped back to manifest keys so that configs (args, ports, etc.) are
    correctly resolved even when the dir name differs from the manifest key.
    """
    if path_to_key is None:
        path_to_key = {}

    def _resolve(dir_name: str) -> tuple[str, ServiceConfig]:
        """Return (service_name, config) for a discovered directory."""
        manifest_key = path_to_key.get(dir_name, dir_name)
        cfg = manifest.get_service_config(manifest_key) if manifest else ServiceConfig()
        return manifest_key, cfg

    services: list[DiscoveredService] = []
    for child in sorted(services_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(".") or name.startswith("_"):
            continue

        # If the optional grouping convention is used (apps/frontend/* etc),
        # treat the *second* level as the actual service.
        if name.lower() in ("frontend", "backend", "worker", "workers"):
            for nested in sorted(child.iterdir()):
                if not nested.is_dir():
                    continue
                n = nested.name
                if n.startswith(".") or n.startswith("_"):
                    continue
                svc_name, svc_cfg = _resolve(n)
                services.append(
                    DiscoveredService(
                        name=svc_name,
                        path=nested,
                        runtime=detect_runtime(nested),
                        kind=infer_service_kind(services_root, nested),
                        config=svc_cfg,
                    )
                )
            continue

        svc_name, svc_cfg = _resolve(name)
        services.append(
            DiscoveredService(
                name=svc_name,
                path=child,
                runtime=detect_runtime(child),
                kind=infer_service_kind(services_root, child),
                config=svc_cfg,
            )
        )
    return services


def _load_local_config_yml(foundry_dir: Path) -> dict | None:
    """Load merged Foundry config (defaults, then local overrides).

    Merge precedence:
      1) ``.foundry/config.defaults.yml`` (committed, team-safe baseline)
      2) ``.foundry/config.yml`` (gitignored, developer-local overrides)

    This allows teams to share non-sensitive defaults while keeping personal
    and sensitive settings local.
    """

    def _load_yaml_object(path: Path) -> dict | None:
        if not path.exists() or not path.is_file():
            return None
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise FoundryError(f"Could not parse {path}: {e}") from e

        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise FoundryError(f"Invalid {path}: expected a YAML object at the root.")
        return raw

    def _deep_merge(base: dict, overlay: dict) -> dict:
        merged = dict(base)
        for key, value in overlay.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = _deep_merge(existing, value)
            else:
                merged[key] = value
        return merged

    defaults_path = foundry_dir / "config.defaults.yml"
    local_path = foundry_dir / "config.yml"

    defaults_cfg = _load_yaml_object(defaults_path) or {}
    local_cfg = _load_yaml_object(local_path) or {}

    if not defaults_cfg and not local_cfg:
        return None

    return _deep_merge(defaults_cfg, local_cfg)


def _apply_local_service_overrides(
    services: list[DiscoveredService],
    foundry_dir: Path,
) -> list[DiscoveredService]:
    """Apply overrides from ``.foundry/config.defaults.yml`` + ``config.yml``.

    Supported per-service overrides:
      services.<name>.sshTunnel
        - dict: full tunnel config
        - null/false: disable any manifest tunnel
            services.<name>.run.strictMode
                - bool: enables/disables strict mode
                - object: { enabled?: bool, strictHealthPorts?: bool }
    """
    local_cfg = _load_local_config_yml(foundry_dir)
    if not local_cfg:
        return services

    raw_services = local_cfg.get("services")
    if raw_services is None:
        return services
    if not isinstance(raw_services, dict):
        raise FoundryError(
            "Invalid .foundry/config.defaults.yml or .foundry/config.yml: "
            "'services' must be a mapping."
        )

    updated: list[DiscoveredService] = []
    for svc in services:
        override = raw_services.get(svc.name)
        if not isinstance(override, dict):
            updated.append(svc)
            continue

        cfg = svc.config
        if "sshTunnel" in override:
            raw_tunnel = override.get("sshTunnel")
            if raw_tunnel in (None, False):
                cfg = replace(cfg, ssh_tunnel=None)
            elif isinstance(raw_tunnel, dict):
                cfg = replace(cfg, ssh_tunnel=SshTunnelConfig.from_dict(raw_tunnel))
            else:
                raise FoundryError(
                    f"Invalid .foundry/config.yml for service '{svc.name}': "
                    "'sshTunnel' must be an object, null, or false."
                )

        if "run" in override:
            raw_run = override.get("run")
            if not isinstance(raw_run, dict):
                raise FoundryError(
                    f"Invalid .foundry/config.yml for service '{svc.name}': "
                    "'run' must be an object."
                )

            if "strictMode" in raw_run:
                raw_strict = raw_run.get("strictMode")
                if isinstance(raw_strict, bool):
                    cfg = replace(
                        cfg,
                        strict_mode_enabled=raw_strict,
                        strict_health_ports=cfg.strict_health_ports,
                    )
                elif isinstance(raw_strict, dict):
                    strict_enabled = cfg.strict_mode_enabled
                    strict_health_ports = cfg.strict_health_ports

                    enabled = raw_strict.get("enabled")
                    strict_health = raw_strict.get("strictHealthPorts")

                    if enabled is not None and not isinstance(enabled, bool):
                        raise FoundryError(
                            f"Invalid .foundry/config.yml for service '{svc.name}': "
                            "run.strictMode.enabled must be boolean."
                        )
                    if strict_health is not None and not isinstance(strict_health, bool):
                        raise FoundryError(
                            f"Invalid .foundry/config.yml for service '{svc.name}': "
                            "run.strictMode.strictHealthPorts must be boolean."
                        )

                    if isinstance(enabled, bool):
                        strict_enabled = enabled
                    if isinstance(strict_health, bool):
                        strict_health_ports = strict_health

                    cfg = replace(
                        cfg,
                        strict_mode_enabled=strict_enabled,
                        strict_health_ports=strict_health_ports,
                    )
                else:
                    raise FoundryError(
                        f"Invalid .foundry/config.yml for service '{svc.name}': "
                        "run.strictMode must be a boolean or object."
                    )

        updated.append(replace(svc, config=cfg))

    return updated


def load_workspace(start: Path | None = None, command: str = "dev") -> tuple[FoundryWorkspace, Path, list[DiscoveredService], list[DiscoveredSidecar]]:
    """Load the current workspace and discover local services.

    If ``.foundry/workspace.yml`` exists, uses its path map to correctly
    resolve directory names back to manifest keys (e.g. the directory
    ``platform-microlith`` maps to the manifest key ``microlith``).  This
    ensures that launch config (args, ports, env) from ``foundry.json`` is
    applied to the right service.

    For Node services managed by pnpm/npm, launch configuration comes from
    ``package.json`` scripts — Foundry only needs the manifest for port
    overrides and similar settings.

    Args:
        start: Starting directory to search from (defaults to CWD)
        command: The npm script to look for (e.g., "dev", "build")

    Returns:
      (workspace, services_root, services, sidecars)
    """
    from foundry_cli.core.project.packages import (
        find_packages_with_script,
        sort_packages_by_dependency_order,
    )

    manifest_path = find_manifest_path(start)
    manifest = load_manifest_from_path(manifest_path)
    workspace_root = manifest_workspace_root(manifest_path)

    # Load workspace.yml path map for dir-name → manifest-key resolution
    path_to_key: dict[str, str] = {}
    foundry_dir = workspace_root / ".foundry"
    ws_data = load_workspace_yml(foundry_dir)
    if ws_data and isinstance(ws_data.get("services"), dict):
        path_to_key = _build_path_to_key_map(workspace_root, ws_data["services"])

    apps_root = workspace_root / Path(manifest.services_dir_name)
    if apps_root.is_dir():
        # Monorepo layout: scan the services directory (apps/ by default).
        services_root = resolve_services_root(manifest)
        traditional_services = discover_services(
            services_root, manifest, path_to_key=path_to_key,
        )
    else:
        # Multi-repo layout (v0.7.0): no apps/ dir — each declared service
        # resolves via its own `path` relative to the manifest.
        traditional_services = discover_manifest_services(manifest)
        if not traditional_services:
            # Nothing declared/resolvable either way: raise the original,
            # descriptive services-directory error.
            resolve_services_root(manifest)
        services_root = workspace_root
        # Let Node-package discovery resolve manifest keys too (e.g. the dir
        # `app` carrying the manifest service `web`).
        for svc_name, svc_cfg in manifest.services_config.items():
            dir_name = Path(svc_cfg.effective_path).name
            path_to_key.setdefault(dir_name, svc_name)
    
    # Filter to only non-Node services (Spring Boot, FastAPI)
    non_node_services = [
        s for s in traditional_services 
        if s.runtime.runtime not in (ServiceRuntime.nextjs, ServiceRuntime.unknown)
    ]

    # Discover Node packages that have the requested script
    node_packages = find_packages_with_script(workspace_root, command)
    node_packages = sort_packages_by_dependency_order(node_packages)
    
    # Convert Node packages to DiscoveredService
    node_services = []
    for pkg in node_packages:
        # Determine kind based on path
        kind = ServiceKind.unknown
        try:
            rel = pkg.path.relative_to(workspace_root)
            parts = rel.parts
            if "frontend" in parts:
                kind = ServiceKind.frontend
            elif "backend" in parts:
                kind = ServiceKind.backend
            elif "packages" in parts or "libs" in parts:
                kind = ServiceKind.package
        except ValueError:
            pass

        # Use the short name (without @repo/ prefix) for display
        display_name = pkg.name
        if "/" in display_name:
            display_name = display_name.split("/")[-1]

        # Resolve manifest key via workspace.yml path map.
        # Try the directory name first (most reliable), then the package name.
        # e.g. dir "web" → manifest key "web", even if package.json name is "public".
        dir_name = pkg.path.name
        manifest_key = path_to_key.get(dir_name) or path_to_key.get(display_name, display_name)

        node_services.append(
            DiscoveredService(
                name=manifest_key,
                path=pkg.path,
                runtime=RuntimeMatch(ServiceRuntime.nextjs, f"package.json: has '{command}' script"),
                kind=kind,
                config=manifest.get_service_config(manifest_key),
            )
        )

    # Combine: Node packages first (dependencies before dependents), then other
    # services. A manifest-declared service whose directory is ALSO a Node
    # package (e.g. a vite frontend) is served by the Node path — drop the
    # duplicate so it isn't started twice.
    node_paths = {str(s.path) for s in node_services}
    non_node_services = [s for s in non_node_services if str(s.path) not in node_paths]
    all_services = node_services + non_node_services

    # Filter out disabled services
    all_services = [s for s in all_services if s.config.enabled]

    # Apply optional developer-local overrides from .foundry/config.yml
    all_services = _apply_local_service_overrides(all_services, foundry_dir)

    # Discover sidecars from within service configs
    sidecars = []
    for svc in all_services:
        for sidecar_name, sidecar_config in svc.config.sidecars.items():
            if sidecar_config.enabled:
                sidecars.append(DiscoveredSidecar(
                    name=sidecar_name,
                    config=sidecar_config,
                    parent_service=svc.name,
                ))

    ws = FoundryWorkspace(root=workspace_root, manifests=(manifest,))
    return ws, services_root, all_services, sidecars


def filter_services(
    services: list[DiscoveredService],
    sidecars: list[DiscoveredSidecar],
    filter_names: list[str],
    workspace_root: Path,
) -> tuple[list[DiscoveredService], list[DiscoveredSidecar]]:
    """Filter services to only those requested, plus their dependencies.

    Automatically includes:
    - Node workspace package dependencies (transitively from package.json)
    - Sidecars for any included service

    Args:
        services: All discovered services
        sidecars: All discovered sidecars
        filter_names: Names of services to include (manifest keys)
        workspace_root: Root directory of the workspace

    Returns:
        Filtered (services, sidecars) tuple preserving original order
    """
    from foundry_cli.core.project.packages import (
        discover_workspace_packages,
        get_package_dependencies,
    )

    svc_by_name = {s.name: s for s in services}
    svc_by_path = {str(s.path): s for s in services}

    # Start with explicitly requested services
    included: set[str] = set()
    for name in filter_names:
        if name in svc_by_name:
            included.add(name)

    # Resolve Node workspace dependencies transitively
    all_packages = discover_workspace_packages(workspace_root)
    pkg_by_path = {str(pkg.path): pkg for pkg in all_packages}

    queue = list(included)
    visited: set[str] = set()
    while queue:
        svc_name = queue.pop(0)
        if svc_name in visited:
            continue
        visited.add(svc_name)

        svc = svc_by_name.get(svc_name)
        if svc is None:
            continue

        # Find the WorkspacePackage for this service by matching paths
        pkg = pkg_by_path.get(str(svc.path))
        if pkg is None:
            continue

        # Get workspace packages this package depends on
        deps = get_package_dependencies(pkg, all_packages)
        for dep_pkg in deps:
            dep_svc = svc_by_path.get(str(dep_pkg.path))
            if dep_svc and dep_svc.name not in included:
                included.add(dep_svc.name)
                queue.append(dep_svc.name)

    # Filter services, preserving original order
    filtered_services = [s for s in services if s.name in included]

    # Include sidecars only for included services
    filtered_sidecars = [sc for sc in sidecars if sc.parent_service in included]

    return filtered_services, filtered_sidecars


__all__ = [
    "FoundryWorkspace",
    "DiscoveredService",
    "DiscoveredSidecar",
    "ServiceKind",
    "find_manifest_path",
    "manifest_workspace_root",
    "resolve_services_root",
    "discover_services",
    "discover_manifest_services",
    "load_workspace",
    "filter_services",
]
