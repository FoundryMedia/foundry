"""Regression tests for the v0.12.0 macOS pilot defects (run dev / sshTunnels).

Locks: loopback-by-default tunnel binds + bindAddress opt-in, the ::1
dual-stack relay, init --dry-run never writing + fresh drift, run.script
honored verbatim for Spring Boot, the live-child registry, headless-mode
selection, and the headless all-failed fatal rule.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

from foundry_cli.commands.init import init
from foundry_cli.core.project import dev_env
from foundry_cli.core.project.manifest import ServiceConfig

# runners must import BEFORE ssh_tunnel (latent circular import — see
# .claude/rules/local-dev-env.md).
from foundry_cli.core.services.runners import process as process_mod
from foundry_cli.core.services.runners.java.spring_boot.maven import (
    SpringBootServiceRunner,
)
from foundry_cli.core.services.runners.tunnel_aware import TunnelAwareRunner
from foundry_cli.core.services import ssh_tunnel
from foundry_cli.core.ui.headless import (
    HeadlessServicesRunner,
    headless_mode_requested,
)

TUNNEL_BASE = {
    "localPort": 15432,
    "remoteHost": "db.internal",
    "remotePort": 5432,
    "host": "1.2.3.4",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ipv6_loopback_available() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Defect 1: loopback bind by default, bindAddress opt-in
# ---------------------------------------------------------------------------

def test_tunnel_config_defaults_to_loopback() -> None:
    cfg = ssh_tunnel.SshTunnelConfig.from_dict(dict(TUNNEL_BASE))
    assert cfg.bind_address is None
    assert cfg.bind_display == "127.0.0.1"


def test_tunnel_config_parses_bind_address() -> None:
    cfg = ssh_tunnel.SshTunnelConfig.from_dict(
        {**TUNNEL_BASE, "bindAddress": "0.0.0.0"}
    )
    assert cfg.bind_address == "0.0.0.0"
    assert cfg.bind_display == "0.0.0.0"


def test_manifest_tunnel_parses_bind_address() -> None:
    cfg = ServiceConfig.from_dict({
        "sshTunnels": {"db": {**TUNNEL_BASE, "bindAddress": "0.0.0.0"}}
    })
    assert cfg.ssh_tunnels["db"].bind_address == "0.0.0.0"
    # Default stays None (loopback).
    cfg2 = ServiceConfig.from_dict({"sshTunnels": {"db": dict(TUNNEL_BASE)}})
    assert cfg2.ssh_tunnels["db"].bind_address is None


def test_env_overlay_can_set_bind_address() -> None:
    cfg = ServiceConfig.from_dict({
        "sshTunnels": {"db": dict(TUNNEL_BASE)},
        "environments": {"docker": {"sshTunnels": {"db": {"bindAddress": "0.0.0.0"}}}},
    })
    merged = dev_env.apply_env_overlay(cfg, "docker")
    assert merged.ssh_tunnels["db"].bind_address == "0.0.0.0"
    # Other fields untouched by the field-level merge.
    assert merged.ssh_tunnels["db"].local_port == TUNNEL_BASE["localPort"]


def test_tunnel_aware_passes_bind_address_through() -> None:
    from foundry_cli.core.project.manifest import SshTunnelConfig as ManifestCfg

    inner = types.SimpleNamespace(name="api", display_name="api", cwd=Path("."), service=None)
    runner = TunnelAwareRunner(
        inner_runner=inner,  # type: ignore[arg-type]
        tunnel_configs={
            "db": ManifestCfg(**{
                "local_port": 15432, "remote_host": "db.internal",
                "remote_port": 5432, "host": "1.2.3.4",
                "bind_address": "0.0.0.0",
            })
        },
    )
    assert runner._tunnel_configs["db"].bind_address == "0.0.0.0"
    assert runner._tunnel_configs["db"].bind_display == "0.0.0.0"


def test_tunnel_rejects_ipv6_bind_address() -> None:
    cfg = ssh_tunnel.SshTunnelConfig.from_dict(
        {**TUNNEL_BASE, "localPort": _free_port(), "bindAddress": "::1"}
    )
    runner = ssh_tunnel.SshTunnelRunner("api", cfg)
    ok = asyncio.run(runner.start())
    assert ok is False


# ---------------------------------------------------------------------------
# Defect 2: dual-stack — the [::1] -> 127.0.0.1 relay
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _ipv6_loopback_available(), reason="no IPv6 loopback")
def test_v6_relay_roundtrip() -> None:
    async def _run() -> bytes:
        port = _free_port()

        async def upstream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            data = await reader.read(100)
            writer.write(b"echo:" + data)
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(upstream, host="127.0.0.1", port=port)
        relay = ssh_tunnel._LoopbackV6Relay(port)
        assert await relay.start() == "ok"
        try:
            reader, writer = await asyncio.open_connection("::1", port)
            writer.write(b"ping")
            await writer.drain()
            got = await asyncio.wait_for(reader.read(100), timeout=5)
            writer.close()
            return got
        finally:
            await relay.stop()
            server.close()
            await server.wait_closed()

    assert asyncio.run(_run()) == b"echo:ping"


def test_v6_relay_reports_held_port_as_in_use() -> None:
    async def _run() -> bool:
        port = _free_port()
        first = ssh_tunnel._LoopbackV6Relay(port)
        second = ssh_tunnel._LoopbackV6Relay(port)
        if await first.start() != "ok":
            return False  # no IPv6 — nothing to assert
        try:
            assert await second.start() == "in-use"
        finally:
            await first.stop()
        return True

    asyncio.run(_run())


def test_tunnel_fails_fast_when_local_port_held() -> None:
    """A localPort already held by ANOTHER process is a hard error — the old
    behavior reported the squatter as an active tunnel (healthy)."""
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)
    port = squatter.getsockname()[1]
    try:
        cfg = ssh_tunnel.SshTunnelConfig.from_dict({**TUNNEL_BASE, "localPort": port})
        runner = ssh_tunnel.SshTunnelRunner("api", cfg)

        async def _run():
            ok = await runner.start()
            events = []
            while not runner._status_queue.empty():
                events.append(runner._status_queue.get_nowait())
            return ok, events

        ok, events = asyncio.run(_run())
        assert ok is False
        failed = [e for e in events if e.status == "failed"]
        assert failed and "already in use" in (failed[-1].error or "")
    finally:
        squatter.close()


# ---------------------------------------------------------------------------
# Defect 3: init --dry-run writes nothing; drift is computed fresh
# ---------------------------------------------------------------------------

@pytest.fixture()
def in_tmp_repo(tmp_path: Path):
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _write_dotfoundry_manifest(root: Path, *, path_value=None) -> None:
    svc: dict = {"stack": {"type": "backend", "framework": "spring-boot", "language": "java"}}
    if path_value is not None:
        svc["path"] = path_value
    manifest = {
        "schemaVersion": "0.7.0",
        "name": "svc",
        "services": {"svc": svc},
    }
    (root / ".foundry").mkdir(exist_ok=True)
    (root / ".foundry" / "foundry.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def test_init_dry_run_writes_nothing(in_tmp_repo: Path) -> None:
    _write_dotfoundry_manifest(in_tmp_repo)  # no path key -> would drift
    result = CliRunner().invoke(init, ["--dry-run"])
    assert result.exit_code == 0, result.output
    assert not (in_tmp_repo / ".foundry" / "workspace.yml").exists()
    assert not (in_tmp_repo / ".foundry" / ".gitignore").exists()
    assert not (in_tmp_repo / ".gitignore").exists()


def test_init_recomputes_drift_from_manifest_not_cache(in_tmp_repo: Path) -> None:
    # 1. Manifest without path -> real init caches a missing-drift workspace.yml
    _write_dotfoundry_manifest(in_tmp_repo)
    first = CliRunner().invoke(init, [])
    assert first.exit_code == 0, first.output
    assert "Drift" in first.output
    assert (in_tmp_repo / ".foundry" / "workspace.yml").exists()

    # 2. Fix the manifest (path "."), re-run WITHOUT --force: the stale
    #    cached drift must not be echoed back.
    _write_dotfoundry_manifest(in_tmp_repo, path_value=".")
    second = CliRunner().invoke(init, ["--dry-run"])
    assert second.exit_code == 0, second.output
    assert "Drift" not in second.output
    assert "missing" not in second.output.lower()


def test_workspace_resolves_empty_path_as_repo_root(in_tmp_repo: Path) -> None:
    from foundry_cli.core.project.manifest import load_manifest_from_path
    from foundry_cli.core.project.workspace_config import resolve_workspace

    _write_dotfoundry_manifest(in_tmp_repo, path_value="")
    manifest = load_manifest_from_path(in_tmp_repo / ".foundry" / "foundry.json")
    ws = resolve_workspace(in_tmp_repo, manifest)
    assert ws["services"]["svc"] is not None
    assert not ws.get("drift", {}).get("missing")


# ---------------------------------------------------------------------------
# Defect 4: run.script honored verbatim for Spring Boot
# ---------------------------------------------------------------------------

class _FakeProc:
    pid = 4242
    returncode = None

    async def wait(self) -> None:  # pragma: no cover - cancelled in test
        await asyncio.Event().wait()


def _fake_service(tmp_path: Path):
    return types.SimpleNamespace(name="svc", path=tmp_path)


def test_spring_boot_script_runs_verbatim(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    async def fake_spawn(self, argv, *, cwd=None, env=None):
        captured["argv"] = list(argv)
        captured["env"] = env
        return _FakeProc()

    monkeypatch.setattr(SpringBootServiceRunner, "_spawn", fake_spawn)

    runner = SpringBootServiceRunner(
        _fake_service(tmp_path),
        port=None,  # skip readiness polling
        actuator_port=None,
        script="mvn spring-boot:run -s settings.xml",
        args=(),
    )

    async def _run() -> None:
        await runner.start()
        if runner._process_monitor_task is not None:
            runner._process_monitor_task.cancel()
            try:
                await runner._process_monitor_task
            except asyncio.CancelledError:
                pass

    asyncio.run(_run())

    assert captured["argv"] == ["mvn", "spring-boot:run", "-s", "settings.xml"]
    assert "-q" not in captured["argv"]
    assert "-o" not in captured["argv"]


def test_spring_boot_script_appends_run_args(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    async def fake_spawn(self, argv, *, cwd=None, env=None):
        captured["argv"] = list(argv)
        return _FakeProc()

    monkeypatch.setattr(SpringBootServiceRunner, "_spawn", fake_spawn)

    runner = SpringBootServiceRunner(
        _fake_service(tmp_path),
        port=None,
        actuator_port=None,
        script="mvn spring-boot:run",
        args=("-Dspring-boot.run.profiles=local",),
    )

    async def _run() -> None:
        await runner.start()
        if runner._process_monitor_task is not None:
            runner._process_monitor_task.cancel()
            try:
                await runner._process_monitor_task
            except asyncio.CancelledError:
                pass

    asyncio.run(_run())
    assert captured["argv"] == [
        "mvn", "spring-boot:run", "-Dspring-boot.run.profiles=local",
    ]


# ---------------------------------------------------------------------------
# Defect 5: live-child registry
# ---------------------------------------------------------------------------

def test_kill_all_live_children_is_safe_on_dead_pids() -> None:
    process_mod._register_live_pid(2 ** 22 + 12345)  # certainly not alive
    process_mod.kill_all_live_children(force_after=0.0)
    assert not process_mod._LIVE_PIDS


def test_posix_spawn_uses_new_session() -> None:
    if sys.platform == "win32":
        pytest.skip("POSIX-only: start_new_session")
    import inspect

    src = inspect.getsource(process_mod.ProcessBackedRunner._spawn)
    assert "start_new_session" in src


# ---------------------------------------------------------------------------
# Defect 6/7: headless selection + fatal-failure exit rule
# ---------------------------------------------------------------------------

def test_headless_mode_selection(monkeypatch) -> None:
    monkeypatch.delenv("FOUNDRY_NO_TUI", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    assert headless_mode_requested(True) is True
    assert headless_mode_requested(False) is False
    monkeypatch.setenv("FOUNDRY_NO_TUI", "1")
    assert headless_mode_requested(False) is True
    monkeypatch.delenv("FOUNDRY_NO_TUI")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    assert headless_mode_requested(False) is True


def test_headless_all_failed_is_fatal() -> None:
    from foundry_cli.core.services.runners.base import ServiceStatus, ServiceStatusEvent

    services = [
        types.SimpleNamespace(name="api"),
        types.SimpleNamespace(name="auth"),
        types.SimpleNamespace(name="api/sidecar"),
    ]
    runners = {s.name: object() for s in services}
    h = HeadlessServicesRunner(services, runners)  # type: ignore[arg-type]

    h._on_status(ServiceStatusEvent("api", ServiceStatus.failed, error="boom"))
    assert h._fatal is False  # auth still starting

    h._on_status(ServiceStatusEvent("auth", ServiceStatus.failed, error="boom"))
    assert h._fatal is True  # sidecars don't block the verdict


def test_headless_healthy_service_prevents_fatal() -> None:
    from foundry_cli.core.services.runners.base import ServiceStatus, ServiceStatusEvent

    services = [types.SimpleNamespace(name="api"), types.SimpleNamespace(name="auth")]
    runners = {s.name: object() for s in services}
    h = HeadlessServicesRunner(services, runners)  # type: ignore[arg-type]

    h._on_status(ServiceStatusEvent("api", ServiceStatus.healthy, detail="up"))
    h._on_status(ServiceStatusEvent("auth", ServiceStatus.failed, error="boom"))
    assert h._fatal is False
