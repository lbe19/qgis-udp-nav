"""Lightweight file-based diagnostic logger for runtime debugging."""
from __future__ import annotations

import os
from datetime import datetime, timezone

DIAG_LOG_PATH = os.path.join(os.path.expanduser("~"), "udp_nav_diag.log")


def diag(msg: str) -> None:
    """Append a timestamped diagnostic line to the log file."""
    try:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        with open(DIAG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass
