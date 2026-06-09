"""Service runtime and package manager detection for Foundry CLI.

Provides:

- **ServiceRuntime** — enum of runtime/framework types Foundry can manage
- **PackageManager** — enum of package managers Foundry can detect
- **detect_runtime()** — identify the runtime of a service directory
- **detect_package_manager()** — identify the build tool for a service directory
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import re


class ServiceRuntime(str, Enum):
    """Runtime types that Foundry can detect and manage.

    Values correspond to the ``type`` field in ``foundry.json`` service entries.
    """
    spring_boot = "spring-boot"
    nextjs = "nextjs"
    vite = "vite"
    uvicorn = "uvicorn"
    gunicorn = "gunicorn"
    express = "express"
    unknown = "unknown"

    # Backward-compat alias — FastAPI apps run via uvicorn.
    # Python enum treats duplicate values as aliases; ``ServiceRuntime.fastapi``
    # resolves to ``ServiceRuntime.uvicorn``.
    fastapi = "uvicorn"


class PackageManager(str, Enum):
    """Package managers Foundry can detect from filesystem markers."""
    maven = "maven"
    gradle = "gradle"
    pnpm = "pnpm"
    npm = "npm"
    yarn = "yarn"
    pip = "pip"
    poetry = "poetry"
    uv = "uv"
    unknown = "unknown"


@dataclass(frozen=True)
class RuntimeMatch:
    """Result of a runtime detection probe."""
    runtime: ServiceRuntime
    evidence: str


class ServiceRuntimeDetector(Protocol):
    """Protocol for runtime detectors."""
    name: str

    def detect(self, service_dir: Path) -> RuntimeMatch | None:  # pragma: no cover
        ...


# ---------------------------------------------------------------------------
# Runtime Detectors
# ---------------------------------------------------------------------------

class SpringBootDetector:
    name = "spring-boot"

    def detect(self, service_dir: Path) -> RuntimeMatch | None:
        pom = service_dir / "pom.xml"
        if not pom.exists():
            return None
        try:
            text = pom.read_text(encoding="utf-8", errors="ignore")
            if re.search(
                r"<parent>.*?<artifactId>spring-boot-starter-parent</artifactId>.*?</parent>",
                text,
                re.DOTALL,
            ):
                return RuntimeMatch(ServiceRuntime.spring_boot, "pom.xml: spring-boot-starter-parent")
        except Exception:
            pass
        return None


class NextJsDetector:
    name = "nextjs"

    def detect(self, service_dir: Path) -> RuntimeMatch | None:
        pkg = service_dir / "package.json"
        if not pkg.exists():
            return None
        for cfg in ("next.config.ts", "next.config.js", "next.config.mjs"):
            if (service_dir / cfg).exists():
                return RuntimeMatch(ServiceRuntime.nextjs, f"package.json + {cfg}")
        return None


class ViteDetector:
    name = "vite"

    def detect(self, service_dir: Path) -> RuntimeMatch | None:
        pkg = service_dir / "package.json"
        if not pkg.exists():
            return None
        for cfg in ("vite.config.ts", "vite.config.js", "vite.config.mjs"):
            if (service_dir / cfg).exists():
                return RuntimeMatch(ServiceRuntime.vite, f"package.json + {cfg}")
        return None


class UvicornDetector:
    """Detect Python services that run via uvicorn (FastAPI, Starlette, etc.)."""
    name = "uvicorn"

    def detect(self, service_dir: Path) -> RuntimeMatch | None:
        for req_file in ("requirements.txt", "pyproject.toml"):
            path = service_dir / req_file
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                continue
            if "uvicorn" in content or "fastapi" in content:
                return RuntimeMatch(ServiceRuntime.uvicorn, f"{req_file}: uvicorn/fastapi")
        return None


DEFAULT_DETECTORS: tuple[ServiceRuntimeDetector, ...] = (
    SpringBootDetector(),
    NextJsDetector(),
    ViteDetector(),
    UvicornDetector(),
)


def detect_runtime(
    service_dir: Path,
    detectors: tuple[ServiceRuntimeDetector, ...] = DEFAULT_DETECTORS,
) -> RuntimeMatch:
    """Detect runtime using the first matching detector in order."""
    for det in detectors:
        match = det.detect(service_dir)
        if match is not None:
            return match
    return RuntimeMatch(ServiceRuntime.unknown, "no runtime detected")


# ---------------------------------------------------------------------------
# Package Manager Detection
# ---------------------------------------------------------------------------

def detect_package_manager(
    service_dir: Path,
    project_root: Path | None = None,
) -> PackageManager:
    """Detect the package manager for a service directory.

    Checks the service dir first for build files (``pom.xml``, ``build.gradle``,
    ``pyproject.toml``, ``requirements.txt``), then falls back to *project_root*
    for workspace-level lock files (``pnpm-lock.yaml``, ``yarn.lock``).
    """
    # Java
    if (service_dir / "pom.xml").exists():
        return PackageManager.maven
    if (service_dir / "build.gradle").exists() or (service_dir / "build.gradle.kts").exists():
        return PackageManager.gradle

    # Python
    pyproject = service_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="ignore")
            if "[tool.poetry]" in text:
                return PackageManager.poetry
        except Exception:
            pass
        return PackageManager.pip
    if (service_dir / "requirements.txt").exists():
        return PackageManager.pip

    # Node — check project root for workspace lock files, then service dir
    roots = [service_dir]
    if project_root and project_root.resolve() != service_dir.resolve():
        roots.append(project_root)

    for root in roots:
        if (root / "pnpm-lock.yaml").exists():
            return PackageManager.pnpm
        if (root / "yarn.lock").exists():
            return PackageManager.yarn
        if (root / "package-lock.json").exists():
            return PackageManager.npm

    # Bare package.json → assume npm
    if (service_dir / "package.json").exists():
        return PackageManager.npm

    return PackageManager.unknown


__all__ = [
    "ServiceRuntime",
    "PackageManager",
    "RuntimeMatch",
    "ServiceRuntimeDetector",
    "SpringBootDetector",
    "NextJsDetector",
    "ViteDetector",
    "UvicornDetector",
    "detect_runtime",
    "detect_package_manager",
    "DEFAULT_DETECTORS",
]
