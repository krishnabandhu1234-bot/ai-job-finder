"""Windows "start at login" registration (section 13: "Ideally support
Windows startup/background operation").

Deliberately the simplest mechanism available: a `.lnk` shortcut in the
current user's Startup folder, which Windows Explorer launches
automatically at login - no admin rights, no registry Run-key edits, and
trivially reversible (delete the one file). Only meaningful for a frozen
build (there's no single "AIJobFinder.exe" to point at when running from
source), so this is a no-op with a clear reason when running from source.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from app.core import paths

logger = logging.getLogger(__name__)

_SHORTCUT_NAME = "AI Job Finder.lnk"


def _startup_folder() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def is_supported() -> bool:
    return paths.is_frozen() and _startup_folder() is not None


def _shortcut_path() -> Path | None:
    folder = _startup_folder()
    return folder / _SHORTCUT_NAME if folder else None


def is_enabled() -> bool:
    shortcut = _shortcut_path()
    return shortcut is not None and shortcut.exists()


def set_enabled(enabled: bool) -> None:
    """Raises `RuntimeError` with a user-safe message on failure - never
    silently no-ops on an explicit user request (section 23)."""
    if not is_supported():
        raise RuntimeError(
            "Start with Windows is only available in the installed application, "
            "not when running from source."
        )
    shortcut = _shortcut_path()
    if not enabled:
        if shortcut.exists():
            shortcut.unlink()
        return

    try:
        import win32com.client  # provided by pywin32, a PySide6/PyInstaller dependency
    except ImportError as exc:
        raise RuntimeError("Could not create the startup shortcut (pywin32 not available).") from exc

    target = sys.executable
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut_obj = shell.CreateShortCut(str(shortcut))
    shortcut_obj.Targetpath = target
    shortcut_obj.WorkingDirectory = str(Path(target).parent)
    shortcut_obj.IconLocation = target
    shortcut_obj.save()
    logger.info("Startup shortcut created at %s", shortcut)
