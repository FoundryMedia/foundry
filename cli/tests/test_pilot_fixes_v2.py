"""Regression tests for the v0.13.0 pilot follow-ups (macOS).

Locks: platform-aware Maven wrapper detection (+ system mvn fallback), a
launch failure is a FAILED status (never a silent hang), the sshtunnel/
paramiko log routing with the passphrase-key rewrite, and the published
foundry.workspace.json schema.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import types
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

# runners must import BEFORE ssh_tunnel (latent circular import).
from foundry_cli.core.services.runners import process as process_mod
from foundry_cli.core.services.runners.base import (
    ServiceLaunchError,
    ServiceStatus,
    ServiceStatusEvent,
)
from foundry_cli.core.services.runners.java.spring_boot import maven
from foundry_cli.core.services import ssh_tunnel
from foundry_cli.core.ui.headless import HeadlessServicesRunner

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Maven wrapper detection is platform-aware
# ---------------------------------------------------------------------------

def _touch(p: Path, mode: int | None = None) -> Path:
    p.write_text("#!/bin/sh\n", encoding="utf-8")
    if mode is not None and sys.platform != "win32":
        os.chmod(p, mode)
    return p


def test_posix_prefers_executable_mvnw_over_cmd(tmp_path: Path, monkeypatch) -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX mode bits")
    monkeypatch.setattr(maven.sys, "platform", "darwin")
    _touch(tmp_path / "mvnw.cmd", 0o644)
    _touch(tmp_path / "mvnw", 0o755)
    found = maven._find_mvnw(tmp_path)
    assert found is not None and found.name == "mvnw"


def test_posix_never_picks_mvnw_cmd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maven.sys, "platform", "darwin")
    _touch(tmp_path / "mvnw.cmd")
    # Only the Windows wrapper exists -> no wrapper for this platform.
    assert maven._find_mvnw(tmp_path) is None


def test_windows_prefers_mvnw_cmd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maven.sys, "platform", "win32")
    _touch(tmp_path / "mvnw")
    _touch(tmp_path / "mvnw.cmd")
    found = maven._find_mvnw(tmp_path)
    assert found is not None and found.name == "mvnw.cmd"


def test_system_mvn_fallback_when_no_wrapper(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maven.sys, "platform", "darwin")
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/local/bin/mvn" if name == "mvn" else None
    )
    launcher, label = maven._find_maven_launcher(tmp_path)
    assert launcher == ["/usr/local/bin/mvn"]
    assert "system" in label


def test_no_launcher_is_a_clear_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maven.sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    launcher, reason = maven._find_maven_launcher(tmp_path)
    assert launcher is None
    assert "./mvnw" in reason and "mvn" in reason and "run.script" in reason


# ---------------------------------------------------------------------------
# 2. A failed launch is a FAILED status, and the drivers never hang on it
# ---------------------------------------------------------------------------

class _Svc(process_mod.ProcessBackedRunner):
    async def start(self) -> None:
        await self._spawn(["/definitely/not/a/binary-xyz"], cwd=self.cwd)


def test_spawn_failure_emits_failed_status_and_raises(tmp_path: Path) -> None:
    runner = _Svc(types.SimpleNamespace(name="svc", path=tmp_path))

    async def _run():
        with pytest.raises(ServiceLaunchError):
            await runner.start()
        events = []
        while not runner._status_queue.empty():
            events.append(runner._status_queue.get_nowait())
        return events

    events = asyncio.run(_run())
    failed = [e for e in events if e.status == ServiceStatus.failed]
    assert failed, "spawn failure must produce a failed status event"
    assert "Cannot launch" in (failed[-1].error or "")


def test_headless_guarded_start_turns_exception_into_fatal() -> None:
    class _Boom:
        name = "api"

        async def start(self):
            raise RuntimeError("kaboom")

    services = [types.SimpleNamespace(name="api")]
    h = HeadlessServicesRunner(services, {"api": _Boom()})  # type: ignore[arg-type]

    async def _run():
        h._stop_event = asyncio.Event()
        await h._guarded_start(h._runners["api"])
        return h._fatal, h._stop_event.is_set()

    fatal, stopped = asyncio.run(_run())
    assert fatal is True and stopped is True


def test_headless_guarded_start_skips_duplicate_for_launch_error() -> None:
    """A ServiceLaunchError already carried its own failed status; the guard
    must not overwrite it with a vaguer one."""
    seen: list[ServiceStatusEvent] = []

    class _Launch:
        name = "api"

        async def start(self):
            raise ServiceLaunchError("Cannot launch x: No such file")

    h = HeadlessServicesRunner(
        [types.SimpleNamespace(name="api")], {"api": _Launch()}  # type: ignore[arg-type]
    )
    h._on_status = lambda ev: seen.append(ev)  # type: ignore[method-assign]
    asyncio.run(h._guarded_start(h._runners["api"]))
    assert seen == []


# ---------------------------------------------------------------------------
# 3. sshtunnel/paramiko records route through the tunnel's queue
# ---------------------------------------------------------------------------

def _rec(level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord("sshtunnel", level, __file__, 1, msg, None, None)


def test_lib_log_handler_rewrites_passphrase_error_to_debug() -> None:
    async def _run():
        q: asyncio.Queue = asyncio.Queue()
        h = ssh_tunnel._TunnelLibLogHandler(
            asyncio.get_running_loop(), q, "svc", "[tunnel:db]"
        )
        h.emit(_rec(logging.ERROR, "Password is required for key /Users/home/.ssh/id_ed25519"))
        # A genuine error is forwarded, labelled.
        h.emit(_rec(logging.ERROR, "Could not establish session to SSH gateway"))
        # INFO chatter is dropped.
        h.emit(_rec(logging.INFO, "Opening tunnel"))
        await asyncio.sleep(0)  # let call_soon_threadsafe callbacks run
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out

    events = asyncio.run(_run())
    assert len(events) == 2
    assert events[0].level == "DEBUG"
    assert "passphrase-protected" in events[0].line and "ssh-agent" in events[0].line
    assert events[0].line.startswith("[tunnel:db] ")
    assert events[1].level == "ERROR" and events[1].line.startswith("[tunnel:db] ")


def test_tunnel_runner_lines_carry_label() -> None:
    cfg = ssh_tunnel.SshTunnelConfig.from_dict({
        "localPort": 1, "remoteHost": "db", "remotePort": 5432, "host": "h",
    })
    r = ssh_tunnel.SshTunnelRunner("svc", cfg, tunnel_name="db")
    assert r.label == "[tunnel:db]"
    legacy = ssh_tunnel.SshTunnelRunner("svc", cfg, tunnel_name="default")
    assert legacy.label == "[tunnel]"

    async def _run():
        await r._log("hello")
        return r._log_queue.get_nowait()

    assert asyncio.run(_run()).line == "[tunnel:db] hello"


# ---------------------------------------------------------------------------
# 4. foundry.workspace.json has a published schema that matches the loader
# ---------------------------------------------------------------------------

def test_workspace_schema_accepts_example_and_matches_loader(tmp_path: Path) -> None:
    from foundry_cli.core.project.workspace import load_workspace_file

    schema = json.loads(
        (REPO_ROOT / "foundry.workspace.schema.json").read_text(encoding="utf-8")
    )
    Draft7Validator.check_schema(schema)
    v = Draft7Validator(schema)
    for example in schema["examples"]:
        assert not list(v.iter_errors(example))
        p = tmp_path / "foundry.workspace.json"
        p.write_text(json.dumps(example), encoding="utf-8")
        ws = load_workspace_file(p)
        assert set(ws.profiles) == set(example["profiles"])

    # Things the loader rejects, the schema rejects too.
    assert list(v.iter_errors({"profiles": {"core": ["a"]}}))  # repos required
    assert list(v.iter_errors({"repos": ["a"], "profiles": {"core": "a"}}))  # not a list
