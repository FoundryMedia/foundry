"""Foundry CLI logging and error handling.

Provides centralized logging that writes to the appropriate location:
- Source builds: resources directory
- Windows exe: logs directory next to foundry.exe
"""
from __future__ import annotations

import sys
import os
import traceback
import contextlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType


def get_log_directory() -> Path:
    """Get the appropriate log directory based on how Foundry is running.
    
    - For source/editable installs: <foundry_cli>/resources/logs
    - For frozen exe: <exe_dir>/logs
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        exe_dir = Path(sys.executable).parent
        log_dir = exe_dir / "logs"
    else:
        # Running from source
        # Go up from foundry_cli/core/logging.py to foundry_cli/resources/logs
        module_dir = Path(__file__).parent.parent
        log_dir = module_dir / "resources" / "logs"
    
    # Create if doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_crash_log_path() -> Path:
    """Get path for a new crash log file."""
    log_dir = get_log_directory()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return log_dir / f"crash_{timestamp}.log"


def write_crash_log(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: "TracebackType | None",
    context: str = "",
) -> Path:
    """Write exception details to a crash log file.
    
    Returns the path to the created log file.
    """
    log_path = get_crash_log_path()
    
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Foundry CLI Crash Log\n")
        f.write(f"{'=' * 50}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"Python: {sys.version}\n")
        f.write(f"Platform: {sys.platform}\n")
        if context:
            f.write(f"Context: {context}\n")
        f.write(f"\n{'=' * 50}\n")
        f.write(f"Exception: {exc_type.__name__}: {exc_value}\n")
        f.write(f"{'=' * 50}\n\n")
        
        if exc_tb:
            f.write("Traceback:\n")
            f.write("".join(traceback.format_tb(exc_tb)))
        
        f.write(f"\n{exc_type.__name__}: {exc_value}\n")
    
    return log_path


class _NullWriter:
    """A writer that discards everything."""
    def write(self, *args, **kwargs):
        pass
    def flush(self, *args, **kwargs):
        pass


def suppress_async_cleanup_warnings() -> None:
    """Suppress the asyncio cleanup warnings that occur on Windows.
    
    These are "Exception ignored in __del__" messages that Python prints
    directly to stderr when the event loop closes before subprocess
    transports are properly cleaned up. They're not actual errors.
    """
    import warnings
    import atexit
    
    # Filter out ResourceWarning from asyncio transports
    warnings.filterwarnings(
        "ignore",
        message="unclosed transport",
        category=ResourceWarning,
    )
    
    # Set up unraisablehook to suppress asyncio cleanup errors
    def quiet_unraisablehook(unraisable):
        # Suppress asyncio cleanup errors silently
        exc_type = unraisable.exc_type
        if exc_type in (ValueError, OSError, BrokenPipeError, RuntimeError):
            # Check if it's from asyncio by looking at the traceback or object
            err_str = str(unraisable.exc_value) if unraisable.exc_value else ""
            if any(x in err_str for x in ["Event loop is closed", "closed pipe", "I/O operation"]):
                return  # Suppress
            if unraisable.object is not None:
                obj_type = type(unraisable.object).__name__
                obj_module = type(unraisable.object).__module__ or ""
                if "Transport" in obj_type or "asyncio" in obj_module:
                    return  # Suppress
        
        # For other unraisable exceptions, write to log file instead of stderr
        try:
            log_path = write_crash_log(
                exc_type,
                unraisable.exc_value,
                unraisable.exc_traceback,
                context=f"Unraisable in {unraisable.object!r}" if unraisable.object else "Unraisable exception"
            )
        except Exception:
            pass  # Can't even log - just suppress
    
    sys.unraisablehook = quiet_unraisablehook
    
    # Also register an atexit handler to suppress stderr during final cleanup
    original_stderr = sys.stderr
    
    def suppress_final_cleanup():
        """Redirect stderr to null during Python's final cleanup phase."""
        # Replace stderr to suppress any remaining __del__ messages
        sys.stderr = _NullWriter()
    
    atexit.register(suppress_final_cleanup)
