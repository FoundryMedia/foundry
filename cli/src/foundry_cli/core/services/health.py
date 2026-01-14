from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Optional

import urllib.request


@dataclass(frozen=True)
class HealthCheckConfig:
    """Health check configuration for a service.

    If `url` is None, the runner can fall back to other readiness strategies
    (e.g. port checks).
    """

    url: Optional[str] = None
    timeout_s: float = 0.5
    interval_s: float = 0.25
    startup_timeout_s: float = 60.0
    require_up_status: bool = False  # If True, check response body for "UP" status


async def wait_for_http_healthy(cfg: HealthCheckConfig) -> None:
    """Poll `cfg.url` until it returns a 2xx/3xx response or timeout.

    Raises:
        asyncio.TimeoutError
    """

    if not cfg.url:
        raise ValueError("HealthCheckConfig.url must be set")

    deadline = asyncio.get_running_loop().time() + cfg.startup_timeout_s

    while True:
        try:
            await _http_probe(cfg.url, timeout_s=cfg.timeout_s, require_up_status=cfg.require_up_status)
            return
        except Exception:
            # keep polling
            pass

        if asyncio.get_running_loop().time() >= deadline:
            raise asyncio.TimeoutError(f"Timed out waiting for HTTP health: {cfg.url}")

        await asyncio.sleep(cfg.interval_s)


async def _http_probe(url: str, *, timeout_s: float, require_up_status: bool = False) -> None:
    def _do() -> None:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}")

            if require_up_status:
                # Read the response body and check for UP status
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(body)
                    status = data.get("status", "").upper()
                    if status != "UP":
                        raise RuntimeError(f"Health status is {status}, not UP")
                except json.JSONDecodeError:
                    # If not JSON, just check if "UP" appears in the response
                    if '"status":"UP"' not in body and '"UP"' not in body:
                        raise RuntimeError("Response does not contain UP status")

    await asyncio.to_thread(_do)
