"""Lightweight file-based diagnostic logger for runtime debugging."""
from __future__ import annotations

import os
from datetime import datetime, timezone

DIAG_LOG_PATH = os.path.join(os.path.expanduser("~"), "udp_nav_diag.log")
_DIAGNOSTIC_LOGGING_ENABLED = (
    os.getenv("QGIS_UDP_NAV_DIAGNOSTICS", "").strip().lower()
    in {"true", "1", "yes"}
)


def diagnostic_logging_enabled() -> bool:
    return _DIAGNOSTIC_LOGGING_ENABLED


def set_diagnostic_logging_enabled(enabled: bool) -> None:
    global _DIAGNOSTIC_LOGGING_ENABLED
    _DIAGNOSTIC_LOGGING_ENABLED = bool(enabled)


def diag(msg: str) -> None:
    """Append a timestamped diagnostic line to the log file."""
    if not _DIAGNOSTIC_LOGGING_ENABLED:
        return

    try:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        with open(DIAG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass
