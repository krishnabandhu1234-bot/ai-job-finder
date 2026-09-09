"""Application-wide logging configuration.

Logs go to both a rotating file (under the app data dir, so they survive
and are inspectable from the "Logs" UI page) and the console (useful when
running from source). Every scan/match/email operation should log through
this, never `print()`.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from app.core import paths

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(logs_dir: Path, level: str = "INFO") -> None:
    """Idempotent: safe to call multiple times (e.g. in tests)."""
    global _configured

    root = logging.getLogger()
    root.setLevel(level)

    if _configured:
        return

    logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "aijobfinder.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # A frozen, windowed (console=False) PyInstaller build has no console -
    # sys.stdout/sys.stderr are None there, which would make this handler a
    # silent no-op. Only attach it when running from source, where it's
    # actually useful.
    if not paths.is_frozen() and sys.stdout is not None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    # Third-party libraries are noisy at DEBUG/INFO; keep them at WARNING
    # unless the app itself is running at DEBUG.
    if level.upper() != "DEBUG":
        for noisy in ("urllib3", "httpx", "sqlalchemy.engine"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info("Logging initialized (level=%s, dir=%s)", level, logs_dir)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def tail_log_file(logs_dir: Path, max_lines: int = 500) -> list[str]:
    """Used by the Logs UI page to show recent activity without loading the
    entire (potentially multi-MB) log file into memory."""
    log_file = logs_dir / "aijobfinder.log"
    if not log_file.exists():
        return []
    with log_file.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-max_lines:]]
