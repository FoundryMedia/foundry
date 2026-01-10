from __future__ import annotations

from pathlib import Path
import sys


def resources_dir() -> Path:
	"""Return the folder containing packaged resources (e.g. VERSION)."""
	# `resources` is shipped as package data, so it lives beside this file.
	return Path(__file__).resolve().parent.parent / "resources"


def exe_dir() -> Path:
	"""Return the directory containing the running executable.

	In normal Python execution this is typically the Python install/venv folder.
	In a Windows packaged build (e.g. PyInstaller), this is the folder containing
	the shipped `foundry.exe`.
	"""
	return Path(sys.executable).resolve().parent


def version_file_candidates() -> list[Path]:
	"""Return possible VERSION file locations, in priority order.

	We prioritize packaged Windows installs where VERSION is placed next to the
	executable, then fall back to the source/package-data location.
	"""
	return [
		exe_dir() / "VERSION",
		resources_dir() / "VERSION",
	]


__all__ = ["resources_dir", "exe_dir", "version_file_candidates"]
