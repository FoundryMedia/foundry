"""SSH tunnel management for Foundry services using pure Python (paramiko/sshtunnel).

Allows services to declare SSH tunnels that must be established before
the service starts (e.g., for database access through an SSH host).

This implementation uses the `sshtunnel` library (wrapping paramiko) for
cross-platform SSH tunneling without requiring system SSH binaries.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundry_cli.core.services.runners.base import ServiceLogEvent, ServiceStatus, ServiceStatusEvent


# Suppress verbose paramiko/sshtunnel logging
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("sshtunnel").setLevel(logging.WARNING)


_PASSPHRASE_KEY_RE = re.compile(r"Password is required for key\s+(?P<path>\S.*)$")


class _TunnelLibLogHandler(logging.Handler):
    """Route sshtunnel/paramiko records into the tunnel's own log stream.

    Without this, sshtunnel attaches a bare StreamHandler: its lines land on
    stderr UNPREFIXED (escaping the ``[service]`` tagging that makes
    ``--no-tui`` parseable), and its key scan logs
    ``ERROR Password is required for key ~/.ssh/id_ed25519`` on every
    SUCCESSFUL agent-authenticated run — a non-fatal fallback reported as
    an error. Here that one is rewritten to a DEBUG line saying what
    actually happens; everything else WARNING+ is forwarded with the
    tunnel label; chatter below WARNING is dropped.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: "asyncio.Queue[ServiceLogEvent]",
        service_name: str,
        label: str,
    ) -> None:
        super().__init__(level=logging.DEBUG)
        self._loop = loop
        self._queue = queue
        self._service_name = service_name
        self._label = label

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return
        m = _PASSPHRASE_KEY_RE.search(msg)
        if m:
            msg = (
                f"key {m.group('path').strip()} is passphrase-protected, "
                "falling back to ssh-agent"
            )
            level = "DEBUG"
        elif record.levelno >= logging.ERROR:
            level = "ERROR"
        elif record.levelno >= logging.WARNING:
            level = "WARN"
        else:
            return
        event = ServiceLogEvent(
            service_name=self._service_name,
            stream="stdout",
            line=f"{self._label} {msg}",
            level=level,
        )
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:
            pass  # loop closed during teardown


def load_ssh_pkey(key_file: str | Path):
    """Pre-load a private key into a paramiko PKey object.

    paramiko 4.x removed DSSKey, but sshtunnel's ``read_private_key_file``
    still references it whenever it is handed a key *path* — so passing a
    string path crashes with ``AttributeError: module 'paramiko' has no
    attribute 'DSSKey'``. Handing SSHTunnelForwarder an already-loaded PKey
    object skips that code path entirely.

    Returns the PKey, or None if no supported loader accepts the file
    (callers fall back to the path-string behavior so the original error
    surfaces).
    """
    import paramiko

    loaders = [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey]
    for loader in loaders:
        try:
            return loader.from_private_key_file(str(key_file))
        except Exception:
            continue
    return None


@dataclass(frozen=True)
class SshTunnelConfig:
    """Configuration for an SSH tunnel.

    Models: ssh -i <key> -N -L <local_port>:<remote_host>:<remote_port> <user>@<host>
    """

    local_port: int
    remote_host: str
    remote_port: int
    host: str
    user: str = "ec2-user"
    password: str | None = None  # Path to private key (absolute or relative to manifest)
    # None = the safe default: 127.0.0.1 plus a [::1] relay so `-h localhost`
    # works on dual-stack hosts. A non-loopback value (e.g. "0.0.0.0" so Docker
    # containers can reach the tunnel via host.docker.internal) exposes the
    # tunnelled service to the network — explicit opt-in only.
    bind_address: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SshTunnelConfig":
        return cls(
            local_port=data["localPort"],
            remote_host=data["remoteHost"],
            remote_port=data["remotePort"],
            host=data["host"],
            user=data.get("user", "ec2-user"),
            password=data.get("password"),
            bind_address=data.get("bindAddress"),
        )

    @property
    def tunnel_spec(self) -> str:
        """Returns the -L argument value: local_port:remote_host:remote_port"""
        return f"{self.local_port}:{self.remote_host}:{self.remote_port}"

    @property
    def destination(self) -> str:
        """Returns the SSH destination: user@host"""
        return f"{self.user}@{self.host}"

    @property
    def bind_display(self) -> str:
        """The bind address as shown in logs."""
        return self.bind_address or "127.0.0.1"


def _is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_loopback(address: str) -> bool:
    return address in ("127.0.0.1", "localhost", "::1")


class _LoopbackV6Relay:
    """Tiny [::1]:port → 127.0.0.1:port relay.

    sshtunnel's forward server is AF_INET-only, so a tunnel bound to
    127.0.0.1 is invisible to clients that resolve ``localhost`` to ``::1``
    first (macOS default) — psql/JDBC then fail with connection-refused while
    ``ssh -L`` (which binds both loopbacks) works. This relay restores the
    dual-stack behavior without touching sshtunnel internals. Best-effort:
    hosts without IPv6 simply skip it.
    """

    def __init__(self, port: int) -> None:
        self._port = port
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> str:
        """Bind [::1]. Returns "ok", "in-use" (another process holds the
        port — a squatter the tunnel must NOT silently coexist with), or
        "unavailable" (no IPv6 on this host — skip, nothing to relay)."""
        import errno

        try:
            self._server = await asyncio.start_server(
                self._handle, host="::1", port=self._port
            )
            return "ok"
        except OSError as e:
            self._server = None
            if e.errno == errno.EADDRINUSE:
                return "in-use"
            return "unavailable"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            up_reader, up_writer = await asyncio.open_connection("127.0.0.1", self._port)
        except OSError:
            writer.close()
            return

        async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    chunk = await src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
                    await dst.drain()
            except (OSError, asyncio.CancelledError):
                pass
            finally:
                try:
                    dst.close()
                except Exception:
                    pass

        await asyncio.gather(
            _pump(reader, up_writer), _pump(up_reader, writer), return_exceptions=True
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None


class SshTunnelRunner:
    """Manages an SSH tunnel using sshtunnel (paramiko-based, pure Python).
    
    The tunnel is started before the service and kept running until the service stops.
    """

    def __init__(
        self,
        service_name: str,
        config: SshTunnelConfig,
        workspace_root: Path | None = None,
        log_queue: asyncio.Queue[ServiceLogEvent] | None = None,
        tunnel_name: str | None = None,
    ) -> None:
        self._service_name = service_name
        self._config = config
        self._workspace_root = workspace_root
        self._log_queue = log_queue or asyncio.Queue()
        self._status_queue: asyncio.Queue[ServiceStatusEvent] = asyncio.Queue()
        self._tunnel = None  # SSHTunnelForwarder instance
        self._tunnel_name = tunnel_name
        self._v6_relay: _LoopbackV6Relay | None = None
        self._lib_logger: logging.Logger | None = None

    @property
    def label(self) -> str:
        """The ``[tunnel:<name>]`` tag every line from this tunnel carries
        (the legacy lone tunnel keeps the bare ``[tunnel]``)."""
        if self._tunnel_name and self._tunnel_name != "default":
            return f"[tunnel:{self._tunnel_name}]"
        return "[tunnel]"

    def _make_lib_logger(self) -> logging.Logger:
        """A per-runner logger handed to sshtunnel so its (and paramiko's)
        records flow through our queue instead of a bare stderr handler.
        sshtunnel only attaches its console handler when the logger it is
        given has none — ours has one, so it never does."""
        logger = logging.getLogger(f"foundry.sshtunnel.{id(self)}")
        logger.handlers = [
            _TunnelLibLogHandler(
                asyncio.get_running_loop(),
                self._log_queue,
                self._service_name,
                self.label,
            )
        ]
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        return logger

    @property
    def name(self) -> str:
        # Named tunnels (multi-tunnel services) label their events;
        # the legacy single tunnel keeps the historical bare suffix.
        if self._tunnel_name and self._tunnel_name != "default":
            return f"{self._service_name}#tunnel:{self._tunnel_name}"
        return f"{self._service_name}#tunnel"

    @property
    def display_name(self) -> str:
        return f"SSH Tunnel ({self._config.local_port} -> {self._config.remote_host}:{self._config.remote_port})"

    def _resolve_password_path(self) -> Path | None:
        """Resolve the password (private key) file path.
        
        Resolution order:
        1. If absolute path, use as-is
        2. If relative, resolve relative to manifest (workspace_root)
        """
        if not self._config.password:
            return None
            
        path = Path(self._config.password)
        
        # If absolute, use as-is
        if path.is_absolute():
            return path if path.exists() else None
        
        # Relative paths are resolved relative to the manifest (workspace root)
        if self._workspace_root:
            manifest_relative_path = self._workspace_root / path
            if manifest_relative_path.exists():
                return manifest_relative_path
        
        return None

    async def _log(self, message: str, level: str = "INFO") -> None:
        """Emit a log event, tagged with this tunnel's label so every line
        stays attributable in ``--no-tui`` output."""
        await self._log_queue.put(
            ServiceLogEvent(
                service_name=self._service_name,
                stream="stdout",
                line=f"{self.label} {message}",
                level=level,
            )
        )

    async def start(self) -> bool:
        """Start the SSH tunnel.
        
        Returns True if the tunnel is established successfully.
        """
        cfg = self._config

        # FAIL FAST when the localPort is already held. The old behavior
        # ("port already open — tunnel may already be active", report
        # healthy) trusted ANY listener — a squatting process, a stale
        # server, another foundry run — and the service then talked to the
        # wrong thing. A held port is a config/lifecycle error the user must
        # resolve; the all-or-nothing guarantee handles the rest.
        if _is_port_open("127.0.0.1", cfg.local_port, timeout=0.5):
            msg = (
                f"localPort {cfg.local_port} is already in use by another "
                "process (another foundry run, or something else listening). "
                "Stop it or pick a different localPort - each tunnel and each "
                "--env environment needs its own."
            )
            await self._log(msg, level="ERROR")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail=f"localPort {cfg.local_port} already in use",
                    error=msg,
                    level="ERROR",
                )
            )
            return False

        # Resolve key file
        key_file = self._resolve_password_path()
        if cfg.password and not key_file:
            await self._log(f"SSH key file not found: {cfg.password}", level="ERROR")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="SSH key file not found",
                    error=f"Could not find key file: {cfg.password}",
                    level="ERROR",
                )
            )
            return False

        # Loopback by default: publishing a tunnelled database to the whole
        # LAN is a hole, not a feature. A manifest opts into wider exposure
        # explicitly via bindAddress (e.g. "0.0.0.0" for Docker containers
        # reaching the tunnel through host.docker.internal).
        bind_addr = cfg.bind_address or "127.0.0.1"
        if ":" in bind_addr:
            await self._log(
                f"bindAddress '{bind_addr}' is not supported (IPv4 only - the "
                "default already listens on ::1 via a loopback relay)",
                level="ERROR",
            )
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="Unsupported bindAddress",
                    error=f"bindAddress '{bind_addr}' must be an IPv4 address",
                    level="ERROR",
                )
            )
            return False
        if not _is_loopback(bind_addr):
            await self._log(
                f"bindAddress {bind_addr}: port {cfg.local_port} is reachable "
                "from other machines on the network",
                level="WARN",
            )

        await self._log(f"Connecting to {cfg.host}...")
        await self._status_queue.put(
            ServiceStatusEvent(
                self.name, ServiceStatus.starting,
                detail=f"Establishing tunnel to {cfg.host}",
                level="INFO",
            )
        )

        try:
            # Import here to allow graceful error if sshtunnel not installed
            from sshtunnel import SSHTunnelForwarder

            # Create tunnel in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            self._lib_logger = self._make_lib_logger()
            lib_logger = self._lib_logger

            def create_tunnel():
                pkey = load_ssh_pkey(key_file) if key_file else None
                tunnel = SSHTunnelForwarder(
                    (cfg.host, 22),
                    ssh_username=cfg.user,
                    ssh_pkey=pkey if pkey is not None else (str(key_file) if key_file else None),
                    remote_bind_address=(cfg.remote_host, cfg.remote_port),
                    local_bind_address=(bind_addr, cfg.local_port),
                    set_keepalive=30.0,
                    logger=lib_logger,
                )
                tunnel.start()
                return tunnel

            self._tunnel = await loop.run_in_executor(None, create_tunnel)

            # Verify tunnel is active
            if self._tunnel.is_active:
                actual_port = self._tunnel.local_bind_port
                # Dual-stack: sshtunnel's forward server is IPv4-only, so on
                # the default loopback bind also listen on [::1] (macOS
                # resolves `localhost` to ::1 first). No IPv6 on the host =
                # skip; the port HELD on ::1 by another process = fail —
                # `localhost` clients would silently talk to the squatter.
                if cfg.bind_address is None:
                    self._v6_relay = _LoopbackV6Relay(cfg.local_port)
                    relay_state = await self._v6_relay.start()
                    if relay_state == "in-use":
                        self._v6_relay = None
                        msg = (
                            f"localPort {cfg.local_port} is already in use on "
                            "[::1] by another process - stop it or pick a "
                            "different localPort."
                        )
                        await self._log(msg, level="ERROR")
                        await self.stop()
                        await self._status_queue.put(
                            ServiceStatusEvent(
                                self.name, ServiceStatus.failed,
                                detail=f"localPort {cfg.local_port} already in use on [::1]",
                                error=msg,
                                level="ERROR",
                            )
                        )
                        return False
                    if relay_state != "ok":
                        self._v6_relay = None
                        await self._log(
                            "IPv6 loopback (::1) unavailable - tunnel listens on 127.0.0.1 only",
                            level="DEBUG",
                        )
                await self._log(f"Tunnel established (localhost:{actual_port} -> {cfg.remote_host}:{cfg.remote_port})")
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.healthy,
                        detail=f"Tunnel active on port {actual_port}",
                        level="INFO",
                    )
                )
                return True
            else:
                await self._log("Tunnel failed to start", level="ERROR")
                await self._status_queue.put(
                    ServiceStatusEvent(
                        self.name, ServiceStatus.failed,
                        detail="Tunnel failed to start",
                        error="SSHTunnelForwarder did not become active",
                        level="ERROR",
                    )
                )
                return False

        except ImportError:
            await self._log("sshtunnel library not installed. Run: pip install sshtunnel", level="ERROR")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="Missing dependency",
                    error="sshtunnel library not installed",
                    level="ERROR",
                )
            )
            return False
            
        except Exception as e:
            error_msg = str(e)
            # Simplify common error messages
            if "Authentication failed" in error_msg:
                error_msg = "Authentication failed - check SSH key"
            elif "Connection refused" in error_msg:
                error_msg = f"Connection refused by {cfg.host}"
            elif "timed out" in error_msg.lower():
                error_msg = f"Connection to {cfg.host} timed out"
            elif "No such file" in error_msg:
                error_msg = f"SSH key file not found"
            elif "open tunnel" in error_msg.lower() or "in use" in error_msg.lower():
                # Bind failed at sshtunnel level (e.g. the port was grabbed
                # between our pre-check and the bind).
                error_msg = (
                    f"Could not bind localPort {cfg.local_port} - "
                    "already in use by another process?"
                )
            
            await self._log(f"SSH tunnel failed: {error_msg}", level="ERROR")
            await self._status_queue.put(
                ServiceStatusEvent(
                    self.name, ServiceStatus.failed,
                    detail="SSH tunnel failed",
                    error=error_msg,
                    level="ERROR",
                )
            )
            return False

    async def stop(self) -> None:
        """Stop the SSH tunnel."""
        if self._v6_relay is not None:
            await self._v6_relay.stop()
            self._v6_relay = None
        if self._tunnel:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._tunnel.stop)
                await self._log("SSH tunnel closed")
            except Exception:
                pass
            self._tunnel = None

    def events(self):
        """Yield log events."""
        async def _gen():
            while True:
                yield await self._log_queue.get()
        return _gen()

    def status_events(self):
        """Yield status events."""
        async def _gen():
            while True:
                yield await self._status_queue.get()
        return _gen()


__all__ = ["SshTunnelConfig", "SshTunnelRunner"]
