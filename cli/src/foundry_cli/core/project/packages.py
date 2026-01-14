"""Node.js/pnpm workspace package discovery and management."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml


@dataclass(frozen=True)
class WorkspacePackage:
    """A package discovered in a pnpm/npm/yarn workspace."""
    name: str
    path: Path
    scripts: dict[str, str]
    dependencies: dict[str, str]
    dev_dependencies: dict[str, str]

    def has_script(self, script_name: str) -> bool:
        """Check if this package has a specific npm script."""
        return script_name in self.scripts

    @property
    def is_workspace_dep(self) -> bool:
        """Check if this package is intended to be used as a workspace dependency."""
        # Packages that start with @ and are private are typically workspace deps
        return self.name.startswith("@") or "workspace:*" in str(self.dependencies) + str(self.dev_dependencies)


def _parse_package_json(path: Path) -> WorkspacePackage | None:
    """Parse a package.json file into a WorkspacePackage."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkspacePackage(
            name=data.get("name", path.parent.name),
            path=path.parent,
            scripts=data.get("scripts", {}),
            dependencies=data.get("dependencies", {}),
            dev_dependencies=data.get("devDependencies", {}),
        )
    except Exception:
        return None


def _expand_glob_pattern(root: Path, pattern: str) -> Iterator[Path]:
    """Expand a glob pattern relative to root, returning matching directories."""
    # Handle pnpm-workspace patterns like "packages/*" or "apps/**"
    # Note: Python's glob doesn't handle ** the same way, so we handle it manually
    
    pattern = pattern.rstrip("/")
    
    # Skip patterns that are negations (start with !)
    if pattern.startswith("!"):
        return
    
    if "**" in pattern:
        # For patterns like "apps/**", we want all nested directories
        base = pattern.split("**")[0].rstrip("/")
        base_path = root / base if base else root
        if base_path.exists():
            for item in base_path.rglob("*"):
                # Skip node_modules and hidden directories
                if "node_modules" in item.parts or any(p.startswith(".") for p in item.parts):
                    continue
                if item.is_dir() and (item / "package.json").exists():
                    yield item
    else:
        # For patterns like "packages/*"
        for item in root.glob(pattern):
            # Skip node_modules and hidden directories
            if "node_modules" in item.parts or any(p.startswith(".") for p in item.parts):
                continue
            if item.is_dir() and (item / "package.json").exists():
                yield item


def find_workspace_root(start: Path) -> Path | None:
    """Find the monorepo workspace root by walking up from start."""
    cur = start.resolve()
    while cur.parent != cur:
        if (cur / "pnpm-workspace.yaml").exists():
            return cur
        pkg = cur / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                if "workspaces" in data:
                    return cur
            except Exception:
                pass
        cur = cur.parent
    return None


def discover_workspace_packages(workspace_root: Path) -> list[WorkspacePackage]:
    """Discover all packages in a pnpm/npm/yarn workspace.
    
    Reads pnpm-workspace.yaml or package.json workspaces field to find
    all packages in the monorepo.
    """
    packages: list[WorkspacePackage] = []
    patterns: list[str] = []
    
    # Try pnpm-workspace.yaml first
    pnpm_ws = workspace_root / "pnpm-workspace.yaml"
    if pnpm_ws.exists():
        try:
            data = yaml.safe_load(pnpm_ws.read_text(encoding="utf-8"))
            patterns = data.get("packages", [])
        except Exception:
            pass
    
    # Fall back to package.json workspaces
    if not patterns:
        pkg = workspace_root / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                ws = data.get("workspaces", [])
                # workspaces can be a list or an object with "packages" key
                if isinstance(ws, list):
                    patterns = ws
                elif isinstance(ws, dict):
                    patterns = ws.get("packages", [])
            except Exception:
                pass
    
    # Expand patterns and collect packages
    seen_paths: set[Path] = set()
    for pattern in patterns:
        for pkg_dir in _expand_glob_pattern(workspace_root, pattern):
            if pkg_dir in seen_paths:
                continue
            seen_paths.add(pkg_dir)
            
            pkg = _parse_package_json(pkg_dir / "package.json")
            if pkg:
                packages.append(pkg)
    
    return sorted(packages, key=lambda p: p.name)


def find_packages_with_script(workspace_root: Path, script_name: str) -> list[WorkspacePackage]:
    """Find all workspace packages that have a specific npm script.
    
    Args:
        workspace_root: Root of the workspace (where pnpm-workspace.yaml lives)
        script_name: Name of the script to look for (e.g., "dev", "build")
    
    Returns:
        List of packages that have the specified script
    """
    packages = discover_workspace_packages(workspace_root)
    return [pkg for pkg in packages if pkg.has_script(script_name)]


def get_package_dependencies(package: WorkspacePackage, all_packages: list[WorkspacePackage]) -> list[WorkspacePackage]:
    """Get the workspace packages that a given package depends on.
    
    This is useful for determining build order - dependencies should be
    built before dependents.
    """
    all_by_name = {pkg.name: pkg for pkg in all_packages}
    deps: list[WorkspacePackage] = []
    
    for dep_name in list(package.dependencies.keys()) + list(package.dev_dependencies.keys()):
        if dep_name in all_by_name:
            deps.append(all_by_name[dep_name])
    
    return deps


def sort_packages_by_dependency_order(packages: list[WorkspacePackage]) -> list[WorkspacePackage]:
    """Sort packages so that dependencies come before dependents.
    
    Uses topological sort to ensure packages are started in the right order.
    """
    all_by_name = {pkg.name: pkg for pkg in packages}
    visited: set[str] = set()
    result: list[WorkspacePackage] = []
    
    def visit(pkg: WorkspacePackage) -> None:
        if pkg.name in visited:
            return
        visited.add(pkg.name)
        
        # Visit dependencies first
        for dep_name in list(pkg.dependencies.keys()) + list(pkg.dev_dependencies.keys()):
            if dep_name in all_by_name:
                visit(all_by_name[dep_name])
        
        result.append(pkg)
    
    for pkg in packages:
        visit(pkg)
    
    return result


__all__ = [
    "WorkspacePackage",
    "find_workspace_root",
    "discover_workspace_packages", 
    "find_packages_with_script",
    "get_package_dependencies",
    "sort_packages_by_dependency_order",
]
