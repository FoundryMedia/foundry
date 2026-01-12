from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol
import json
import re


class ServiceRuntime(str, Enum):
    spring_boot = "spring-boot"
    nextjs = "nextjs"
    fastapi = "fastapi"
    unknown = "unknown"


@dataclass(frozen=True)
class RuntimeMatch:
    runtime: ServiceRuntime
    evidence: str


class ServiceRuntimeDetector(Protocol):
    name: str

    def detect(self, service_dir: Path) -> RuntimeMatch | None:  # pragma: no cover
        ...


class SpringBootDetector:
    name = "spring-boot"

    def detect(self, service_dir: Path) -> RuntimeMatch | None:
        pom = service_dir / "pom.xml"
        if not pom.exists():
            return None

        # Strong signal per your requirement: <parent> contains spring-boot-starter-parent
        try:
            text = pom.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"<parent>.*?<artifactId>spring-boot-starter-parent</artifactId>.*?</parent>", text, re.DOTALL):
                return RuntimeMatch(ServiceRuntime.spring_boot, "pom.xml: spring-boot-starter-parent")
        except Exception:
            pass

        # If pom exists but we can't confirm parent, don't claim Spring Boot.
        return None


class NextJsDetector:
    name = "nextjs"

    def detect(self, service_dir: Path) -> RuntimeMatch | None:
        pkg = service_dir / "package.json"
        if not pkg.exists():
            return None

        # Your requirement: package.json + next.config next to it.
        for cfg in ("next.config.ts", "next.config.js"):
            if (service_dir / cfg).exists():
                return RuntimeMatch(ServiceRuntime.nextjs, f"package.json + {cfg}")

        return None


class FastApiDetector:
    name = "fastapi"

    def detect(self, service_dir: Path) -> RuntimeMatch | None:
        req = service_dir / "requirements.txt"
        if not req.exists():
            return None

        try:
            content = req.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        # Look for a dependency line mentioning fastapi.
        # Handles: fastapi, fastapi==x.y, fastapi>=x, FastAPI (case-insensitive)
        for line in content.splitlines():
            s = line.strip().lower()
            if not s or s.startswith("#"):
                continue
            if s.startswith("fastapi"):
                return RuntimeMatch(ServiceRuntime.fastapi, "requirements.txt: fastapi")

        return None


DEFAULT_DETECTORS: tuple[ServiceRuntimeDetector, ...] = (
    SpringBootDetector(),
    NextJsDetector(),
    FastApiDetector(),
)


def detect_runtime(service_dir: Path, detectors: tuple[ServiceRuntimeDetector, ...] = DEFAULT_DETECTORS) -> RuntimeMatch:
    """Detect runtime using the first matching detector in order."""

    for det in detectors:
        match = det.detect(service_dir)
        if match is not None:
            return match

    return RuntimeMatch(ServiceRuntime.unknown, "no runtime detected")


__all__ = [
    "ServiceRuntime",
    "RuntimeMatch",
    "ServiceRuntimeDetector",
    "SpringBootDetector",
    "NextJsDetector",
    "FastApiDetector",
    "detect_runtime",
    "DEFAULT_DETECTORS",
]
