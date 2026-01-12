from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from foundry_cli.core.errors import FoundryError

from foundry_cli.core.project.manifest import ProjectManifest, load_manifest_from_path
from foundry_cli.core.project.service_runtime import RuntimeMatch, detect_runtime


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


def discover_services(services_root: Path) -> list[DiscoveredService]:
    """Discover service folders inside the services root.

    Current heuristic: immediate child directories that do not start with '.' or '_'.
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
                    )
                )
            continue

        services.append(
            DiscoveredService(
                name=name,
                path=child,
                runtime=detect_runtime(child),
                kind=infer_service_kind(services_root, child),
            )
        )
    return services


def load_workspace(start: Path | None = None) -> tuple[FoundryWorkspace, Path, list[DiscoveredService]]:
    """Load the current workspace and discover local services.

    Returns:
      (workspace, services_root, services)
    """

    manifest_path = find_manifest_path(start)
    manifest = load_manifest_from_path(manifest_path)
    services_root = resolve_services_root(manifest)
    services = discover_services(services_root)

    ws = FoundryWorkspace(root=manifest_path.parent, manifests=(manifest,))
    return ws, services_root, services


__all__ = [
    "FoundryWorkspace",
    "DiscoveredService",
    "ServiceKind",
    "find_manifest_path",
    "resolve_services_root",
    "discover_services",
    "load_workspace",
]
