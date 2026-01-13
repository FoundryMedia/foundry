from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR", "SUCCESS"]

DEBUG_HEX = "#29B8DB"
INFO_HEX = "#3B8EEA"
WARN_HEX = "#F5F536"
ERROR_HEX = "#F14C4C"
SUCCESS_HEX = "#23D18B"
RESET_HEX = "#FFFFFF"


@dataclass(frozen=True)
class LogLine:
    timestamp: datetime
    level: LogLevel
    message: str


def format_log_line(line: LogLine) -> str:
    """Format a log line with Rich markup.

    Pattern:
      {timestamp}(bold white) {log_level}(bold + color) {message}
    """

    ts = line.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    ts_s = f"[bold {RESET_HEX}]{ts}[/bold {RESET_HEX}]"

    if line.level == "DEBUG":
        lvl_s = f"[bold {DEBUG_HEX}]DEBUG[/bold {DEBUG_HEX}]"
    elif line.level == "INFO":
        lvl_s = f"[bold {INFO_HEX}]INFO[/bold {INFO_HEX}]"
    elif line.level == "WARN":
        lvl_s = f"[bold {WARN_HEX}]WARN[/bold {WARN_HEX}]"
    elif line.level == "SUCCESS":
        lvl_s = f"[bold {SUCCESS_HEX}]SUCCESS[/bold {SUCCESS_HEX}]"
    else:
        lvl_s = f"[bold {ERROR_HEX}]ERROR[/bold {ERROR_HEX}]"

    return f"{ts_s} {lvl_s} {line.message}"
