"""`foundry publish` — cook a game build LOCALLY, then push it to FCM in one step.

The platform never cooks (UE cooks are heavy; the dev already has the engine + an
incremental cache locally). So `publish` runs the cook on this machine using the
project's `.foundry/config.yml`, zips the staged client, and uploads it to the
Foundry Content Mesh via the same presigned-PUT path as `foundry build push`.

  foundry publish --version 1.0.0            # cook + push
  foundry publish --version 1.0.0 --submit   # cook + push + submit for the $20 review

Reads `.foundry/config.yml` at the project root (kind: game-publisher):
  publisher, gameId, build: { type: ue5, ueRoot, uprojectPath, executableRelpath }
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click
import yaml

from foundry_cli.core import auth, fid
from foundry_cli.core.errors import FoundryError
from foundry_cli.commands.build_cmd import upload_build

# Map a .foundry build.type to the FCM engine specifier.
_ENGINE_BY_TYPE = {"ue5": "unreal", "ue4": "unreal", "unity": "unity", "godot": "godot"}


def _load_config(root: Path) -> dict:
    cfg_path = root / ".foundry" / "config.yml"
    if not cfg_path.is_file():
        cfg_path = root / ".foundry" / "config.yaml"
    if not cfg_path.is_file():
        raise FoundryError(
            "No .foundry/config.yml found. Run `foundry publish` from a game-publisher "
            "project root (the dir with .foundry/config.yml)."
        )
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if cfg.get("kind") != "game-publisher":
        raise FoundryError(f".foundry/config.yml kind is {cfg.get('kind')!r}; `publish` needs 'game-publisher'.")
    return cfg


def _cook_ue(root: Path, build: dict, version: str) -> Path:
    """Run UE BuildCookRun locally; return the staged client directory (holds the .exe)."""
    ue_root = build.get("ueRoot")
    uproject_rel = build.get("uprojectPath")
    if not ue_root or not uproject_rel:
        raise FoundryError("config build.ueRoot and build.uprojectPath are required for a ue5 cook.")
    uproject = (root / uproject_rel).resolve()
    if not uproject.is_file():
        raise FoundryError(f"uproject not found: {uproject}")
    target = build.get("target") or uproject.stem  # e.g. Conquest

    is_win = sys.platform == "win32"
    runuat = Path(ue_root) / "Engine" / "Build" / "BatchFiles" / ("RunUAT.bat" if is_win else "RunUAT.sh")
    if not runuat.is_file():
        raise FoundryError(f"RunUAT not found at {runuat} (check build.ueRoot).")

    archive = Path(tempfile.mkdtemp(prefix=f"fcm-{target}-{version}-"))
    uat_args = [
        "BuildCookRun",
        f"-project={uproject}",
        "-platform=Win64",
        f"-target={target}",
        "-clientconfig=Development",
        "-build", "-cook", "-stage", "-pak", "-archive",
        f"-archivedirectory={archive}",
        "-nodebuginfo", "-unattended", "-utf8output", "-noP4",
    ]
    cmd = (["cmd", "/c", str(runuat)] if is_win else [str(runuat)]) + uat_args

    click.echo(click.style(f"Cooking {target} (Win64, Development client) locally…", fg="cyan"))
    click.echo(click.style("  (first cook compiles the client target — this can take a while)", fg="white"))
    result = subprocess.run(cmd)  # inherit stdio so the dev sees cook progress
    if result.returncode != 0:
        raise FoundryError(f"BuildCookRun failed (exit {result.returncode}). See the UAT output above.")

    staged = _find_staged_dir(archive)
    if staged is None:
        raise FoundryError(f"No packaged client (.exe) found under {archive} after cook.")
    return staged


def _find_staged_dir(archive: Path) -> Path | None:
    """The archive holds <archive>/Windows/<...>.exe; return the dir whose root holds the .exe."""
    # Prefer the conventional Windows/ stage; else any dir directly containing an .exe.
    candidates = [archive / "Windows", archive / "WindowsClient", archive / "WindowsNoEditor"]
    for c in candidates:
        if c.is_dir() and any(p.suffix.lower() == ".exe" for p in c.iterdir() if p.is_file()):
            return c
    for d in archive.rglob("*"):
        if d.is_dir() and any(p.suffix.lower() == ".exe" for p in d.iterdir() if p.is_file()):
            return d
    return None


@click.command()
@click.option("--version", "version", default=None, help="Release version, e.g. 1.0.0 (recommended).")
@click.option("--submit", "do_submit", is_flag=True, default=False, hidden=True)
def publish(version, do_submit) -> None:
    """Cook the local game build and push it to the Foundry Content Mesh."""
    root = Path.cwd()
    cfg = _load_config(root)
    build = cfg.get("build") or {}
    btype = (build.get("type") or "ue5").lower()
    engine = _ENGINE_BY_TYPE.get(btype, "unreal")

    if btype not in ("ue5", "ue4"):
        raise FoundryError(f"build.type {btype!r} not supported by `publish` yet (Unreal only).")

    if not version:
        version = click.prompt("Release version", default="", show_default=False).strip() or None

    token = auth.access_token()  # fail fast if not signed in, before the long cook

    staged = _cook_ue(root, build, version or "dev")

    # Zip the staged client (exe at the zip root -> clean launcher install layout).
    click.echo("Packaging the cooked client into a .zip…")
    tmp_zip_base = Path(tempfile.mkdtemp(prefix="fcm-zip-")) / f"{cfg.get('gameId', 'game')}-{version or 'dev'}"
    zip_path = Path(shutil.make_archive(str(tmp_zip_base), "zip", root_dir=str(staged)))

    row = upload_build(str(zip_path), kind="client", version=version, engine=engine, token=token)
    build_id = row.get("id")

    # best-effort cleanup of the local zip (the cooked archive is left for inspection)
    try:
        shutil.rmtree(zip_path.parent, ignore_errors=True)
    except OSError:
        pass

    # NOTE: --submit is intentionally inert. Publishing to the Foundry App is a BILLED review and must
    # go through the web checkout so the dev sees + confirms the charge — the CLI never triggers a fee.
    if do_submit:
        click.echo()
        click.echo(click.style(
            "Publishing review is done in the web console (it's a billed action needing an explicit "
            "checkout — the CLI can't charge you). Open your game at "
            "https://foundryplatform.app/console and use 'Submit for review'.", fg="yellow"))
    elif build_id:
        click.echo()
        click.echo(
            "Pushed. To publish to the Foundry App, open your game in the web console and use "
            + click.style("'Submit for review'", fg="cyan", bold=True)
            + " (billed with checkout there)."
        )
