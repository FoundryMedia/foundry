"""`foundry init --template ue5-game` against a wizard-shaped Unreal C++ project.

The fixture is the UE 5.7 TP_Blank template with the project name substituted — exactly
what the editor's New Project wizard writes — because the Build.cs / <Game>.cpp edits are
anchored on those lines. The plugin zip comes from FOUNDRY_FSDK_ZIP (no network).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from foundry_cli.commands import init_ue5
from foundry_cli.commands.init import init

NAME = "GooCrew"
GUID = "{441C019C-48F7-4655-791C-A8A68E78B7BF}"

UPROJECT = {
    "FileVersion": 3,
    "EngineAssociation": GUID,
    "Category": "",
    "Description": "",
    "Modules": [{"Name": NAME, "Type": "Runtime", "LoadingPhase": "Default"}],
    "Plugins": [{"Name": "ModelingToolsEditorMode", "Enabled": True, "TargetAllowList": ["Editor"]}],
}

MODULE_CPP = (
    "// Copyright Epic Games, Inc. All Rights Reserved.\n\n"
    f'#include "{NAME}.h"\n'
    '#include "Modules/ModuleManager.h"\n\n'
    f'IMPLEMENT_PRIMARY_GAME_MODULE( FDefaultGameModuleImpl, {NAME}, "{NAME}" );\n'
)

BUILD_CS = (
    "// Copyright Epic Games, Inc. All Rights Reserved.\n\n"
    "using UnrealBuildTool;\n\n"
    f"public class {NAME} : ModuleRules\n{{\n"
    f"\tpublic {NAME}(ReadOnlyTargetRules Target) : base(Target)\n\t{{\n"
    "\t\tPCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;\n\t\n"
    '\t\tPublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput" });\n\n'
    "\t\tPrivateDependencyModuleNames.AddRange(new string[] {  });\n\n"
    "\t\t// Uncomment if you are using Slate UI\n"
    '\t\t// PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore" });\n'
    "\t}\n}\n"
)

GAME_TARGET = (
    "using UnrealBuildTool;\nusing System.Collections.Generic;\n\n"
    f"public class {NAME}Target : TargetRules\n{{\n"
    f"\tpublic {NAME}Target(TargetInfo Target) : base(Target)\n\t{{\n"
    "\t\tType = TargetType.Game;\n\t}\n}\n"
)


def _plugin_zip(version: str = "0.5.0") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("FoundryFSDK/FoundryFSDK.uplugin", json.dumps({"VersionName": version, "Modules": [{"Name": "FoundryFSDK"}]}))
        z.writestr("FoundryFSDK/Source/FoundryFSDK/FoundryFSDK.Build.cs", "// build rules")
        z.writestr("FoundryFSDK/README.md", "# FSDK")
    return buf.getvalue()


@pytest.fixture()
def ue_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / f"{NAME}.uproject").write_text(json.dumps(UPROJECT, indent="\t") + "\n", encoding="utf-8")
    src = tmp_path / "Source"
    (src / NAME).mkdir(parents=True)
    (src / f"{NAME}.Target.cs").write_text(GAME_TARGET, encoding="utf-8")
    (src / f"{NAME}Editor.Target.cs").write_text(GAME_TARGET.replace("Game", "Editor"), encoding="utf-8")
    (src / NAME / f"{NAME}.cpp").write_text(MODULE_CPP, encoding="utf-8")
    (src / NAME / f"{NAME}.h").write_text('#pragma once\n#include "CoreMinimal.h"\n', encoding="utf-8")
    (src / NAME / f"{NAME}.Build.cs").write_text(BUILD_CS, encoding="utf-8")

    zip_path = tmp_path / "plugin.zip"
    zip_path.write_bytes(_plugin_zip())
    monkeypatch.setenv(init_ue5.PLUGIN_ZIP_ENV, str(zip_path))
    monkeypatch.setattr(init_ue5, "engine_root_from_registry", lambda guid: "D:/UnrealEngine" if guid == GUID else None)

    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


def _tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "plugin.zip":
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_fresh_project_gets_everything(ue_project: Path) -> None:
    res = CliRunner().invoke(init, ["--template", "ue5-game", "--publisher", "foundry", "--game", "goo-crew"])
    assert res.exit_code == 0, res.output

    # 1. plugin unzipped into Plugins/
    uplugin = ue_project / "Plugins" / "FoundryFSDK" / "FoundryFSDK.uplugin"
    assert uplugin.is_file()
    assert "v0.5.0" in res.output

    # 2. uproject entry, exactly once, existing entries kept
    doc = json.loads((ue_project / f"{NAME}.uproject").read_text(encoding="utf-8"))
    names = [p["Name"] for p in doc["Plugins"]]
    assert names == ["ModelingToolsEditorMode", "FoundryFSDK"]
    assert doc["EngineAssociation"] == GUID

    # 3. Server target
    server = (ue_project / "Source" / f"{NAME}Server.Target.cs").read_text(encoding="utf-8")
    assert "Type = TargetType.Server;" in server
    assert f'ExtraModuleNames.Add("{NAME}");' in server
    assert f"class {NAME}ServerTarget : TargetRules" in server

    # 4. Build.cs dependency inside the private list
    build = (ue_project / "Source" / NAME / f"{NAME}.Build.cs").read_text(encoding="utf-8")
    assert 'PrivateDependencyModuleNames.AddRange(new string[] { "FoundryFSDK" });' in build
    assert build.count('"FoundryFSDK"') == 1

    # 5. protocol version pinned, wizard line gone, include added once
    cpp = (ue_project / "Source" / NAME / f"{NAME}.cpp").read_text(encoding="utf-8")
    assert "GetLocalNetworkVersionOverride" in cpp
    assert f"static constexpr uint32 {NAME}NetProtocolVersion = 1;" in cpp
    assert f"FDefaultGameModuleImpl, {NAME}," not in cpp
    assert f'IMPLEMENT_PRIMARY_GAME_MODULE( F{NAME}Module, {NAME}, "{NAME}" );' in cpp
    assert cpp.count('#include "Misc/NetworkVersion.h"') == 1

    # 6. config + Dockerfile
    cfg = (ue_project / ".foundry" / "config.yml").read_text(encoding="utf-8")
    assert "kind: game-publisher" in cfg
    assert "publisher: foundry" in cfg
    assert "gameId: goo-crew" in cfg
    assert f"serverTarget: {NAME}Server" in cfg
    assert "ueRoot: D:/UnrealEngine" in cfg
    assert f"uprojectPath: {NAME}.uproject" in cfg
    assert "imageName: goo-crew-server" in cfg
    assert not (ue_project / ".foundry" / ".gitignore").exists()  # config.yml is committed for games
    docker = (ue_project / "Docker" / "Dockerfile").read_bytes()
    assert b"\r\n" not in docker
    assert f"/server/{NAME}/Binaries/Linux/{NAME}Server".encode() in docker
    assert b"FOUNDRY_GAME_PORT" in docker and b"FOUNDRY_AUTH_BASE" in docker
    assert "By hand" not in res.output


def test_second_run_changes_nothing(ue_project: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(init, ["--template", "ue5-game", "--game", "goo-crew"]).exit_code == 0
    before = _tree_hash(ue_project)
    res = runner.invoke(init, ["--template", "ue5-game", "--game", "goo-crew"])
    assert res.exit_code == 0, res.output
    assert _tree_hash(ue_project) == before
    assert "already installed (v0.5.0)" in res.output
    assert "already lists FoundryFSDK" in res.output


def test_dry_run_writes_nothing(ue_project: Path) -> None:
    before = _tree_hash(ue_project)
    res = CliRunner().invoke(init, ["--template", "ue5-game", "--dry-run"])
    assert res.exit_code == 0, res.output
    assert _tree_hash(ue_project) == before
    assert "[dry-run]" in res.output
    assert not (ue_project / "Plugins").exists()


def test_slug_derives_from_camel_case(ue_project: Path) -> None:
    res = CliRunner().invoke(init, ["--template", "ue5-game", "--no-plugin"])
    assert res.exit_code == 0, res.output
    assert "gameId: goo-crew" in (ue_project / ".foundry" / "config.yml").read_text(encoding="utf-8")
    assert "skipped (--no-plugin)" in res.output
    assert not (ue_project / "Plugins").exists()


def test_existing_private_deps_are_kept(ue_project: Path) -> None:
    build_cs = ue_project / "Source" / NAME / f"{NAME}.Build.cs"
    build_cs.write_text(
        BUILD_CS.replace("new string[] {  });", 'new string[] { "Slate", "SlateCore" });'), encoding="utf-8"
    )
    assert CliRunner().invoke(init, ["--template", "ue5-game", "--no-plugin"]).exit_code == 0
    assert 'new string[] { "Slate", "SlateCore", "FoundryFSDK" });' in build_cs.read_text(encoding="utf-8")


def test_customized_module_and_build_cs_are_left_alone(ue_project: Path) -> None:
    cpp = ue_project / "Source" / NAME / f"{NAME}.cpp"
    cpp.write_text('#include "Modules/ModuleManager.h"\nIMPLEMENT_PRIMARY_GAME_MODULE(FMyModule, GooCrew, "GooCrew");\n', encoding="utf-8")
    build_cs = ue_project / "Source" / NAME / f"{NAME}.Build.cs"
    build_cs.write_text("public class GooCrew : ModuleRules { }\n", encoding="utf-8")
    res = CliRunner().invoke(init, ["--template", "ue5-game", "--no-plugin"])
    assert res.exit_code == 0, res.output
    assert "FMyModule" in cpp.read_text(encoding="utf-8")
    assert "FoundryFSDK" not in build_cs.read_text(encoding="utf-8")
    assert "By hand" in res.output
    assert "GetLocalNetworkVersionOverride" in res.output
    assert "PrivateDependencyModuleNames" in res.output


def test_launcher_engine_is_reported_not_guessed(ue_project: Path) -> None:
    up = ue_project / f"{NAME}.uproject"
    doc = json.loads(up.read_text(encoding="utf-8"))
    doc["EngineAssociation"] = "5.7"
    up.write_text(json.dumps(doc), encoding="utf-8")
    res = CliRunner().invoke(init, ["--template", "ue5-game", "--no-plugin"])
    assert res.exit_code == 0, res.output
    assert "built from source" in res.output
    cfg = (ue_project / ".foundry" / "config.yml").read_text(encoding="utf-8")
    assert "SOURCE build" in cfg  # placeholder, never a guessed path


def test_no_uproject_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(init, ["--template", "ue5-game"])
    assert res.exit_code == 1
    assert "No .uproject" in res.output


def test_zip_slip_is_refused(ue_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("FoundryFSDK/FoundryFSDK.uplugin", "{}")
        z.writestr("../evil.txt", "x")
    bad = tmp_path / "bad.zip"
    bad.write_bytes(buf.getvalue())
    monkeypatch.setenv(init_ue5.PLUGIN_ZIP_ENV, str(bad))
    res = CliRunner().invoke(init, ["--template", "ue5-game"])
    assert res.exit_code == 1
    assert "outside Plugins/" in res.output
    assert not (tmp_path / "evil.txt").exists()
