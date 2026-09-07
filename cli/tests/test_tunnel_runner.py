"""TunnelAwareRunner multi-tunnel semantics: all-or-nothing start, full teardown."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from foundry_cli.core.project.manifest import SshTunnelConfig
from foundry_cli.core.services.runners import tunnel_aware


class _FakeInner:
    """Minimal stand-in for a ServiceRunner."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    name = "api"
    display_name = "api"
    cwd = Path(".")
    service = None

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def events(self):
        async def _gen():
            if False:  # pragma: no cover
                yield None
        return _gen()

    def status_events(self):
        async def _gen():
            if False:  # pragma: no cover
                yield None
        return _gen()


class _FakeTunnel:
    """Records start/stop; failure controlled by the tunnel name."""

    instances: list["_FakeTunnel"] = []

    def __init__(self, service_name, config, workspace_root=None, log_queue=None, tunnel_name=None):
        self.tunnel_name = tunnel_name
        self.started = False
        self.stopped = False
        _FakeTunnel.instances.append(self)

    async def start(self) -> bool:
        self.started = True
        return self.tunnel_name != "bad"

    async def stop(self) -> None:
        self.stopped = True


def _tunnels(names: list[str]) -> dict[str, SshTunnelConfig]:
    return {
        n: SshTunnelConfig(
            local_port=15000 + i, remote_host="r", remote_port=5432, host="h"
        )
        for i, n in enumerate(names)
    }


@pytest.fixture(autouse=True)
def _fake_tunnel(monkeypatch: pytest.MonkeyPatch):
    _FakeTunnel.instances = []
    monkeypatch.setattr(tunnel_aware, "SshTunnelRunner", _FakeTunnel)


def test_all_tunnels_up_then_service_starts() -> None:
    inner = _FakeInner()
    runner = tunnel_aware.TunnelAwareRunner(inner, _tunnels(["auth", "db1", "db2"]))
    asyncio.run(runner.start())
    assert inner.started is True
    assert len(_FakeTunnel.instances) == 3
    assert all(t.started for t in _FakeTunnel.instances)


def test_one_tunnel_failure_stops_the_rest_and_blocks_service() -> None:
    inner = _FakeInner()
    runner = tunnel_aware.TunnelAwareRunner(inner, _tunnels(["auth", "bad", "db2"]))
    asyncio.run(runner.start())
    assert inner.started is False  # service never starts on partial tunnels
    # every opened tunnel was torn down — no half-open state left behind
    assert all(t.stopped for t in _FakeTunnel.instances)


def test_stop_closes_all_tunnels() -> None:
    inner = _FakeInner()
    runner = tunnel_aware.TunnelAwareRunner(inner, _tunnels(["auth", "db1"]))
    asyncio.run(runner.start())
    asyncio.run(runner.stop())
    assert inner.stopped is True
    assert all(t.stopped for t in _FakeTunnel.instances)
