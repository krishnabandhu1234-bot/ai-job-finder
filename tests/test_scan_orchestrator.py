"""Tests for the scan orchestrator: fetch -> normalize -> dedupe -> record
ScanHistory, across all enabled sources, with one failing source never
stopping the others."""

from __future__ import annotations

from app.core.constants import ScanStatus
from app.database.models import Job, JobSourceConfig, ScanHistory
from app.jobs.scan_orchestrator import run_scan


def _add_source(session, name, source_type, config=None, enabled=True) -> JobSourceConfig:
    source = JobSourceConfig(name=name, source_type=source_type, config=config or {}, enabled=enabled)
    session.add(source)
    session.flush()
    return source


def test_scan_with_only_demo_source_creates_jobs_and_records_history(db_session):
    _add_source(db_session, "Demo", "demo")

    summary = run_scan(db_session)

    assert summary.jobs_retrieved > 0
    assert summary.new_jobs == summary.jobs_retrieved
    assert summary.sources_failed == []

    jobs = db_session.query(Job).all()
    assert len(jobs) == summary.jobs_retrieved
    assert all(job.company for job in jobs)  # never a blank/fabricated job

    scan = db_session.get(ScanHistory, summary.scan_history_id)
    assert scan.status == ScanStatus.SUCCESS.value
    assert scan.completed_at is not None
    assert scan.new_jobs_found == summary.new_jobs


def test_rescanning_unchanged_demo_source_finds_no_new_jobs(db_session):
    _add_source(db_session, "Demo", "demo")

    first = run_scan(db_session)
    second = run_scan(db_session)

    assert first.new_jobs > 0
    assert second.new_jobs == 0
    assert second.updated_jobs == first.jobs_retrieved


def test_disabled_source_is_not_scanned(db_session):
    _add_source(db_session, "Demo", "demo", enabled=False)

    summary = run_scan(db_session)

    assert summary.jobs_retrieved == 0
    assert summary.sources_scanned == []
    assert db_session.query(Job).count() == 0


def test_source_with_missing_config_fails_without_stopping_other_sources(db_session):
    _add_source(db_session, "Broken Greenhouse", "greenhouse", config={})  # missing board_token
    _add_source(db_session, "Demo", "demo")

    summary = run_scan(db_session)

    assert "Broken Greenhouse" in summary.sources_failed
    assert "Demo" in summary.sources_scanned
    assert summary.jobs_retrieved > 0  # demo source still ran

    scan = db_session.get(ScanHistory, summary.scan_history_id)
    assert scan.status == ScanStatus.PARTIAL_FAILURE.value
    assert "Broken Greenhouse" in scan.error_summary


def test_unimplemented_source_type_fails_gracefully(db_session):
    _add_source(db_session, "Some Workday Board", "workday")

    summary = run_scan(db_session)

    assert summary.sources_failed == ["Some Workday Board"]
    scan = db_session.get(ScanHistory, summary.scan_history_id)
    assert scan.status == ScanStatus.PARTIAL_FAILURE.value or scan.status == ScanStatus.FAILED.value


def test_no_enabled_sources_is_a_clean_no_op(db_session):
    summary = run_scan(db_session)
    assert summary.jobs_retrieved == 0
    scan = db_session.get(ScanHistory, summary.scan_history_id)
    assert scan.status == ScanStatus.SUCCESS.value


def test_progress_callback_receives_updates(db_session):
    _add_source(db_session, "Demo", "demo")
    messages = []

    run_scan(db_session, progress_callback=messages.append)

    assert any("Scanning Demo" in m for m in messages)
    assert any("Scan complete" in m for m in messages)
