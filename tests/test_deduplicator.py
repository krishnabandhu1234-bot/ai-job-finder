"""Tests for new-job detection, cross-source dedup, and reappearance
handling (section 7)."""

from __future__ import annotations

import datetime as dt

from app.database.models import Job, JobSourceConfig, utc_now
from app.jobs.deduplicator import DedupOutcome, mark_disappeared_jobs, upsert_job


def _source(session, name="Acme (Greenhouse)", source_type="greenhouse") -> JobSourceConfig:
    source = JobSourceConfig(name=name, source_type=source_type)
    session.add(source)
    session.flush()
    return source


def _fields(source_id: int, **overrides) -> dict:
    """`source_id` has no default deliberately - a previous version of
    this helper defaulted it to 1 which happened to work by coincidence
    (SQLite's first autoincremented id in a fresh test DB) but was wrong
    the moment a test used two sources. Every call site must pass the
    real source's id, exactly like production code (normalize_posting)
    always does."""
    base = dict(
        external_job_id="111",
        source_id=source_id,
        company="Acme Corp",
        title="Senior Engineer",
        description="Great job with lots of responsibilities.",
        requirements=[],
        preferred_qualifications=[],
        location_raw="Austin, TX",
        city="Austin", state_province="TX", country="United States",
        remote=False, work_arrangement="",
        employment_type="full_time",
        salary_min=None, salary_max=None, salary_currency="",
        salary_raw_text="",
        posted_date=None,
        apply_url="https://example.com/apply",
        company_url="https://example.com",
        raw_source_data={},
    )
    base.update(overrides)
    return base


def test_new_job_is_created(db_session):
    source = _source(db_session)
    job, outcome = upsert_job(db_session, source, _fields(source.id))

    assert outcome == DedupOutcome.NEW
    assert job.is_active is True
    assert job.fingerprint  # computed and stored


def test_same_source_same_id_is_an_update_not_a_new_job(db_session):
    source = _source(db_session)
    job1, outcome1 = upsert_job(db_session, source, _fields(source.id))
    job2, outcome2 = upsert_job(db_session, source, _fields(source.id, title="Senior Engineer II"))

    assert outcome1 == DedupOutcome.NEW
    assert outcome2 == DedupOutcome.UPDATED
    assert job1.id == job2.id
    assert job2.title == "Senior Engineer II"


def test_cross_source_fingerprint_match_merges_into_one_job(db_session):
    greenhouse_source = _source(db_session, name="Acme (Greenhouse)", source_type="greenhouse")
    lever_source = _source(db_session, name="Acme (Lever)", source_type="lever")

    job1, outcome1 = upsert_job(db_session, greenhouse_source, _fields(greenhouse_source.id, external_job_id="gh-1"))
    job2, outcome2 = upsert_job(
        db_session, lever_source,
        _fields(lever_source.id, external_job_id="lever-1"),  # same company/title/location
    )

    assert outcome1 == DedupOutcome.NEW
    assert outcome2 == DedupOutcome.UPDATED  # matched via fingerprint, not a new row
    assert job1.id == job2.id

    total_jobs = db_session.query(Job).count()
    assert total_jobs == 1


def test_cross_source_fingerprint_match_preserves_original_source_and_external_id(db_session):
    """A cross-source match must not overwrite the merged-into row's own
    (source_id, external_job_id) identity with the OTHER source's values -
    doing so would silently detach the row from both sources' own lookups
    (the unique constraint is on that pair), so a later scan of either
    source would create a fresh duplicate instead of matching this row."""
    greenhouse_source = _source(db_session, name="Acme (Greenhouse)", source_type="greenhouse")
    lever_source = _source(db_session, name="Acme (Lever)", source_type="lever")

    job1, _ = upsert_job(db_session, greenhouse_source, _fields(greenhouse_source.id, external_job_id="gh-1"))
    job2, _ = upsert_job(
        db_session, lever_source, _fields(lever_source.id, external_job_id="lever-1"),
    )

    assert job1.id == job2.id
    assert job2.source_id == greenhouse_source.id  # NOT overwritten to lever_source.id
    assert job2.external_job_id == "gh-1"  # NOT overwritten to "lever-1"

    # A later Greenhouse scan must still match this same row by its
    # original (source_id, external_job_id) pair, not create a duplicate.
    job3, outcome3 = upsert_job(
        db_session, greenhouse_source,
        _fields(greenhouse_source.id, external_job_id="gh-1", title="Senior Engineer II"),
    )
    assert job3.id == job1.id
    assert outcome3 == DedupOutcome.UPDATED
    assert db_session.query(Job).count() == 1


def test_different_location_is_a_different_job(db_session):
    source = _source(db_session)
    upsert_job(db_session, source, _fields(source.id, external_job_id="1", location_raw="Austin, TX"))
    job2, outcome2 = upsert_job(
        db_session, source, _fields(source.id, external_job_id="2", location_raw="Seattle, WA")
    )
    assert outcome2 == DedupOutcome.NEW


def test_disappeared_job_is_marked_inactive(db_session):
    source = _source(db_session)
    upsert_job(db_session, source, _fields(source.id, external_job_id="1"))
    upsert_job(db_session, source, _fields(source.id, external_job_id="2", title="Other Role"))

    disappeared_count = mark_disappeared_jobs(db_session, source, seen_external_ids={"1"})

    assert disappeared_count == 1
    job2 = db_session.query(Job).filter_by(external_job_id="2").one()
    assert job2.is_active is False
    job1 = db_session.query(Job).filter_by(external_job_id="1").one()
    assert job1.is_active is True


def test_reappeared_job_with_unchanged_description_is_reactivated_not_renotified(db_session):
    source = _source(db_session)
    job, _ = upsert_job(db_session, source, _fields(source.id, external_job_id="1"))
    job.notified = True
    job.notification_date = utc_now()
    db_session.flush()

    mark_disappeared_jobs(db_session, source, seen_external_ids=set())
    assert job.is_active is False

    job2, outcome = upsert_job(db_session, source, _fields(source.id, external_job_id="1"))  # same description

    assert outcome == DedupOutcome.REACTIVATED
    assert job2.id == job.id
    assert job2.is_active is True
    assert job2.notified is True  # must NOT be re-notified for an unchanged reappearance


def test_reappeared_job_with_different_description_is_reset_as_new(db_session):
    source = _source(db_session)
    job, _ = upsert_job(
        db_session, source, _fields(source.id, external_job_id="1", description="Original description text.")
    )
    job.notified = True
    job.notification_date = utc_now()
    db_session.flush()

    mark_disappeared_jobs(db_session, source, seen_external_ids=set())

    job2, outcome = upsert_job(
        db_session, source,
        _fields(
            source.id, external_job_id="1",
            description="A completely different role with entirely new responsibilities and scope.",
        ),
    )

    assert outcome == DedupOutcome.RESET_AS_NEW
    assert job2.notified is False
    assert job2.notification_date is None


def test_reappeared_job_after_long_absence_is_reset_as_new_even_if_unchanged(db_session, monkeypatch):
    source = _source(db_session)
    job, _ = upsert_job(db_session, source, _fields(source.id, external_job_id="1"))
    job.notified = True
    job.is_active = False
    job.last_seen_at = utc_now() - dt.timedelta(days=100)  # long gone
    db_session.flush()

    job2, outcome = upsert_job(db_session, source, _fields(source.id, external_job_id="1"))  # identical description

    assert outcome == DedupOutcome.RESET_AS_NEW
    assert job2.notified is False
