"""Core primitives.

`core` is reserved for internal runtime and CLI plumbing.
Release/version/update helpers live in the top-level `foundry_cli.release` package.
"""

from .errors import FoundryError
from .runtime import resources_dir

__all__ = ["FoundryError", "resources_dir"]
