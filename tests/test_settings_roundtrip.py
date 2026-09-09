"""Settings load/save round-trip regressions across a few pages -
consolidated from an ad-hoc manual smoke-test script. Each of these
covers a real bug that was previously fixed: an API key override not
round-tripping through save/load/clear, a QTimeEdit value not
persisting, and a numeric "0" value being treated as falsy and reset to
its default instead of being saved as an explicit zero."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QTime
from PySide6.QtWidgets import QMessageBox

from app.ui.pages.ai_settings import AISettingsPage
from app.ui.pages.email_settings import EmailSettingsPage
from app.ui.pages.job_profile import JobProfilePage


@pytest.fixture(autouse=True)
def _no_blocking_message_boxes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))


def test_ai_settings_api_key_override_round_trips_and_clears(qtbot, db_session, app_context):
    page = AISettingsPage(app_context)
    qtbot.addWidget(page)

    page.anthropic_key_input.setText("sk-test-override")
    page._save()
    db_session.commit()
    db_session.expire_all()

    page.anthropic_key_input.clear()
    page._load()
    assert page.anthropic_key_input.text() == "sk-test-override"

    page._clear_anthropic_key()
    assert page.anthropic_key_input.text() == ""
    db_session.commit()
    db_session.expire_all()
    page._load()
    assert page.anthropic_key_input.text() == ""


def test_ai_settings_local_llm_url_round_trips(qtbot, db_session, app_context):
    page = AISettingsPage(app_context)
    qtbot.addWidget(page)

    page.llm_provider_combo.setCurrentIndex(page.llm_provider_combo.findData("local"))
    page.llm_model_input.setText("llama3.1")
    page.local_llm_url_input.setText("http://localhost:11434/v1")
    page._save()
    db_session.commit()
    db_session.expire_all()

    page.local_llm_url_input.clear()
    page.llm_model_input.clear()
    page.llm_provider_combo.setCurrentIndex(page.llm_provider_combo.findData("anthropic"))
    page._load()

    assert page.llm_provider_combo.currentData() == "local"
    assert page.llm_model_input.text() == "llama3.1"
    assert page.local_llm_url_input.text() == "http://localhost:11434/v1"


def test_ai_settings_local_llm_field_only_shown_for_local_provider(qtbot, db_session, app_context):
    """The endpoint URL field is meaningless noise for Anthropic/OpenAI/
    none - it should only appear once "local" is actually selected."""
    page = AISettingsPage(app_context)
    qtbot.addWidget(page)

    # `isVisible()` reflects the whole ancestor chain and is unreliable
    # for a widget that's never been `.show()`-n (as in this test) - the
    # explicit hidden flag `setVisible()` toggles is what `isHidden()`
    # checks instead, regardless of whether the window is actually shown.
    page.llm_provider_combo.setCurrentIndex(page.llm_provider_combo.findData("anthropic"))
    assert page.local_llm_url_input.isHidden() is True

    page.llm_provider_combo.setCurrentIndex(page.llm_provider_combo.findData("local"))
    assert page.local_llm_url_input.isHidden() is False


def test_email_settings_send_time_round_trips(qtbot, db_session, app_context):
    page = EmailSettingsPage(app_context)
    qtbot.addWidget(page)

    page.send_time_input.setTime(QTime(7, 30))
    page._save()
    db_session.commit()
    db_session.expire_all()

    page.send_time_input.setTime(QTime(0, 0))
    page._load()
    assert page.send_time_input.time() == QTime(7, 30)


def test_job_profile_min_email_score_zero_round_trips_not_reset_to_default(qtbot, db_session, app_context):
    """`min_email_score=0` is falsy in Python - a save/load path that
    uses `value or 85` instead of `value if value is not None else 85`
    would silently discard an explicit 0 and reset it to the 85 default."""
    page = JobProfilePage(app_context)
    qtbot.addWidget(page)

    page.min_score_input.setValue(0)
    page._save()
    db_session.commit()
    db_session.expire_all()

    page.min_score_input.setValue(50)
    page._load()
    assert page.min_score_input.value() == 0
