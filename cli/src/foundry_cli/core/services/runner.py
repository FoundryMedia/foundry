from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Literal

from foundry_cli.core.project.workspace import DiscoveredService


StreamName = Literal["stdout", "stderr"]


@dataclass(frozen=True)
class ServiceLogEvent:
    service_name: str
    stream: StreamName
    line: str


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
