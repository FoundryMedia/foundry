from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from foundry_cli.core.errors import FoundryError

from foundry_cli.core.project.manifest import ProjectManifest, ServiceConfig, load_manifest_from_path
from foundry_cli.core.project.service_runtime import RuntimeMatch, ServiceRuntime, detect_runtime


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


class ServiceKind(str, Enum):
    frontend = "frontend"
    backend = "backend"
    worker = "worker"
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

    return ServiceKind.unknown


def find_manifest_path(start: Path | None = None) -> Path:
    """Find the nearest `foundry.json` by walking up from `start` (or CWD)."""

    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent

    while True:
        candidate = cur / "foundry.json"
        if candidate.exists():
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent

    raise FoundryError(
        "Could not locate project manifest (foundry.json) in the current directory or any parent directory."
    )


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

    root = (manifest.path.parent / rel).resolve()
    if not root.exists() or not root.is_dir():
        raise FoundryError(
            f"Could not locate services directory '{raw}' next to {manifest.path.name}. "
            "Create it (default: 'apps') or set `servicesDir` in foundry.json."
        )

    return root


def discover_services(services_root: Path, manifest: ProjectManifest | None = None) -> list[DiscoveredService]:
    """Discover service folders inside the services root.

    Current heuristic: immediate child directories that do not start with '.' or '_'.

    If a manifest is provided, service configs from foundry.json are merged in.
    """

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
                services.append(
                    DiscoveredService(
                        name=n,
                        path=nested,
                        runtime=detect_runtime(nested),
                        kind=infer_service_kind(services_root, nested),
                        config=manifest.get_service_config(n) if manifest else ServiceConfig(),
                    )
                )
            continue

        services.append(
            DiscoveredService(
                name=name,
                path=child,
                runtime=detect_runtime(child),
                kind=infer_service_kind(services_root, child),
                config=manifest.get_service_config(name) if manifest else ServiceConfig(),
            )
        )
    return services


def load_workspace(start: Path | None = None, command: str = "dev") -> tuple[FoundryWorkspace, Path, list[DiscoveredService]]:
    """Load the current workspace and discover local services.

    For non-Node services (Spring Boot, FastAPI), discovers from the apps/ directory.
    For Node packages, discovers all workspace packages that have the requested npm script.

    Args:
        start: Starting directory to search from (defaults to CWD)
        command: The npm script to look for (e.g., "dev", "build")

    Returns:
      (workspace, services_root, services)
    """
    from foundry_cli.core.project.packages import (
        find_packages_with_script,
        sort_packages_by_dependency_order,
    )

    manifest_path = find_manifest_path(start)
    manifest = load_manifest_from_path(manifest_path)
    services_root = resolve_services_root(manifest)
    workspace_root = manifest_path.parent

    # Discover traditional services (Spring Boot, FastAPI, etc.) from apps/
    traditional_services = discover_services(services_root, manifest)
    
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
            elif "packages" in parts:
                kind = ServiceKind.unknown  # shared packages
        except ValueError:
            pass

        # Use the short name (without @repo/ prefix) for display
        display_name = pkg.name
        if "/" in display_name:
            display_name = display_name.split("/")[-1]

        node_services.append(
            DiscoveredService(
                name=display_name,
                path=pkg.path,
                runtime=RuntimeMatch(ServiceRuntime.nextjs, f"package.json: has '{command}' script"),
                kind=kind,
                config=manifest.get_service_config(display_name),
            )
        )

    # Combine: Node packages first (dependencies before dependents), then other services
    all_services = node_services + non_node_services

    # Filter out disabled services
    all_services = [s for s in all_services if s.config.enabled]

    ws = FoundryWorkspace(root=workspace_root, manifests=(manifest,))
    return ws, services_root, all_services


__all__ = [
    "FoundryWorkspace",
    "DiscoveredService",
    "ServiceKind",
    "find_manifest_path",
    "resolve_services_root",
    "discover_services",
    "load_workspace",
]
