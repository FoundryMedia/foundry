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


def internal_dir() -> Path:
	"""Return the _internal directory for PyInstaller onedir builds.

	This is the home directory for packaged builds where VERSION, logs/, and
	other runtime files live.
	"""
	return exe_dir() / "_internal"


def is_packaged_build() -> bool:
	"""Return True if running from a PyInstaller packaged build."""
	return internal_dir().exists()


def version_file_candidates() -> list[Path]:
	"""Return possible VERSION file locations, in priority order.

	We prioritize packaged Windows installs where VERSION is in _internal/
	for PyInstaller onedir builds, then fall back to source/package-data location.
	"""
	return [
		internal_dir() / "VERSION",
		exe_dir() / "VERSION",
		resources_dir() / "VERSION",
	]


__all__ = ["resources_dir", "exe_dir", "internal_dir", "is_packaged_build", "version_file_candidates"]
