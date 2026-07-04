"""`foundry package` — package a game build LOCALLY. NO upload, NO publish, NO charge.

The platform never cooks (UE cooks are heavy; the dev already has the engine + an
incremental cache locally). So `package` runs the cook/containerize on THIS machine
using the project's `.foundry/config.yml` and prints the resulting artifact path. It
does NOT touch the network — uploading is a separate step (`foundry fcm push`), and
publishing to the Foundry App is a BILLED action done in the web console (checkout).

  foundry package --client --version 1.0.0      # cook the UE client -> a .zip
  foundry package --server --version 1.0.0      # cook + containerize the server -> a .tar

Then upload the artifact:
  foundry fcm push --type client --name my-game ./my-game-1.0.0.zip
  foundry fcm push --type server --name my-game --image-tag my-game:1.0.0 ./my-game-1.0.0.tar

Reads `.foundry/config.yml` at the project root (kind: game-publisher):
  publisher, gameId
  build:  { type: ue5, ueRoot, uprojectPath, executableRelpath,
            clientConfig: Shipping|Development (default Shipping),
            chunking: true|false (default true) }                  # --client
  server: { ueRoot, uprojectPath, serverTarget, dockerfile, imageName }  # --server
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import click
import yaml

from foundry_cli.core.errors import FoundryError


def _load_config(root: Path) -> dict:
    cfg_path = root / ".foundry" / "config.yml"
    if not cfg_path.is_file():
        cfg_path = root / ".foundry" / "config.yaml"
    if not cfg_path.is_file():
        raise FoundryError(
            "No .foundry/config.yml found. Run `foundry package` from a game-publisher "
            "project root (the dir with .foundry/config.yml)."
        )
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if cfg.get("kind") != "game-publisher":
        raise FoundryError(
            f".foundry/config.yml kind is {cfg.get('kind')!r}; `package` needs 'game-publisher'."
        )
    return cfg


def _which(tool: str) -> str:
    """Resolve an executable on PATH or raise a FoundryError naming it."""
    found = shutil.which(tool)
    if not found:
        raise FoundryError(f"`{tool}` not found on PATH — it is required to package this build.")
    return found


def _run(cmd: list[str], *, what: str) -> None:
    """Run an external step (inherit stdio so the dev sees progress); raise on failure."""
    click.echo(click.style(f"$ {' '.join(str(c) for c in cmd)}", fg="bright_black"))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise FoundryError(f"{what} failed (exit {result.returncode}). See the output above.")


# ---------------------------------------------------------------------------
# --client : UE client cook + zip
# ---------------------------------------------------------------------------

_CLIENT_CONFIGS = ("Shipping", "Development", "Test", "DebugGame")


def _cook_ue_client(root: Path, build: dict, version: str) -> Path:
    """Run UE BuildCookRun for the CLIENT locally; return the staged dir (holds the .exe)."""
    ue_root = build.get("ueRoot")
    uproject_rel = build.get("uprojectPath")
    if not ue_root or not uproject_rel:
        raise FoundryError("config build.ueRoot and build.uprojectPath are required for a ue5 client cook.")
    uproject = (root / uproject_rel).resolve()
    if not uproject.is_file():
        raise FoundryError(f"uproject not found: {uproject}")
    target = build.get("target") or uproject.stem  # e.g. Conquest

    client_config = build.get("clientConfig") or "Shipping"
    if client_config not in _CLIENT_CONFIGS:
        raise FoundryError(
            f"build.clientConfig {client_config!r} is not one of {', '.join(_CLIENT_CONFIGS)}."
        )

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
        f"-clientconfig={client_config}",
        "-build", "-cook", "-stage", "-pak", "-archive",
        f"-archivedirectory={archive}",
        "-nodebuginfo", "-unattended", "-utf8output", "-noP4",
    ]
    # Invoke the .bat directly (never `cmd /c <path> <args>` — cmd re-splits an
    # unquoted spaced path like "F:\Documents\Unreal Projects\..." and dies).
    cmd = [str(runuat)] + uat_args

    click.echo(click.style(f"Cooking {target} (Win64, {client_config} client) locally…", fg="cyan"))
    click.echo(click.style("  (first cook compiles the client target — this can take a while)", fg="white"))
    _run(cmd, what="BuildCookRun (client)")

    staged = _find_staged_dir(archive)
    if staged is None:
        raise FoundryError(f"No packaged client (.exe) found under {archive} after cook.")
    return staged


# A single monolithic content container bigger than this means chunking isn't
# working — every content tweak would re-ship the whole thing to players.
_CHUNK_SIZE_GATE_BYTES = 200 * 1024 * 1024


def _validate_chunked_output(staged: Path, chunking: bool) -> None:
    """Delta-friendliness gate: the launcher's delta-sync is per-file, so content
    must be split across multiple pak/IoStore containers to patch incrementally.
    With build.chunking enabled (the default), fail if the cook produced a single
    monolithic container above the size gate."""
    containers = sorted(staged.rglob("*.ucas")) or sorted(staged.rglob("*.pak"))
    if not containers:
        return  # no pak output at all — nothing to validate

    total = 0
    click.echo(click.style("Content containers:", fg="cyan"))
    for c in containers:
        size = c.stat().st_size
        total += size
        click.echo(f"  {c.name}  {size / (1024 * 1024):,.1f} MB")

    if not chunking:
        return
    if len(containers) == 1 and containers[0].stat().st_size > _CHUNK_SIZE_GATE_BYTES:
        raise FoundryError(
            f"Cook produced a SINGLE {containers[0].stat().st_size / (1024 * 1024):,.0f} MB content "
            "container — every content change would re-ship all of it to players.\n"
            "Enable chunk generation in the project so content splits into multiple containers:\n"
            "  Config/DefaultGame.ini:\n"
            "    [/Script/UnrealEd.ProjectPackagingSettings]\n"
            "    bGenerateChunks=True\n"
            "  then assign chunks via PrimaryAssetLabel assets or\n"
            "  [/Script/Engine.AssetManagerSettings] rules (e.g. maps -> ChunkId 1+).\n"
            "If this game is intentionally monolithic, set build.chunking: false in .foundry/config.yml."
        )


# Stage-tree noise that must never ship to players: debug symbols and the UAT
# stage manifests (Manifest_UFSFiles_Win64.txt etc.).
def _zip_excluded(path: Path) -> bool:
    name = path.name
    return name.lower().endswith(".pdb") or (name.startswith("Manifest_") and name.endswith(".txt"))


def _zip_staged(staged: Path, zip_base: Path) -> Path:
    """Zip the staged client tree, excluding .pdb + Manifest_* stage files."""
    zip_path = zip_base.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(staged.rglob("*")):
            if not p.is_file() or _zip_excluded(p):
                continue
            zf.write(p, p.relative_to(staged).as_posix())
    return zip_path


def _find_staged_dir(archive: Path) -> Path | None:
    """The archive holds <archive>/Windows/<...>.exe; return the dir whose root holds the .exe."""
    candidates = [archive / "Windows", archive / "WindowsClient", archive / "WindowsNoEditor"]
    for c in candidates:
        if c.is_dir() and any(p.suffix.lower() == ".exe" for p in c.iterdir() if p.is_file()):
            return c
    for d in archive.rglob("*"):
        if d.is_dir() and any(p.suffix.lower() == ".exe" for p in d.iterdir() if p.is_file()):
            return d
    return None


def _package_client(root: Path, cfg: dict, version: str | None, out_dir: Path | None) -> Path:
    """Cook the UE client and zip it. Returns the .zip path."""
    build = cfg.get("build") or {}
    btype = (build.get("type") or "ue5").lower()
    if btype not in ("ue5", "ue4"):
        raise FoundryError(f"build.type {btype!r} not supported by `package --client` yet (Unreal only).")

    staged = _cook_ue_client(root, build, version or "dev")
    _validate_chunked_output(staged, chunking=bool(build.get("chunking", True)))

    click.echo("Packaging the cooked client into a .zip…")
    base_name = f"{cfg.get('gameId', 'game')}-{version or 'dev'}"
    dest_dir = out_dir or Path(tempfile.mkdtemp(prefix="fcm-zip-"))
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = _zip_staged(staged, dest_dir / base_name)
    return zip_path


# ---------------------------------------------------------------------------
# --server : UE Linux dedicated-server cook + docker build + docker save
# ---------------------------------------------------------------------------

def _cook_ue_server(root: Path, server: dict, version: str) -> Path:
    """Cross-compile + stage a UE Linux DEDICATED SERVER build; return the staged LinuxServer dir.

    Recipe per .claude/plans/conquest-dedicated-server.md (Phase C):
      RunUAT BuildCookRun -platform=Linux -server -noclient -target=<Target>Server
        -serverconfig=Development -build -cook -stage -pak   (NO -archive: it self-copies
        the stage tree onto itself, fails "file in use", and DELETES the staged files).
    Output lands in <uprojectDir>/Saved/StagedBuilds/LinuxServer.
    """
    ue_root = server.get("ueRoot")
    uproject_rel = server.get("uprojectPath")
    if not ue_root or not uproject_rel:
        raise FoundryError("config server.ueRoot and server.uprojectPath are required for a server package.")
    uproject = (root / uproject_rel).resolve()
    if not uproject.is_file():
        raise FoundryError(f"uproject not found: {uproject}")

    # The server target defaults to "<ProjectName>Server" (UE convention, e.g. ConquestServer).
    server_target = server.get("serverTarget") or f"{uproject.stem}Server"

    is_win = sys.platform == "win32"
    runuat = Path(ue_root) / "Engine" / "Build" / "BatchFiles" / ("RunUAT.bat" if is_win else "RunUAT.sh")
    if not runuat.is_file():
        raise FoundryError(f"RunUAT not found at {runuat} (check server.ueRoot).")

    # NOTE: cross-compiling a Linux server from Windows needs the UE Linux toolchain
    # (LINUX_MULTIARCH_ROOT set by Epic's cross-toolchain installer). UAT enforces it and
    # errors clearly if it's missing, so we don't pre-check it here.
    uat_args = [
        "BuildCookRun",
        f"-project={uproject}",
        "-noP4",
        "-platform=Linux",
        "-server", "-noclient",
        f"-target={server_target}",
        "-serverconfig=Development",
        "-build", "-cook", "-stage", "-pak",
        # NOTE: deliberately NO -archive (see docstring) and NO -nullrhi.
        "-unattended", "-utf8output",
    ]
    # Invoke the .bat directly (never `cmd /c <path> <args>` — see the client cook note).
    cmd = [str(runuat)] + uat_args

    click.echo(click.style(f"Cooking {server_target} (Linux, Development dedicated server) locally…", fg="cyan"))
    click.echo(click.style(
        "  (cross-compiling a Linux server needs the UE Linux toolchain / LINUX_MULTIARCH_ROOT;"
        " the first cook can take a while)", fg="white"))
    _run(cmd, what="BuildCookRun (Linux server)")

    staged = uproject.parent / "Saved" / "StagedBuilds" / "LinuxServer"
    if not staged.is_dir():
        raise FoundryError(
            f"No staged Linux server found at {staged} after cook. "
            "Confirm the Linux toolchain is installed and the server target built."
        )
    return staged


def _docker_build_server(root: Path, server: dict, staged: Path, image_name: str) -> str:
    """`docker build` the server image using the project's Dockerfile. Returns the RepoTag."""
    docker = _which("docker")

    dockerfile_rel = server.get("dockerfile") or "Docker/Dockerfile"
    dockerfile = (root / dockerfile_rel).resolve()
    if not dockerfile.is_file():
        raise FoundryError(
            f"Dockerfile not found at {dockerfile} (config server.dockerfile, default Docker/Dockerfile). "
            "Provide a Dockerfile that COPYs the staged LinuxServer/ tree and launches the ELF as a "
            "non-root user (UE servers refuse to run as root)."
        )

    # The Dockerfile is expected to `COPY LinuxServer/ ...`, so the build context must be the
    # directory that CONTAINS the staged LinuxServer/ dir (i.e. StagedBuilds/), mirroring the plan doc.
    context = staged.parent
    if not (context / "LinuxServer").is_dir():
        # Fall back to using the staged dir's parent regardless; warn so the dev can fix the context.
        click.echo(click.style(
            f"  WARNING: expected a LinuxServer/ dir under the build context {context}; "
            "the Dockerfile's COPY paths must match your staged layout.", fg="yellow"))

    click.echo(click.style(f"Building the server image {image_name}…", fg="cyan"))
    _run(
        [docker, "build", "-f", str(dockerfile), "-t", image_name, str(context)],
        what="docker build",
    )
    return image_name


def _docker_save_server(image_name: str, out_dir: Path, base_name: str) -> Path:
    """`docker save` the built image to a .tar. Returns the .tar path."""
    docker = _which("docker")
    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = out_dir / f"{base_name}.tar"

    click.echo(click.style(f"Saving {image_name} to {tar_path}…", fg="cyan"))
    _run([docker, "save", "-o", str(tar_path), image_name], what="docker save")
    if not tar_path.is_file():
        raise FoundryError(f"docker save produced no file at {tar_path}.")
    return tar_path


def _package_server(root: Path, cfg: dict, version: str | None, out_dir: Path | None) -> tuple[Path, str]:
    """Cook the UE Linux server, containerize it, and save the image to a .tar.

    Returns (tar_path, image_repo_tag).
    """
    server = cfg.get("server") or {}
    if not server:
        raise FoundryError(
            "config is missing a `server:` block. Add one to .foundry/config.yml:\n"
            "  server:\n"
            "    ueRoot: <path to the UE engine root>\n"
            "    uprojectPath: <path to your .uproject, relative to the project root>\n"
            "    serverTarget: <YourGameServer>        # default <ProjectName>Server\n"
            "    dockerfile: Docker/Dockerfile         # default\n"
            "    imageName: <your-game>                # default <gameId>-server\n"
        )

    ver = version or "dev"
    game_id = cfg.get("gameId", "game")
    image_name = server.get("imageName") or f"{game_id}-server"
    # Tag the image with the version so the saved tar's RepoTag is meaningful for `fcm push --image-tag`.
    image_repo_tag = image_name if ":" in image_name else f"{image_name}:{ver}"

    staged = _cook_ue_server(root, server, ver)
    _docker_build_server(root, server, staged, image_repo_tag)

    dest_dir = out_dir or Path(tempfile.mkdtemp(prefix="fcm-server-tar-"))
    base_name = f"{game_id}-server-{ver}"
    tar_path = _docker_save_server(image_repo_tag, dest_dir, base_name)
    return tar_path, image_repo_tag


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

@click.command()
@click.option("--client", "do_client", is_flag=True, default=False,
              help="Package the player CLIENT (UE cook -> .zip).")
@click.option("--server", "do_server", is_flag=True, default=False,
              help="Package the dedicated SERVER (UE Linux cook -> docker image -> .tar).")
@click.option("--version", "version", default=None, help="Build version, e.g. 1.0.0 (stamped into the artifact name).")
@click.option("--out", "out", type=click.Path(file_okay=False, resolve_path=True), default=None,
              help="Output directory for the artifact (defaults to a temp dir; the path is printed).")
def package(do_client, do_server, version, out) -> None:
    """Package a game build LOCALLY (no upload). Use --client or --server.

    This never uploads or publishes. After packaging, upload with `foundry fcm push`,
    and publish to the Foundry App from the web console (a billed checkout).
    """
    if do_client == do_server:
        raise FoundryError("Choose exactly one of --client or --server.")

    root = Path.cwd()
    cfg = _load_config(root)
    out_dir = Path(out) if out else None

    if do_client:
        zip_path = _package_client(root, cfg, version, out_dir)
        click.echo()
        click.echo(click.style("✓ Client packaged.", fg="green", bold=True))
        click.echo("  artifact: " + click.style(str(zip_path), fg="cyan", bold=True))
        click.echo()
        click.echo(
            "Upload it with "
            + click.style(f"foundry fcm push --type client --name <name> \"{zip_path}\"", fg="cyan")
        )
        return

    # --server
    tar_path, image_repo_tag = _package_server(root, cfg, version, out_dir)
    click.echo()
    click.echo(click.style("✓ Server packaged.", fg="green", bold=True))
    click.echo("  artifact: " + click.style(str(tar_path), fg="cyan", bold=True))
    click.echo("  image:    " + click.style(image_repo_tag, fg="cyan", bold=True))
    click.echo()
    click.echo(
        "Upload it with "
        + click.style(
            f"foundry fcm push --type server --name <name> --image-tag {image_repo_tag} \"{tar_path}\"",
            fg="cyan",
        )
    )
