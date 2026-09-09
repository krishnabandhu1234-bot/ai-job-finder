"""App update checking and notification.

The user asked to be told when a new version of the app is available,
rather than having to go looking. Two delivery routes, both driven from
here so they can't disagree about what "current" means:

  * the daily email footer mentions it (the user reads that anyway), and
  * the Settings page shows it when they open the app.

Design constraints that shaped this:

  * **It must not need a server this project doesn't have.** The check
    reads a small JSON manifest over HTTPS at a configurable URL. Ship
    that file anywhere static (a GitHub release asset, raw.githubusercontent,
    S3, a personal site) and update checking works; leave the URL unset
    and the whole feature is inert.
  * **It must never break the app.** No network at all, a 404, malformed
    JSON, a manifest advertising a garbage version - every one of those
    resolves to "no update known", never an exception reaching a caller
    and never a stalled scan. Checking is also rate-limited to once a day
    so a scheduled hourly run doesn't hammer the manifest host.
  * **It never downloads or installs anything by itself.** It reports a
    version and a link. Silently self-updating a desktop app that manages
    someone's job search is a bigger promise than this warrants, and it
    would happen behind their back.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass

from app import __version__
from app.database.models import utc_now

logger = logging.getLogger(__name__)

SETTING_MANIFEST_URL = "updates.manifest_url"
SETTING_LAST_CHECKED = "updates.last_checked_at"
SETTING_LATEST_SEEN = "updates.latest_version_seen"
SETTING_ENABLED = "updates.check_enabled"

CHECK_INTERVAL_HOURS = 24
_TIMEOUT_SECONDS = 10.0

# A version string we're willing to compare. Anything else in a manifest
# is treated as absent rather than guessed at.
_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


@dataclass
class UpdateInfo:
    """What (if anything) is newer than what's running."""

    current_version: str = __version__
    latest_version: str = ""
    download_url: str = ""
    notes: str = ""

    @property
    def update_available(self) -> bool:
        return bool(self.latest_version) and _is_newer(self.latest_version, self.current_version)

    def summary_line(self) -> str:
        if not self.update_available:
            return f"AI Job Finder v{self.current_version} (up to date)"
        line = f"Update available: v{self.latest_version} (you have v{self.current_version})"
        if self.download_url:
            line += f" - {self.download_url}"
        return line


def _parse_version(value: str) -> tuple[int, ...] | None:
    value = (value or "").strip().lstrip("vV")
    if not _VERSION_RE.match(value):
        return None
    return tuple(int(part) for part in value.split("."))


def _is_newer(candidate: str, current: str) -> bool:
    """Numeric, component-wise comparison, so 0.10.0 correctly beats
    0.9.0 (a plain string compare would get that backwards). An
    unparseable version on either side means "don't claim an update" -
    nagging someone about a bad version string is worse than silence."""
    new = _parse_version(candidate)
    old = _parse_version(current)
    if new is None or old is None:
        return False
    length = max(len(new), len(old))
    return new + (0,) * (length - len(new)) > old + (0,) * (length - len(old))


def _parse_manifest(data) -> UpdateInfo:
    """Reads the published manifest, which looks like:

        {"version": "0.2.0",
         "download_url": "https://.../AIJobFinder-Setup.exe",
         "notes": "What changed"}
    """
    info = UpdateInfo()
    if not isinstance(data, dict):
        return info
    version = str(data.get("version") or data.get("latest_version") or "").strip()
    if _parse_version(version) is None:
        if version:
            logger.info("Update manifest advertised an unusable version %r - ignoring.", version)
        return info
    info.latest_version = version.lstrip("vV")
    info.download_url = str(data.get("download_url") or data.get("url") or "").strip()
    info.notes = str(data.get("notes") or "").strip()[:500]
    return info


def check_for_update(session, context, force: bool = False) -> UpdateInfo:
    """Returns what's known about a newer version. Never raises.

    Rate-limited to once per `CHECK_INTERVAL_HOURS` unless `force` (the
    Settings page's "Check now" button), so a frequent scheduler doesn't
    re-request the manifest on every run."""
    repo = context.settings_repo
    info = UpdateInfo()

    if not repo.get_bool(session, SETTING_ENABLED, True):
        return info

    manifest_url = repo.get(session, SETTING_MANIFEST_URL, context.config.update_manifest_url)
    if not manifest_url:
        return info  # feature not configured for this build - stay inert

    if not force and not _due_for_check(repo.get(session, SETTING_LAST_CHECKED, "")):
        # Report what the last successful check found rather than nothing,
        # so the email/Settings still show a pending update between checks.
        cached = repo.get(session, SETTING_LATEST_SEEN, "")
        if cached:
            info.latest_version = cached
        return info

    try:
        from app.jobs.http_client import get_json

        info = _parse_manifest(get_json(manifest_url, timeout=_TIMEOUT_SECONDS))
    except Exception as exc:
        # Offline, DNS failure, 404, bad JSON - all just mean "we don't
        # know of an update", which is the safe answer.
        logger.info("Update check could not complete (%s) - continuing without it.", exc)
        return UpdateInfo()

    repo.set(session, SETTING_LAST_CHECKED, utc_now().isoformat(timespec="seconds"))
    if info.latest_version:
        repo.set(session, SETTING_LATEST_SEEN, info.latest_version)
    return info


def _due_for_check(last_checked_iso: str) -> bool:
    if not last_checked_iso:
        return True
    try:
        last = dt.datetime.fromisoformat(last_checked_iso)
    except ValueError:
        return True
    return (utc_now() - last) >= dt.timedelta(hours=CHECK_INTERVAL_HOURS)
