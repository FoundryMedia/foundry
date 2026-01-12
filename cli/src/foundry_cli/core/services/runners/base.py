from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Literal, Optional

from foundry_cli.core.project.workspace import DiscoveredService


StreamName = Literal["stdout", "stderr"]


@dataclass(frozen=True)
class ServiceLogEvent:
    service_name: str
    stream: StreamName
    line: str


class ServiceStatus(str):
    """Lifecycle status for a service in the "run" UI."""

    starting = "starting"
    healthy = "healthy"
    failed = "failed"


@dataclass(frozen=True)
class ServiceStatusEvent:
    """Status update emitted by a runner.

    - `detail` is human-readable (surface it in logs or debug panel).
    - `error` is a longer message for failures.
    """

    service_name: str
    status: ServiceStatus
    detail: str = ""
    error: Optional[str] = None


class ServiceRunner(abc.ABC):
    """Runs a single service.

    Contract:
    - `start()` spawns the process (or runtime-specific machinery).
    - `stop()` terminates it.
    - `events()` yields log lines tagged with stdout/stderr.

    Runtimes can subclass this later (Spring Boot / NextJS / FastAPI).
    """

    def __init__(self, service: DiscoveredService) -> None:
        self.service = service

    @property
    def name(self) -> str:
        return self.service.name

    @property
    def cwd(self) -> Path:
        return self.service.path

    @abc.abstractmethod
    async def start(self) -> None:  # pragma: no cover
        raise NotImplementedError

    @abc.abstractmethod
    async def stop(self) -> None:  # pragma: no cover
        raise NotImplementedError

    @abc.abstractmethod
    def events(self) -> AsyncIterator[ServiceLogEvent]:  # pragma: no cover
        raise NotImplementedError

    def status_events(self) -> AsyncIterator[ServiceStatusEvent]:  # pragma: no cover
        """Optional status stream.

        Default: emit nothing.

        Runners that support readiness checks should override this.
        """

        async def _empty() -> AsyncIterator[ServiceStatusEvent]:
            if False:  # pragma: no cover
                yield None  # type: ignore[misc]
            return

        return _empty()
