"""``.foundry/workspace.yml`` — resolved service path map.

Maps each manifest service name to the **actual directory** it lives in on
disk.  The manifest (``foundry.json``) remains the single source of truth for
everything *declarative* — scope, stack, deploy strategy, run config, database.
For Node/pnpm services the ``package.json`` scripts define how to run them.

``workspace.yml`` captures exactly one thing the manifest *cannot* know: where
each service physically lives when the directory name doesn't match the
manifest key (e.g. ``microlith`` → ``apps/backend/platform-microlith``).

Lifecycle::

    foundry init   →  creates foundry.json, then runs sync automatically
    foundry sync   →  reads manifest + scans filesystem → writes workspace.yml
    foundry run    →  reads manifest (launch config) + workspace.yml (paths)
    foundry generate → reads manifest + workspace.yml for resolved service map

The file is **committed to git** — the whole team shares a common view.
Regenerate with ``foundry sync``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from foundry_cli.core.project.manifest import ProjectManifest
from foundry_cli.core.project.service_runtime import (
    detect_package_manager,
    detect_runtime,
)


WORKSPACE_YML_FILENAME = "workspace.yml"


class _NoAliasDumper(yaml.SafeDumper):
    """YAML dumper that never emits anchors/aliases."""

    def ignore_aliases(self, data: Any) -> bool:  # type: ignore[override]
        return True


# Runtimes that should be treated as equivalent when comparing manifest
# framework to filesystem detection.
_EQUIVALENT_FRAMEWORKS: set[tuple[str, str]] = {
    ("fastapi", "uvicorn"),
    ("uvicorn", "uvicorn"),
    ("spring-boot", "spring-boot"),
    ("nextjs", "nextjs"),
    ("vite", "vite"),
}


# ---------------------------------------------------------------------------
# Filesystem scanning
# ---------------------------------------------------------------------------

def scan_filesystem(
    project_root: Path,
    apps_dir: str = "apps",
    packages_dir: str = "packages",
) -> dict[str, dict[str, Any]]:
    """Scan the project for service directories under the canonical layout.

    Returns a dict keyed by directory name with detection metadata.
    """
    discovered: dict[str, dict[str, Any]] = {}

    for kind, scan_dir in [
        ("backend",  project_root / apps_dir / "backend"),
        ("frontend", project_root / apps_dir / "frontend"),
        ("package",  project_root / packages_dir),
    ]:
        if not scan_dir.is_dir():
            continue
        for child in sorted(scan_dir.iterdir()):
            if not child.is_dir() or child.name.startswith((".", "_")):
                continue

            runtime = detect_runtime(child)
            pkg_mgr = detect_package_manager(child, project_root)
            rel = str(child.relative_to(project_root)).replace("\\", "/")

            discovered[child.name] = {
                "kind": kind,
                "path": rel,
                "detectedRuntime": runtime.runtime.value,
                "packageManager": pkg_mgr.value,
                "evidence": runtime.evidence,
            }

    return discovered


# ---------------------------------------------------------------------------
# Directory resolution
# ---------------------------------------------------------------------------

def _resolve_service_dir(
    kind: str,
    svc_name: str,
    project_root: Path,
    apps_dir: str,
    packages_dir: str,
) -> Path | None:
    """Resolve the actual directory for a service on disk.

    Tries exact match, then prefix match (e.g. ``"hub"`` → ``"hub-frontend"``),
    then contains match.  Returns ``None`` if no match found.
    """
    if kind == "frontend":
        base = project_root / apps_dir / "frontend"
    elif kind == "backend":
        base = project_root / apps_dir / "backend"
    else:
        base = project_root / packages_dir

    # Exact match
    exact = base / svc_name
    if exact.is_dir():
        return exact

    # Prefix match (e.g. "hub" → "hub-frontend")
    if base.is_dir():
        candidates = [d for d in base.iterdir() if d.is_dir() and d.name.startswith(svc_name)]
        if len(candidates) == 1:
            return candidates[0]

    # Contains match
    if base.is_dir():
        candidates = [d for d in base.iterdir() if d.is_dir() and svc_name in d.name]
        if len(candidates) == 1:
            return candidates[0]

    return None


def _relative_posix(child: Path, parent: Path) -> str:
    """Forward-slash relative path."""
    try:
        return str(child.relative_to(parent)).replace("\\", "/")
    except ValueError:
        return str(child).replace("\\", "/")


# ---------------------------------------------------------------------------
# Workspace resolution
# ---------------------------------------------------------------------------

def resolve_workspace(
    project_root: Path,
    manifest: ProjectManifest,
) -> dict[str, Any]:
    """Resolve the workspace path map from manifest + filesystem.

    This is the core of ``foundry sync``.  It:

    1. Scans the filesystem to discover what's on disk.
    2. Walks every service in the manifest.
    3. Resolves each service's actual directory path.
    4. Computes drift (undeclared dirs, missing dirs, framework mismatches).
    5. Returns a dict ready for YAML serialization to ``workspace.yml``.

    The returned dict is intentionally minimal — just service→path mappings
    plus any drift.  All other service metadata lives in ``foundry.json``.
    """
    structure = manifest.structure
    apps_dir = structure.apps_dir
    packages_dir = structure.packages_dir

    # --- Filesystem scan ---
    discovered = scan_filesystem(project_root, apps_dir, packages_dir)
    discovered_names = set(discovered.keys())
    manifest_names = set(manifest.services_config.keys())

    # --- Resolve each manifest service's path ---
    services_out: dict[str, str | None] = {}
    resolved_dir_names: set[str] = set()

    for svc_name, svc_cfg in manifest.services_config.items():
        kind = svc_cfg.kind or "backend"

        # Resolve filesystem path
        svc_dir = _resolve_service_dir(kind, svc_name, project_root, apps_dir, packages_dir)

        if svc_dir is not None and svc_dir.is_dir():
            rel_path = _relative_posix(svc_dir, project_root)
            resolved_dir_names.add(svc_dir.name)
        else:
            rel_path = None

        services_out[svc_name] = rel_path

    # --- Drift ---
    undeclared = sorted(discovered_names - manifest_names - resolved_dir_names)
    missing = sorted(name for name, path in services_out.items() if path is None)

    # Framework mismatches (detected runtime vs manifest-declared framework)
    mismatches: dict[str, list[str]] = {}
    for svc_name, svc_cfg in manifest.services_config.items():
        framework = svc_cfg.type
        if not framework or services_out.get(svc_name) is None:
            continue
        # Find the discovered entry for this service's resolved dir
        rel_path = services_out[svc_name]
        disk_entry = next(
            (v for v in discovered.values() if v["path"] == rel_path),
            None,
        )
        if disk_entry is None:
            continue
        detected_rt = disk_entry["detectedRuntime"]
        if detected_rt and detected_rt != "unknown":
            if (detected_rt, framework) not in _EQUIVALENT_FRAMEWORKS:
                mismatches.setdefault(svc_name, []).append(
                    f"framework: manifest={framework}, detected={detected_rt}"
                )

    drift: dict[str, Any] = {}
    if undeclared:
        drift["undeclared"] = {
            name: {
                "kind": discovered[name]["kind"],
                "path": discovered[name]["path"],
                "detectedRuntime": discovered[name]["detectedRuntime"],
            }
            for name in undeclared
        }
    if missing:
        drift["missing"] = missing
    if mismatches:
        drift["mismatches"] = mismatches

    # --- Assemble ---
    workspace: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "schemaVersion": manifest.data.get("schemaVersion", "unknown"),
        "services": services_out,
    }

    if drift:
        workspace["drift"] = drift

    return workspace


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_HEADER = """\
# .foundry/workspace.yml
# Generated by Foundry CLI — regenerate with `foundry sync`.
# Maps manifest service names to their actual directories on disk.
# Committed to git — the team shares a common view of the workspace.
# ---

"""


def save_workspace_yml(workspace_data: dict[str, Any], foundry_dir: Path) -> Path:
    """Write resolved workspace to ``.foundry/workspace.yml``."""
    path = foundry_dir / WORKSPACE_YML_FILENAME
    content = _HEADER + yaml.dump(
        workspace_data,
        Dumper=_NoAliasDumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    path.write_text(content, encoding="utf-8")
    return path


def load_workspace_yml(foundry_dir: Path) -> dict[str, Any] | None:
    """Load workspace config from ``.foundry/workspace.yml``, or ``None`` if absent."""
    path = foundry_dir / WORKSPACE_YML_FILENAME
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


__all__ = [
    "WORKSPACE_YML_FILENAME",
    "load_workspace_yml",
    "resolve_workspace",
    "save_workspace_yml",
    "scan_filesystem",
]
