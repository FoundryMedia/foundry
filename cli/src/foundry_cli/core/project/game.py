"""Resolve the project's game slug from `.foundry/config.yml` (game-publisher projects).

Shared by `foundry fcm push` (link an uploaded build to its game) and `foundry fmms queue`
(scope queue commands to the project's game) so a command run inside a game project needs no
explicit `--game`. Any read/parse problem just means "no default" — command scoping must never
fail on config sniffing.
"""

from __future__ import annotations

from pathlib import Path


def project_game_id() -> str | None:
    """The gameId from `.foundry/config.yml`, walking up from CWD (game-publisher projects only)."""
    cwd = Path.cwd()
    for root in (cwd, *cwd.parents):
        for filename in ("config.yml", "config.yaml"):
            cfg_path = root / ".foundry" / filename
            if cfg_path.is_file():
                try:
                    import yaml

                    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    return None
                if cfg.get("kind") != "game-publisher":
                    return None
                game_id = cfg.get("gameId")
                return str(game_id).strip().lower() if game_id else None
    return None
