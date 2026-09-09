"""Tests for the Email Settings page's load/save round-trip (sections
11-12): in particular, that a save never silently overwrites SMTP
credentials that come from .env with blanks - a real bug this page had,
where `_load()` only ever populated fields from the raw settings-table
override (never falling back to .env like the actual sender does), so
saving the page for any reason (e.g. just changing the send time) wiped
out a working .env-only email configuration."""

from __future__ import annotations

import pytest

from app.email.sender import resolve_email_config
from app.ui.pages.email_settings import EmailSettingsPage


@pytest.fixture(autouse=True)
def _no_blocking_message_boxes(monkeypatch):
    # `_save()` shows a modal QMessageBox.information() on success - real
    # UI behavior, but it blocks forever in a headless test (no user to
    # click it), so replace it with a no-op for the duration of this file.
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))


def _make_page(qtbot, app_context):
    page = EmailSettingsPage(app_context)
    qtbot.addWidget(page)
    return page


def test_load_populates_fields_from_env_when_no_db_override_exists(qtbot, db_session, app_context):
    app_context.config.smtp_host = "smtp.example.com"
    app_context.config.smtp_port = 2525
    app_context.config.smtp_username = "env-user@example.com"
    app_context.config.smtp_app_password = "env-app-password"
    app_context.config.email_to = "recipient@example.com"

    page = _make_page(qtbot, app_context)

    assert page.recipient_input.text() == "recipient@example.com"
    assert page.smtp_host_input.text() == "smtp.example.com"
    assert page.smtp_port_input.value() == 2525
    assert page.smtp_username_input.text() == "env-user@example.com"
    assert page.smtp_password_input.text() == "env-app-password"


def test_save_after_load_never_blanks_out_env_configured_credentials(qtbot, db_session, app_context):
    """The actual regression: open the page (which used to leave fields
    blank for .env-sourced values) and save without touching the SMTP
    fields - email must still be sendable afterwards."""
    app_context.config.smtp_host = "smtp.example.com"
    app_context.config.smtp_port = 2525
    app_context.config.smtp_username = "env-user@example.com"
    app_context.config.smtp_app_password = "env-app-password"
    app_context.config.email_to = "recipient@example.com"

    page = _make_page(qtbot, app_context)
    page._save()  # simulates the user just changing e.g. the send time and saving
    db_session.commit()
    db_session.expire_all()

    email_config = resolve_email_config(db_session, app_context)
    assert email_config.is_configured()
    assert email_config.smtp_host == "smtp.example.com"
    assert email_config.smtp_password == "env-app-password"
    assert email_config.recipient == "recipient@example.com"


def test_save_persists_a_value_the_user_actually_changed(qtbot, db_session, app_context):
    app_context.config.smtp_host = "smtp.example.com"
    app_context.config.smtp_username = "env-user@example.com"
    app_context.config.smtp_app_password = "env-app-password"
    app_context.config.email_to = "recipient@example.com"

    page = _make_page(qtbot, app_context)
    page.smtp_host_input.setText("smtp.overridden.example.com")
    page._save()
    db_session.commit()
    db_session.expire_all()

    email_config = resolve_email_config(db_session, app_context)
    assert email_config.smtp_host == "smtp.overridden.example.com"
    # Fields the user didn't touch are still correctly preserved.
    assert email_config.smtp_password == "env-app-password"
