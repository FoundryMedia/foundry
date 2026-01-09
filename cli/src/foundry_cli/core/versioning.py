from __future__ import annotations

from importlib import metadata
from pathlib import Path

from foundry_cli.core.runtime import resources_dir

PACKAGE_NAME = "foundry-cli"


class VersionResolutionError(RuntimeError):
    pass


def get_local_version() -> str:
    """
    Resolve the Foundry CLI version.

    Resolution order:
      1) Installed package metadata (pip / editable installs)
      2) VERSION resource file (MSI / PyInstaller installs)

    Failure to resolve a version is considered a fatal error and indicates
    a corrupted or incomplete installation.
    """
    # 1) Installed package metadata
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        pass

    # 2) VERSION file
    vfile: Path = resources_dir() / "VERSION"
    if vfile.exists():
        version = vfile.read_text(encoding="utf-8").strip()
        if version:
            return version

    # 3) Fatal: corrupted install
    raise VersionResolutionError(
        "Foundry CLI installation is corrupted.\n"
        "Unable to determine version from package metadata or VERSION file.\n"
        "Please reinstall Foundry CLI using the official installer."
    )
