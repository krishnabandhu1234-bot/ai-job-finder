"""Tests for the daily-email orchestration (section 11): marking jobs
notified only after a successful send, and never marking them on
failure so they're retried."""

from __future__ import annotations

import app.email.service as service_module
from app.database.models import EmailHistory, Job, JobMatch, JobSourceConfig
from app.email.sender import EmailSendError


def _seed(session, context, score=90.0):
    context.config.email_to = "test@example.com"
    user = context.users_repo.get_or_create_default_user(session, "test@example.com")
    profile = context.candidate_profile_repo.get_current(session, user.id)
    context.preferences_repo.save(
        session, context.preferences_repo.get_active(session, user.id),
        min_email_score=85, max_email_jobs=15,
    )
    source = JobSourceConfig(name="Demo", source_type="demo")
    session.add(source)
    session.flush()
    job = Job(external_job_id="1", source_id=source.id, company="NVIDIA", title="Engineer", is_active=True)
    session.add(job)
    session.flush()
    session.add(
        JobMatch(job_id=job.id, candidate_profile_id=profile.id, overall_score=score, passed_hard_filters=True)
    )
    session.flush()
    return job


def test_no_qualifying_jobs_skips_send(db_session, app_context, monkeypatch):
    called = []
    monkeypatch.setattr(service_module, "send_email", lambda *a, **kw: called.append(1))
    _seed(db_session, app_context, score=50.0)  # below default 85 threshold

    result = service_module.send_daily_report_now(db_session, app_context)

    assert result.sent is False
    assert called == []


def test_successful_send_marks_jobs_notified_and_records_history(db_session, app_context, monkeypatch):
    monkeypatch.setattr(service_module, "send_email", lambda *a, **kw: None)
    job = _seed(db_session, app_context, score=95.0)

    result = service_module.send_daily_report_now(db_session, app_context)

    assert result.sent is True
    db_session.refresh(job)
    assert job.notified is True
    assert job.notification_date is not None
    history = db_session.query(EmailHistory).all()
    assert len(history) == 1
    assert history[0].status == "sent"


def test_failed_send_does_not_mark_notified_and_records_failure(db_session, app_context, monkeypatch):
    def _raise(*a, **kw):
        raise EmailSendError("SMTP login failed")

    monkeypatch.setattr(service_module, "send_email", _raise)
    job = _seed(db_session, app_context, score=95.0)

    result = service_module.send_daily_report_now(db_session, app_context)

    assert result.sent is False
    assert result.error == "SMTP login failed"
    db_session.refresh(job)
    assert job.notified is False
    history = db_session.query(EmailHistory).all()
    assert len(history) == 1
    assert history[0].status == "failed"


def test_email_settings_max_jobs_setting_overrides_preferences_column(db_session, app_context, monkeypatch):
    """The Email Settings page's "Max jobs per email" field writes to the
    `email.max_jobs` setting, not the `UserPreferences.max_email_jobs`
    column - the sender must honor that field, not silently ignore it."""
    sent = []
    monkeypatch.setattr(service_module, "send_email", lambda *a, **kw: sent.append(1))
    context = app_context
    context.config.email_to = "test@example.com"
    user = context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = context.candidate_profile_repo.get_current(db_session, user.id)
    source = JobSourceConfig(name="Demo", source_type="demo")
    db_session.add(source)
    db_session.flush()
    for i in range(3):
        job = Job(external_job_id=str(i), source_id=source.id, company=f"Co{i}", title=f"Engineer {i}", is_active=True)
        db_session.add(job)
        db_session.flush()
        db_session.add(
            JobMatch(job_id=job.id, candidate_profile_id=profile.id, overall_score=95.0, passed_hard_filters=True)
        )
    db_session.flush()
    context.settings_repo.set(db_session, "email.max_jobs", "1")

    result = service_module.send_daily_report_now(db_session, context)

    assert result.job_count == 1


def test_second_run_does_not_resend_already_notified_job(db_session, app_context, monkeypatch):
    sent_count = {"n": 0}

    def _send(*a, **kw):
        sent_count["n"] += 1

    monkeypatch.setattr(service_module, "send_email", _send)
    _seed(db_session, app_context, score=95.0)

    first = service_module.send_daily_report_now(db_session, app_context)
    second = service_module.send_daily_report_now(db_session, app_context)

    assert first.sent is True
    assert second.sent is False
    assert sent_count["n"] == 1
