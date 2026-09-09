"""Tests for the Dashboard's update banner (`app/ui/pages/dashboard.py`).

A pushed update has to reach the user somewhere they'll actually see it
without hunting through Settings, and be actionable from right there -
that's what this covers, not the rest of the Dashboard's rendering."""

from __future__ import annotations

import pytest

from app.core import updates as updates_module
from app.ui.pages.dashboard import DashboardPage

pytest.importorskip("PySide6")


@pytest.fixture
def page(qtbot, db_session, app_context):
    app_context.config.email_to = "test@example.com"
    widget = DashboardPage(app_context)
    qtbot.addWidget(widget)
    return widget


def test_banner_hidden_when_no_update_is_available(page, monkeypatch):
    monkeypatch.setattr(
        updates_module, "check_for_update",
        lambda session, context, force=False: updates_module.UpdateInfo(),
    )

    page.refresh()

    assert page.update_banner.isHidden()


def test_banner_shown_with_working_download_button(page, monkeypatch, qtbot):
    info = updates_module.UpdateInfo(
        current_version="0.1.0", latest_version="0.2.0",
        download_url="https://example.com/Setup.exe", notes="Bug fixes",
    )
    monkeypatch.setattr(
        updates_module, "check_for_update", lambda session, context, force=False: info
    )

    page.refresh()

    assert not page.update_banner.isHidden()
    assert "0.2.0" in page.update_banner_label.text()
    assert "Bug fixes" in page.update_banner_label.text()
    assert page.update_download_button.isEnabled()

    opened = []
    monkeypatch.setattr("app.ui.pages.dashboard.webbrowser.open", lambda url: opened.append(url))
    qtbot.mouseClick(page.update_download_button, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.LeftButton)

    assert opened == ["https://example.com/Setup.exe"]


def test_banner_never_crashes_the_dashboard_if_the_check_fails(page, monkeypatch):
    def _raise(session, context, force=False):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(updates_module, "check_for_update", _raise)

    page.refresh()  # must not raise

    assert page.update_banner.isHidden()
