"""A DECLARED service is never silently dropped (pilot round 3, 2026-09-07).

`load_workspace` used to drop declared services whose detected runtime was
nextjs/unknown, expecting Node package discovery to re-find them — which
finds nothing in an aggregator directory with no root package.json, and
never found a package lacking a `<command>` script. An nx frontend (no
vite.config at its root → runtime unknown) vanished: 7 declared, 6 run, no
warning. These tests pin: declared services stay, unrunnable ones fail
LOUDLY, missing directories produce a notice, and a Node `run.script` that
is not a package.json script name runs verbatim with node_modules/.bin on
PATH.
"""
from __future__ import annotations

import asyncio
import json
import os
import types
from pathlib import Path

import pytest

from foundry_cli.core.project.service_runtime import RuntimeMatch, ServiceRuntime
from foundry_cli.core.project.workspace import (
    DiscoveredService,
    ServiceKind,
    load_workspace,
)
from foundry_cli.core.services import factory
from foundry_cli.core.services.runners import base
from foundry_cli.core.services.runners.node import nextjs
from foundry_cli.core.services.runners.script import ScriptServiceRunner


def _aggregator(tmp_path: Path, services: dict) -> Path:
    (tmp_path / ".foundry").mkdir()
    (tmp_path / ".foundry" / "foundry.json").write_text(
        json.dumps({"schemaVersion": "0.7.0", "name": "agg", "services": services}),
        encoding="utf-8",
    )
    return tmp_path


def _nx_frontend(root: Path, name: str, scripts: dict | None = None) -> Path:
    d = root / name
    d.mkdir()
    (d / "package.json").write_text(
        json.dumps({"name": name, "scripts": scripts or {"auth": "aws codeartifact login"}}),
        encoding="utf-8",
    )
    (d / "nx.json").write_text("{}", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def test_declared_frontend_without_dev_script_is_kept(tmp_path: Path) -> None:
    root = _aggregator(tmp_path, {
        "frontend-portal": {
            "path": "frontend-portal",
            "stack": {"type": "frontend", "framework": "vite", "language": "typescript"},
            "run": {"port": 4200, "script": "nx serve enterprise"},
        },
    })
    _nx_frontend(root, "frontend-portal")
    ws, _root, services, _sidecars = load_workspace(start=root, command="dev")
    names = [s.name for s in services]
    assert names == ["frontend-portal"]
    assert services[0].runtime.runtime == ServiceRuntime.unknown  # nx: no vite.config at root
    assert ws.notices == ()


def test_missing_declared_directory_produces_a_notice(tmp_path: Path) -> None:
    root = _aggregator(tmp_path, {
        "present": {"path": "present", "stack": {"type": "frontend", "framework": "vite"}},
        "ghost": {"path": "ghost", "stack": {"type": "backend", "framework": "spring-boot"}},
    })
    _nx_frontend(root, "present")
    ws, _root, services, _ = load_workspace(start=root, command="dev")
    assert [s.name for s in services] == ["present"]
    assert len(ws.notices) == 1
    assert "'ghost'" in ws.notices[0] and "does not exist" in ws.notices[0]


# ---------------------------------------------------------------------------
# Runner routing for undetected runtimes
# ---------------------------------------------------------------------------

def _svc(path: Path, cfg_data: dict, name: str = "svc") -> DiscoveredService:
    from foundry_cli.core.project.manifest import ServiceConfig

    return DiscoveredService(
        name=name,
        path=path,
        runtime=RuntimeMatch(ServiceRuntime.unknown, "no runtime detected"),
        kind=ServiceKind.frontend,
        config=ServiceConfig.from_dict(cfg_data),
    )


def test_unknown_runtime_with_package_json_routes_to_node_runner(tmp_path: Path) -> None:
    d = _nx_frontend(tmp_path, "fe")
    runner = factory.create_runner(
        _svc(d, {"run": {"port": 4200, "script": "nx serve enterprise"}}),
        command="dev", workspace_root=tmp_path,
    )
    assert isinstance(runner, nextjs.NodeServiceRunner)


def test_unknown_runtime_with_script_only_routes_to_script_runner(tmp_path: Path) -> None:
    d = tmp_path / "svc"
    d.mkdir()
    runner = factory.create_runner(
        _svc(d, {"run": {"script": "./start.sh --port 9000", "port": 9000}}),
        command="dev", workspace_root=tmp_path,
    )
    assert isinstance(runner, ScriptServiceRunner)


def test_unrunnable_declared_service_fails_loudly(tmp_path: Path) -> None:
    d = tmp_path / "svc"
    d.mkdir()
    runner = factory.create_runner(_svc(d, {}), command="dev", workspace_root=tmp_path)
    assert isinstance(runner, factory._UnsupportedServiceRunner)

    async def _run():
        await runner.start()
        gen = runner.status_events()
        return await asyncio.wait_for(gen.__anext__(), timeout=2)

    ev = asyncio.run(_run())
    assert ev.status == base.ServiceStatus.failed
    assert "run.script" in (ev.error or "")


# ---------------------------------------------------------------------------
# Node run.script: package.json script name, else a verbatim command
# ---------------------------------------------------------------------------

class _FakeProc:
    pid = 4242
    returncode = None

    async def wait(self):  # pragma: no cover - cancelled in test
        await asyncio.Event().wait()


async def _drain(runner) -> list:
    if runner._process_monitor_task is not None:
        runner._process_monitor_task.cancel()
        try:
            await runner._process_monitor_task
        except asyncio.CancelledError:
            pass
    out = []
    while not runner._status_queue.empty():
        out.append(runner._status_queue.get_nowait())
    return out


def test_node_script_not_in_package_json_runs_verbatim(tmp_path: Path, monkeypatch) -> None:
    d = _nx_frontend(tmp_path, "fe")
    (d / "node_modules" / ".bin").mkdir(parents=True)
    captured: dict = {}

    async def fake_spawn(self, argv, *, cwd=None, env=None):
        captured["argv"] = list(argv)
        captured["cwd"] = cwd
        captured["env"] = env
        return _FakeProc()

    monkeypatch.setattr(nextjs.NodeServiceRunner, "_spawn", fake_spawn)
    monkeypatch.setattr(nextjs, "STARTUP_TIMEOUT_S", 0.3)

    runner = nextjs.NodeServiceRunner(
        types.SimpleNamespace(name="fe", path=d),
        port=None, command="dev", script="nx serve enterprise", args=("--open=false",),
    )

    async def _run():
        await runner.start()
        return await _drain(runner)

    events = asyncio.run(_run())
    assert captured["argv"] == ["nx", "serve", "enterprise", "--open=false"]
    assert captured["cwd"] == d
    assert str(d / "node_modules" / ".bin") == captured["env"]["PATH"].split(os.pathsep)[0]
    assert not [e for e in events if e.status == base.ServiceStatus.failed]


def test_node_script_name_still_uses_package_manager(tmp_path: Path, monkeypatch) -> None:
    d = _nx_frontend(tmp_path, "fe", scripts={"dev": "vite"})
    captured: dict = {}

    async def fake_spawn(self, argv, *, cwd=None, env=None):
        captured["argv"] = list(argv)
        return _FakeProc()

    monkeypatch.setattr(nextjs.NodeServiceRunner, "_spawn", fake_spawn)
    monkeypatch.setattr(nextjs, "STARTUP_TIMEOUT_S", 0.3)
    runner = nextjs.NodeServiceRunner(
        types.SimpleNamespace(name="fe", path=d), port=None, command="dev", script="dev"
    )

    async def _run():
        await runner.start()
        await _drain(runner)

    asyncio.run(_run())
    assert captured["argv"][-2:] == ["run", "dev"]  # npm/pnpm run dev, never verbatim


def test_node_default_dev_missing_is_a_guided_failure(tmp_path: Path) -> None:
    d = _nx_frontend(tmp_path, "fe")  # only an 'auth' script, no run.script
    runner = nextjs.NodeServiceRunner(
        types.SimpleNamespace(name="fe", path=d), port=None, command="dev"
    )

    async def _run():
        await runner.start()
        return await _drain(runner)

    events = asyncio.run(_run())
    failed = [e for e in events if e.status == base.ServiceStatus.failed]
    assert failed and "run.script" in (failed[-1].error or "")
