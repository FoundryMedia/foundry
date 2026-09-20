"""``foundry init --template ue5-game`` — turn a fresh Unreal C++ project into a Foundry game project.

Run from the folder that holds the ``.uproject`` (right after the editor's New Project
wizard). It performs the install steps of the fsdk-unreal README so a developer does not
have to:

1. downloads the latest FoundryFSDK plugin release into ``Plugins/FoundryFSDK/``
2. adds the plugin entry to the ``.uproject``
3. writes ``Source/<Game>Server.Target.cs`` (the dedicated-server target)
4. adds ``"FoundryFSDK"`` to the game module's ``Build.cs`` private dependencies
5. pins the network protocol version in the primary game module (the
   ``ProjectVersion``-in-handshake trap)
6. writes ``.foundry/config.yml`` (kind ``game-publisher``) and ``Docker/Dockerfile``

Every step is idempotent and never overwrites a file the developer already has: an
existing file is reported and left alone. The edits to wizard-generated files
(``Build.cs``, ``<Game>.cpp``) are anchored on the EXACT lines the UE 5.7 ``TP_Blank``
template emits; anything else is left untouched with a printed instruction.

``.foundry/config.yml`` is COMMITTED for a game-publisher project (unlike a platform
project's personal config.yml), so this module deliberately does not write the
platform-style ``.foundry/.gitignore``.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import click

from foundry_cli.core.errors import FoundryError

TEMPLATE_NAME = "ue5-game"
PLUGIN_REPO = "FoundryMedia/fsdk-unreal"
PLUGIN_DIR_NAME = "FoundryFSDK"
PLUGIN_ZIP_ENV = "FOUNDRY_FSDK_ZIP"  # local zip path: offline installs + tests
_GH_HEADERS = {"User-Agent": "foundry-cli", "Accept": "application/vnd.github+json"}

# The UE 5.7 TP_Blank template's primary-module line, with the project name substituted.
_DEFAULT_MODULE_RE = (
    r'IMPLEMENT_PRIMARY_GAME_MODULE\(\s*FDefaultGameModuleImpl\s*,\s*{name}\s*,\s*"{name}"\s*\)\s*;'
)
# The TP_Blank Build.cs private-dependency line (first occurrence only).
_PRIVATE_DEPS_RE = re.compile(
    r'(PrivateDependencyModuleNames\.AddRange\(new string\[\]\s*\{)([^}]*)(\}\s*\);)'
)
_GUID_RE = re.compile(r"^\{[0-9A-Fa-f-]{36}\}$")


@dataclass
class Ue5InitResult:
    """What the template did, for the summary + tests."""

    name: str
    slug: str
    ue_root: str | None
    plugin_version: str | None
    lines: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)

    def ok(self, text: str) -> None:
        self.lines.append(click.style("  ✓ ", fg="green") + text)

    def kept(self, text: str) -> None:
        self.lines.append(click.style("  • ", fg="yellow") + text)

    def todo(self, text: str) -> None:
        self.manual.append(text)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_uproject(root: Path) -> Path:
    """The single ``.uproject`` in ``root`` (the editor wizard writes exactly one)."""
    found = sorted(root.glob("*.uproject"))
    if not found:
        raise FoundryError(
            f"No .uproject in {root}.\n"
            "Run `foundry init --template ue5-game` from the folder that holds your .uproject "
            "(create the project first: UnrealEditor -> New Project -> Games -> Blank -> C++)."
        )
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise FoundryError(f"Several .uproject files here ({names}); one project per folder.")
    return found[0]


def slug_from_name(name: str) -> str:
    """``GooCrew`` -> ``goo-crew``; ``TP_Blank`` -> ``tp-blank``. Permanent once registered."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "game"


def engine_root_from_registry(guid: str) -> str | None:
    """Resolve a source-build EngineAssociation GUID to its path (Windows registry:
    HKCU\\Software\\Epic Games\\Unreal Engine\\Builds). None when unknown / not Windows."""
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Epic Games\Unreal Engine\Builds") as key:
            value, _ = winreg.QueryValueEx(key, guid)
            return str(value).replace("\\", "/").rstrip("/") or None
    except OSError:
        return None


def resolve_ue_root(association: str, override: str | None, result: Ue5InitResult) -> str | None:
    """``ueRoot`` for the config: an explicit --ue-root, else the registry path behind a
    source-build GUID. A Launcher engine ("5.7") or an empty association cannot build a
    Server target, so it is reported, not guessed."""
    if override:
        return override.replace("\\", "/").rstrip("/")
    assoc = (association or "").strip()
    if _GUID_RE.match(assoc):
        path = engine_root_from_registry(assoc)
        if path:
            return path
        result.todo(
            f"EngineAssociation {assoc} is not in the registry on this machine; set build.ueRoot "
            "and server.ueRoot in .foundry/config.yml to your UE 5.7 SOURCE build."
        )
        return None
    result.todo(
        f"EngineAssociation is {assoc or 'empty'!r} (a Launcher engine or unset). A dedicated-server "
        "target needs an engine built from source: right-click the .uproject -> Switch Unreal Engine "
        "version -> your source build, then set build.ueRoot / server.ueRoot in .foundry/config.yml."
    )
    return None


# ---------------------------------------------------------------------------
# Plugin download + install
# ---------------------------------------------------------------------------

def fetch_plugin_zip(version: str | None) -> tuple[bytes, str]:
    """The FoundryFSDK release zip bytes + the version they carry. ``FOUNDRY_FSDK_ZIP`` (a local
    path) short-circuits the network for offline installs and tests."""
    local = os.environ.get(PLUGIN_ZIP_ENV)
    if local:
        p = Path(local)
        if not p.is_file():
            raise FoundryError(f"{PLUGIN_ZIP_ENV}={local} is not a file.")
        return p.read_bytes(), _version_from_zip(p.read_bytes()) or "local"

    api = (
        f"https://api.github.com/repos/{PLUGIN_REPO}/releases/latest"
        if not version
        else f"https://api.github.com/repos/{PLUGIN_REPO}/releases/tags/v{version.lstrip('v')}"
    )
    try:
        req = urllib.request.Request(api, headers=_GH_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            release = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - one message for every network failure
        raise FoundryError(
            f"Could not read the FoundryFSDK release from GitHub ({exc}).\n"
            f"Download the zip from https://github.com/{PLUGIN_REPO}/releases and rerun with "
            f"{PLUGIN_ZIP_ENV}=<path-to-zip>, or pass --no-plugin."
        ) from exc
    asset = next(
        (a for a in release.get("assets", [])
         if str(a.get("name", "")).startswith(f"{PLUGIN_DIR_NAME}-v") and str(a.get("name", "")).endswith(".zip")),
        None,
    )
    if asset is None:
        raise FoundryError(f"Release {release.get('tag_name')} carries no {PLUGIN_DIR_NAME}-v*.zip asset.")
    try:
        req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "foundry-cli"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception as exc:  # noqa: BLE001
        raise FoundryError(f"Plugin download failed ({exc}).") from exc
    tag = str(release.get("tag_name", "")).lstrip("v")
    return data, tag or _version_from_zip(data) or "unknown"


def _version_from_zip(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            with z.open(f"{PLUGIN_DIR_NAME}/{PLUGIN_DIR_NAME}.uplugin") as f:
                return str(json.load(f).get("VersionName") or "") or None
    except (KeyError, OSError, ValueError, zipfile.BadZipFile):
        return None


def installed_plugin_version(root: Path) -> str | None:
    uplugin = root / "Plugins" / PLUGIN_DIR_NAME / f"{PLUGIN_DIR_NAME}.uplugin"
    if not uplugin.is_file():
        return None
    try:
        return str(json.loads(uplugin.read_text(encoding="utf-8")).get("VersionName") or "") or "?"
    except (OSError, ValueError):
        return "?"


def install_plugin_zip(root: Path, data: bytes) -> None:
    """Unzip the release (top-level ``FoundryFSDK/``) into ``<root>/Plugins/``. Zip-slip guarded."""
    plugins = root / "Plugins"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        if not any(n.startswith(f"{PLUGIN_DIR_NAME}/") for n in names):
            raise FoundryError(f"The zip does not carry a top-level {PLUGIN_DIR_NAME}/ folder.")
        for n in names:
            target = (plugins / n).resolve()
            if plugins.resolve() not in target.parents and target != plugins.resolve():
                raise FoundryError(f"Refusing zip member outside Plugins/: {n}")
        plugins.mkdir(parents=True, exist_ok=True)
        z.extractall(plugins)
    if not (plugins / PLUGIN_DIR_NAME / f"{PLUGIN_DIR_NAME}.uplugin").is_file():
        raise FoundryError("Unzipped, but Plugins/FoundryFSDK/FoundryFSDK.uplugin is missing.")


# ---------------------------------------------------------------------------
# Project edits (each: returns True when it changed something)
# ---------------------------------------------------------------------------

def ensure_uproject_plugin(uproject: Path, dry_run: bool) -> bool:
    doc = json.loads(uproject.read_text(encoding="utf-8-sig"))
    plugins = doc.setdefault("Plugins", [])
    if any(isinstance(p, dict) and p.get("Name") == PLUGIN_DIR_NAME for p in plugins):
        return False
    plugins.append({"Name": PLUGIN_DIR_NAME, "Enabled": True})
    if not dry_run:
        # UE writes tab-indented JSON with a trailing newline; keep its shape.
        uproject.write_text(json.dumps(doc, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def server_target_source(name: str) -> str:
    return (
        "using UnrealBuildTool;\n"
        "using System.Collections.Generic;\n"
        "\n"
        f"public class {name}ServerTarget : TargetRules\n"
        "{\n"
        f"\tpublic {name}ServerTarget(TargetInfo Target) : base(Target)\n"
        "\t{\n"
        "\t\tType = TargetType.Server;\n"
        "\t\tDefaultBuildSettings = BuildSettingsVersion.V6;\n"
        "\t\tIncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7;\n"
        f'\t\tExtraModuleNames.Add("{name}");\n'
        "\t}\n"
        "}\n"
    )


def protocol_module_source(name: str) -> str:
    return (
        "// Client<->server compatibility is OUR protocol number, not the release string.\n"
        "// Unreal hashes ProjectVersion into the network handshake and `foundry package` stamps\n"
        "// it per release, so without this override a client and a server built from different\n"
        "// releases refuse each other (CloseReason=Upgrade). Bump ONLY on a breaking replication\n"
        "// change (replicated fields added/removed/retyped, RPC signature changes).\n"
        f"static constexpr uint32 {name}NetProtocolVersion = 1;\n"
        "\n"
        f"class F{name}Module : public FDefaultGameModuleImpl\n"
        "{\n"
        "public:\n"
        "\tvirtual void StartupModule() override\n"
        "\t{\n"
        "\t\tFDefaultGameModuleImpl::StartupModule();\n"
        "\t\tFNetworkVersion::GetLocalNetworkVersionOverride.BindLambda(\n"
        f"\t\t\t[]() -> uint32 {{ return {name}NetProtocolVersion; }});\n"
        "\t}\n"
        "};\n"
        "\n"
        f'IMPLEMENT_PRIMARY_GAME_MODULE( F{name}Module, {name}, "{name}" );'
    )


def pin_protocol_version(cpp: Path, name: str, dry_run: bool) -> str:
    """Replace the wizard's default primary-module line with the protocol override.
    Returns ``"pinned"`` / ``"already"`` / ``"manual"``."""
    text = cpp.read_text(encoding="utf-8")
    if "GetLocalNetworkVersionOverride" in text:
        return "already"
    pattern = re.compile(_DEFAULT_MODULE_RE.format(name=re.escape(name)))
    if not pattern.search(text):
        return "manual"
    new = pattern.sub(lambda _m: protocol_module_source(name), text, count=1)
    if '"Misc/NetworkVersion.h"' not in new:
        include_line = '#include "Modules/ModuleManager.h"'
        if include_line in new:
            new = new.replace(include_line, '#include "Misc/NetworkVersion.h"\n' + include_line, 1)
        else:
            new = '#include "Misc/NetworkVersion.h"\n' + new
    if not dry_run:
        cpp.write_text(new, encoding="utf-8")
    return "pinned"


def add_build_dependency(build_cs: Path, dry_run: bool) -> str:
    """Add ``"FoundryFSDK"`` to the first ``PrivateDependencyModuleNames.AddRange(new string[] { ... });``.
    Returns ``"added"`` / ``"already"`` / ``"manual"``."""
    text = build_cs.read_text(encoding="utf-8")
    if f'"{PLUGIN_DIR_NAME}"' in text:
        return "already"
    m = _PRIVATE_DEPS_RE.search(text)
    if not m:
        return "manual"
    existing = [s.strip() for s in m.group(2).split(",") if s.strip()]
    existing.append(f'"{PLUGIN_DIR_NAME}"')
    new = text[: m.start()] + m.group(1) + " " + ", ".join(existing) + " " + m.group(3) + text[m.end():]
    if not dry_run:
        build_cs.write_text(new, encoding="utf-8")
    return "added"


def config_yml_source(name: str, slug: str, publisher: str, ue_root: str | None) -> str:
    root = ue_root or "C:/UnrealEngine   # <- your UE 5.7 SOURCE build (a Server target needs one)"
    return (
        "# Foundry game-publisher project config. Drives `foundry package` (local UE cook)\n"
        "# and `foundry fcm push` (upload + game link). Written by `foundry init --template ue5-game`.\n"
        "\n"
        'schemaVersion: "1"\n'
        "kind: game-publisher\n"
        f"name: {name}\n"
        "\n"
        f"publisher: {publisher or 'your-publisher-handle'}\n"
        f"gameId: {slug}\n"
        "\n"
        "build:\n"
        "  type: ue5\n"
        f"  uprojectPath: {name}.uproject\n"
        f"  ueRoot: {root}\n"
        f"  executableRelpath: Windows/{name}.exe\n"
        "  clientConfig: Shipping   # real releases ship Shipping (console/debug stripped)\n"
        "  chunking: true           # fail the package if content cooks to one monolithic container\n"
        "\n"
        "server:\n"
        f"  ueRoot: {root}\n"
        f"  uprojectPath: {name}.uproject\n"
        f"  serverTarget: {name}Server\n"
        "  dockerfile: Docker/Dockerfile\n"
        f"  imageName: {slug}-server\n"
    )


def dockerfile_source(name: str) -> str:
    return (
        "# Docker/Dockerfile - written by `foundry init --template ue5-game`; edit freely.\n"
        "# `foundry package --server` builds with <project>/Saved/StagedBuilds as the context,\n"
        "# so COPY LinuxServer/ is the staged dedicated server. Self-contained: no other files.\n"
        "\n"
        "# Stage 1: the staged server minus its debug symbols (~1.4 GB the server never reads).\n"
        "FROM ubuntu:22.04 AS staged\n"
        "COPY LinuxServer/ /server/\n"
        "RUN find /server \\( -name '*.debug' -o -name '*.sym' -o -name '*.pdb' \\) -delete\n"
        "\n"
        "# Stage 2: the image. A UE Linux server needs only glibc + TLS roots (OpenSSL is static).\n"
        "FROM ubuntu:22.04\n"
        "RUN apt-get update \\\n"
        " && apt-get install -y --no-install-recommends ca-certificates libc6 \\\n"
        " && rm -rf /var/lib/apt/lists/*\n"
        "# UE dedicated servers REFUSE to run as root; the ELF loses its +x bit on Windows filesystems.\n"
        "RUN useradd -m -u 1000 ueserver\n"
        "COPY --from=staged --chown=ueserver:ueserver /server/ /server/\n"
        f"RUN chmod +x /server/{name}/Binaries/Linux/{name}Server\n"
        "USER ueserver\n"
        "EXPOSE 7777/udp\n"
        "# The platform hands the container FOUNDRY_GAME_PORT and FOUNDRY_AUTH_BASE. The server loads\n"
        "# ServerDefaultMap from Config/DefaultEngine.ini; put a map name first to override.\n"
        f'ENTRYPOINT ["/bin/sh", "-c", "exec /server/{name}/Binaries/Linux/{name}Server '
        "-Port=${FOUNDRY_GAME_PORT:-7777} "
        "-FoundryAuthBase=${FOUNDRY_AUTH_BASE:-https://auth.foundryplatform.app} "
        '-unattended -stdout -FullStdOutLogOutput"]\n'
    )


def _write_new(path: Path, content: str, dry_run: bool) -> bool:
    """Write ``path`` only if absent (LF endings). Returns True when written / would write."""
    if path.exists():
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    return True


# ---------------------------------------------------------------------------
# The command body
# ---------------------------------------------------------------------------

def init_ue5_game(
    root: Path,
    *,
    publisher: str | None,
    game: str | None,
    ue_root: str | None,
    plugin_version: str | None,
    install_plugin: bool,
    dry_run: bool,
) -> Ue5InitResult:
    root = root.resolve()
    uproject = find_uproject(root)
    name = uproject.stem
    slug = (game or "").strip().lower() or slug_from_name(name)
    doc = json.loads(uproject.read_text(encoding="utf-8-sig"))
    result = Ue5InitResult(name=name, slug=slug, ue_root=None, plugin_version=None)
    result.ue_root = resolve_ue_root(str(doc.get("EngineAssociation", "")), ue_root, result)
    prefix = "[dry-run] would " if dry_run else ""

    click.echo(click.style(f"Foundry UE5 game project: {name}  (slug {slug})", fg="blue", bold=True))
    if result.ue_root:
        click.echo(f"  engine: {result.ue_root}")
    click.echo()

    # 1. plugin
    have = installed_plugin_version(root)
    if have:
        result.plugin_version = have
        result.kept(f"Plugins/{PLUGIN_DIR_NAME}/ already installed (v{have}) - left alone")
    elif not install_plugin:
        result.kept(f"Plugins/{PLUGIN_DIR_NAME}/ skipped (--no-plugin)")
    else:
        data, ver = fetch_plugin_zip(plugin_version)
        if not dry_run:
            install_plugin_zip(root, data)
        result.plugin_version = ver
        result.ok(f"{prefix}install Plugins/{PLUGIN_DIR_NAME}/ (v{ver})" if dry_run
                  else f"Plugins/{PLUGIN_DIR_NAME}/  (v{ver})")

    # 2. uproject entry
    if ensure_uproject_plugin(uproject, dry_run):
        result.ok(f"{prefix}{uproject.name}: plugin {PLUGIN_DIR_NAME} enabled")
    else:
        result.kept(f"{uproject.name} already lists {PLUGIN_DIR_NAME}")

    # 3. Server target
    source_dir = root / "Source"
    game_target = source_dir / f"{name}.Target.cs"
    server_target = source_dir / f"{name}Server.Target.cs"
    if not game_target.is_file():
        result.todo(
            f"Source/{name}.Target.cs not found - this does not look like a C++ project. Create the "
            "project as C++ (New Project -> Games -> Blank -> C++), or add a Source/ module; "
            "a dedicated-server target needs one."
        )
    elif _write_new(server_target, server_target_source(name), dry_run):
        result.ok(f"{prefix}Source/{name}Server.Target.cs")
    else:
        result.kept(f"Source/{name}Server.Target.cs exists")

    # 4. Build.cs dependency
    build_cs = source_dir / name / f"{name}.Build.cs"
    if build_cs.is_file():
        status = add_build_dependency(build_cs, dry_run)
        if status == "added":
            result.ok(f'{prefix}Source/{name}/{name}.Build.cs: "{PLUGIN_DIR_NAME}" added to PrivateDependencyModuleNames')
        elif status == "already":
            result.kept(f"Source/{name}/{name}.Build.cs already depends on {PLUGIN_DIR_NAME}")
        else:
            result.todo(f'Add "{PLUGIN_DIR_NAME}" to PrivateDependencyModuleNames in Source/{name}/{name}.Build.cs.')
    else:
        result.todo(f'Add "{PLUGIN_DIR_NAME}" to PrivateDependencyModuleNames in your game module\'s Build.cs.')

    # 5. protocol version
    module_cpp = source_dir / name / f"{name}.cpp"
    if module_cpp.is_file():
        status = pin_protocol_version(module_cpp, name, dry_run)
        if status == "pinned":
            result.ok(f"{prefix}Source/{name}/{name}.cpp: network protocol version pinned (GetLocalNetworkVersionOverride)")
        elif status == "already":
            result.kept(f"Source/{name}/{name}.cpp already overrides the network version")
        else:
            result.todo(
                f"Source/{name}/{name}.cpp is customized; bind FNetworkVersion::GetLocalNetworkVersionOverride "
                "to a protocol constant in your primary module's StartupModule (fsdk-unreal README 3.4)."
            )
    else:
        result.todo(
            "Pin the network protocol version in your primary game module "
            "(FNetworkVersion::GetLocalNetworkVersionOverride, fsdk-unreal README 3.4)."
        )

    # 6. config + Dockerfile
    cfg = root / ".foundry" / "config.yml"
    if _write_new(cfg, config_yml_source(name, slug, publisher or "", result.ue_root), dry_run):
        result.ok(f"{prefix}.foundry/config.yml  (kind game-publisher, gameId {slug}, serverTarget {name}Server)")
    else:
        result.kept(".foundry/config.yml exists")
    dockerfile = root / "Docker" / "Dockerfile"
    if _write_new(dockerfile, dockerfile_source(name), dry_run):
        result.ok(f"{prefix}Docker/Dockerfile  (self-contained dedicated-server image)")
    else:
        result.kept("Docker/Dockerfile exists")

    for line in result.lines:
        click.echo(line)
    if result.manual:
        click.echo()
        click.echo(click.style("  By hand:", fg="yellow", bold=True))
        for item in result.manual:
            click.echo(click.style("  ⚠ ", fg="yellow") + item)
    click.echo()
    click.echo(click.style("Next:", bold=True))
    click.echo(f"  1. Right-click {uproject.name} -> Generate Visual Studio project files; build {name}Editor.")
    click.echo("  2. foundry login   then   foundry games create --name \"<Your Game>\"   (once; the slug goes in .foundry/config.yml gameId)")
    click.echo("  3. In the editor: run with -DevMode, press ~, `foundry login <email>` (once per machine; later starts sign in on their own).")
    click.echo(f"  4. Ship: foundry package --server --version 0.1.0 && foundry fcm push <tar> --type server --version 0.1.0 --game {slug}")
    return result
