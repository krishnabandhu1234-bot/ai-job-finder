"""Tests for the background scheduler (section 13/8) - only its
configuration logic (which trigger gets built from which settings);
never waits for an actual scheduled fire."""

from __future__ import annotations

from app.core.constants import ScanTrigger, ScheduleFrequency
from app.core.scheduler import AppScheduler


def test_disabled_by_default_adds_no_job(db_session, app_context):
    scheduler = AppScheduler(app_context)
    scheduler.start()
    try:
        assert scheduler._scheduler.get_job("aijobfinder-scan") is None
    finally:
        scheduler.shutdown()


def test_enabling_daily_adds_a_cron_job(db_session, app_context):
    app_context.settings_repo.set(db_session, "scheduler.enabled", "true")
    app_context.settings_repo.set(db_session, "scheduler.frequency", ScheduleFrequency.DAILY.value)
    app_context.settings_repo.set(db_session, "email.send_time", "07:30")
    db_session.commit()  # AppScheduler.reload() reads via its own session

    scheduler = AppScheduler(app_context)
    scheduler.start()
    try:
        job = scheduler._scheduler.get_job("aijobfinder-scan")
        assert job is not None
    finally:
        scheduler.shutdown()


def test_manual_only_frequency_adds_no_job(db_session, app_context):
    app_context.settings_repo.set(db_session, "scheduler.enabled", "true")
    app_context.settings_repo.set(db_session, "scheduler.frequency", ScheduleFrequency.MANUAL_ONLY.value)
    db_session.commit()

    scheduler = AppScheduler(app_context)
    scheduler.start()
    try:
        assert scheduler._scheduler.get_job("aijobfinder-scan") is None
    finally:
        scheduler.shutdown()


def test_cron_job_runs_with_scheduled_trigger(db_session, app_context):
    app_context.settings_repo.set(db_session, "scheduler.enabled", "true")
    app_context.settings_repo.set(db_session, "scheduler.frequency", ScheduleFrequency.DAILY.value)
    db_session.commit()

    scheduler = AppScheduler(app_context)
    scheduler.start()
    try:
        job = scheduler._scheduler.get_job("aijobfinder-scan")
        assert job.kwargs == {"scan_trigger": ScanTrigger.SCHEDULED.value}
    finally:
        scheduler.shutdown()


def test_run_now_async_records_a_manual_trigger_not_scheduled(db_session, app_context):
    """Regression: `_run()` used to hardcode ScanTrigger.SCHEDULED
    regardless of how it was invoked, so a user-initiated "Run Full
    Pipeline Now" would be misrecorded in History as a scheduled run."""
    scheduler = AppScheduler(app_context)
    scheduler.start()
    try:
        scheduler.run_now_async()
        job = scheduler._scheduler.get_job("aijobfinder-scan-manual")
        assert job.kwargs == {"scan_trigger": ScanTrigger.MANUAL.value}
    finally:
        scheduler.shutdown()


def test_reload_picks_up_changed_settings(db_session, app_context):
    scheduler = AppScheduler(app_context)
    scheduler.start()
    try:
        assert scheduler._scheduler.get_job("aijobfinder-scan") is None
        app_context.settings_repo.set(db_session, "scheduler.enabled", "true")
        app_context.settings_repo.set(db_session, "scheduler.frequency", ScheduleFrequency.EVERY_12_HOURS.value)
        db_session.commit()
        scheduler.reload()
        assert scheduler._scheduler.get_job("aijobfinder-scan") is not None
    finally:
        scheduler.shutdown()
