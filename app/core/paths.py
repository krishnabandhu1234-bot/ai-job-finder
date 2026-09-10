"""Resolves filesystem locations for app data, logs, and resources.

Must work identically whether running from source (`python main.py`) or
from a PyInstaller-frozen executable, where `sys.executable` points at the
.exe and bundled read-only resources live under `sys._MEIPASS`.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "AIJobFinder"


def is_frozen() -> bool:
    """True when running inside a PyInstaller-built executable."""
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    """Root of the source tree when running from source.

    Not meaningful (and not used) when frozen — use `resource_path` instead.
    """
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    """Path to a bundled, read-only resource (e.g. icons, HTML email templates).

    Resolves against the PyInstaller extraction dir when frozen, otherwise
    against the source tree.
    """
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = project_root()
    return base.joinpath(*parts)


def default_data_dir() -> Path:
    """Writable per-user directory for the SQLite DB, logs, and uploaded files.

    Uses %LOCALAPPDATA%\\AIJobFinder on Windows, falling back to a local
    ``data`` folder next to the project when LOCALAPPDATA isn't set (e.g.
    some CI/dev environments).
    """
    import os

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    if is_frozen():
        return Path(sys.executable).parent / "data"
    return project_root() / "data"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def browsers_dir() -> Path:
    """Where the optional headless-browser (Playwright/Chromium) files
    live, for the "any career page" job source's JS-rendering fallback.

    Kept under the writable per-user data dir rather than next to the
    app itself - a per-machine install under Program Files usually isn't
    writable by a normal user, and Playwright's own default location can
    collide across apps that bundle different versions."""
    return ensure_dir(default_data_dir() / "browsers")
