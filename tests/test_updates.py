"""Tests for app update checking (`app/core/updates.py`).

The behaviour that matters: it must never break anything. No network, a
404, garbage JSON, a nonsense version string - every one of those has to
resolve to "no update known" rather than an exception reaching a scan or
an email send.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app import __version__
from app.core import updates
from app.database.models import utc_now
from app.core.updates import (
    SETTING_ENABLED,
    SETTING_LAST_CHECKED,
    SETTING_MANIFEST_URL,
    UpdateInfo,
    _is_newer,
    _parse_manifest,
    check_for_update,
)


# --------------------------------------------------------------------------
# Version comparison
# --------------------------------------------------------------------------

def test_newer_version_detected():
    assert _is_newer("0.2.0", "0.1.0") is True
    assert _is_newer("1.0.0", "0.9.9") is True


def test_same_or_older_version_is_not_an_update():
    assert _is_newer("0.1.0", "0.1.0") is False
    assert _is_newer("0.1.0", "0.2.0") is False


def test_version_comparison_is_numeric_not_alphabetical():
    """A string compare would rank 0.9.0 above 0.10.0, which is exactly
    backwards and would stop advertising updates after 0.9."""
    assert _is_newer("0.10.0", "0.9.0") is True
    assert _is_newer("0.9.0", "0.10.0") is False


def test_versions_of_differing_length_compare_sensibly():
    assert _is_newer("0.2", "0.1.9") is True
    assert _is_newer("0.1.0", "0.1") is False  # 0.1.0 == 0.1


def test_v_prefix_is_tolerated():
    assert _is_newer("v0.2.0", "0.1.0") is True


def test_unparseable_versions_never_claim_an_update():
    """Nagging someone about a garbage version string is worse than
    staying quiet."""
    assert _is_newer("banana", "0.1.0") is False
    assert _is_newer("0.2.0", "banana") is False
    assert _is_newer("", "0.1.0") is False


# --------------------------------------------------------------------------
# Manifest parsing
# --------------------------------------------------------------------------

def test_parse_valid_manifest():
    info = _parse_manifest({
        "version": "0.5.0",
        "download_url": "https://example.com/Setup.exe",
        "notes": "Faster matching",
    })
    assert info.latest_version == "0.5.0"
    assert info.download_url == "https://example.com/Setup.exe"
    assert info.notes == "Faster matching"


def test_parse_manifest_accepts_alternate_key_names():
    info = _parse_manifest({"latest_version": "0.5.0", "url": "https://example.com/x"})
    assert info.latest_version == "0.5.0"
    assert info.download_url == "https://example.com/x"


def test_parse_manifest_rejects_junk():
    assert _parse_manifest(None).latest_version == ""
    assert _parse_manifest([]).latest_version == ""
    assert _parse_manifest({}).latest_version == ""
    assert _parse_manifest({"version": "not-a-version"}).latest_version == ""


def test_parse_manifest_truncates_long_notes():
    info = _parse_manifest({"version": "0.5.0", "notes": "x" * 5000})
    assert len(info.notes) <= 500


# --------------------------------------------------------------------------
# UpdateInfo
# --------------------------------------------------------------------------

def test_update_info_defaults_to_current_version_and_no_update():
    info = UpdateInfo()
    assert info.current_version == __version__
    assert info.update_available is False
    assert "up to date" in info.summary_line()


def test_summary_line_includes_the_download_link():
    info = UpdateInfo(current_version="0.1.0", latest_version="0.2.0",
                      download_url="https://example.com/Setup.exe")
    line = info.summary_line()
    assert "0.2.0" in line and "0.1.0" in line
    assert "https://example.com/Setup.exe" in line


# --------------------------------------------------------------------------
# check_for_update
# --------------------------------------------------------------------------

def test_check_is_inert_when_no_manifest_url_configured(db_session, app_context):
    """A build that ships without an update URL must never phone home."""
    called = []
    info = check_for_update(db_session, app_context)
    assert info.update_available is False
    assert called == []


def test_check_can_be_disabled(db_session, app_context, monkeypatch):
    app_context.settings_repo.set(db_session, SETTING_MANIFEST_URL, "https://example.com/m.json")
    app_context.settings_repo.set(db_session, SETTING_ENABLED, "false")
    monkeypatch.setattr(
        "app.jobs.http_client.get_json",
        lambda *a, **kw: pytest.fail("must not fetch when disabled"),
    )

    assert check_for_update(db_session, app_context).update_available is False


def test_check_reads_the_manifest_and_reports_an_update(db_session, app_context, monkeypatch):
    app_context.settings_repo.set(db_session, SETTING_MANIFEST_URL, "https://example.com/m.json")
    monkeypatch.setattr(
        "app.jobs.http_client.get_json",
        lambda url, **kw: {"version": "99.0.0", "download_url": "https://example.com/Setup.exe"},
    )

    info = check_for_update(db_session, app_context)

    assert info.update_available is True
    assert info.latest_version == "99.0.0"


def test_a_network_failure_is_not_an_error(db_session, app_context, monkeypatch):
    """Offline, DNS failure, 404 - all just mean "we don't know of an
    update", which must never surface as an exception to a scan or an
    email send."""
    app_context.settings_repo.set(db_session, SETTING_MANIFEST_URL, "https://example.com/m.json")

    def _boom(url, **kwargs):
        raise ConnectionError("no network")

    monkeypatch.setattr("app.jobs.http_client.get_json", _boom)

    info = check_for_update(db_session, app_context)
    assert info.update_available is False


def test_malformed_manifest_is_not_an_error(db_session, app_context, monkeypatch):
    app_context.settings_repo.set(db_session, SETTING_MANIFEST_URL, "https://example.com/m.json")
    monkeypatch.setattr("app.jobs.http_client.get_json", lambda url, **kw: "not a dict")

    assert check_for_update(db_session, app_context).update_available is False


def test_check_is_rate_limited_to_once_a_day(db_session, app_context, monkeypatch):
    """A scheduler running every 12 hours must not re-request the
    manifest on every single run."""
    app_context.settings_repo.set(db_session, SETTING_MANIFEST_URL, "https://example.com/m.json")
    app_context.settings_repo.set(
        db_session, SETTING_LAST_CHECKED, utc_now().isoformat(timespec="seconds")
    )
    fetches = []
    monkeypatch.setattr(
        "app.jobs.http_client.get_json",
        lambda url, **kw: fetches.append(url) or {"version": "99.0.0"},
    )

    check_for_update(db_session, app_context)

    assert fetches == []


def test_force_bypasses_the_rate_limit(db_session, app_context, monkeypatch):
    """The Settings page's "Check now" button must actually check."""
    app_context.settings_repo.set(db_session, SETTING_MANIFEST_URL, "https://example.com/m.json")
    app_context.settings_repo.set(
        db_session, SETTING_LAST_CHECKED, utc_now().isoformat(timespec="seconds")
    )
    fetches = []
    monkeypatch.setattr(
        "app.jobs.http_client.get_json",
        lambda url, **kw: fetches.append(url) or {"version": "99.0.0"},
    )

    info = check_for_update(db_session, app_context, force=True)

    assert len(fetches) == 1
    assert info.update_available is True


def test_a_known_pending_update_is_still_reported_between_checks(db_session, app_context, monkeypatch):
    """Between rate-limited checks the user should still be told about an
    update found earlier, not shown "up to date"."""
    app_context.settings_repo.set(db_session, SETTING_MANIFEST_URL, "https://example.com/m.json")
    monkeypatch.setattr("app.jobs.http_client.get_json", lambda url, **kw: {"version": "99.0.0"})
    check_for_update(db_session, app_context)  # first check records it

    monkeypatch.setattr(
        "app.jobs.http_client.get_json",
        lambda *a, **kw: pytest.fail("should be rate-limited now"),
    )
    second = check_for_update(db_session, app_context)

    assert second.update_available is True
    assert second.latest_version == "99.0.0"

