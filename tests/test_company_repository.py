"""Tests for company aggregation and job-source CRUD repositories."""

from __future__ import annotations

from app.database.repository import CompanyRepository, JobSourceRepository
from app.jobs.deduplicator import upsert_job


def _make_source(session, name="Demo"):
    from app.database.models import JobSourceConfig

    source = JobSourceConfig(name=name, source_type="demo")
    session.add(source)
    session.flush()
    return source


def _job_fields(source_id, **overrides):
    base = dict(
        external_job_id="1", source_id=source_id, company="Acme Corp", title="Engineer",
        description="", requirements=[], preferred_qualifications=[], location_raw="Austin, TX",
        city="Austin", state_province="TX", country="United States", remote=False,
        work_arrangement="", employment_type="full_time", salary_min=None, salary_max=None,
        salary_currency="", salary_raw_text="", posted_date=None,
        apply_url="", company_url="", raw_source_data={},
    )
    base.update(overrides)
    return base


def test_company_stats_empty_database(db_session):
    repo = CompanyRepository()
    assert repo.get_company_stats(db_session) == []


def test_company_stats_aggregates_job_counts_and_salary(db_session):
    source = _make_source(db_session)
    upsert_job(db_session, source, _job_fields(source.id, external_job_id="1", company="Acme Corp",
                                                title="Engineer I", salary_min=100000, salary_max=120000,
                                                salary_currency="USD", remote=True))
    upsert_job(db_session, source, _job_fields(source.id, external_job_id="2", company="Acme Corp",
                                                title="Engineer II", location_raw="Seattle, WA",
                                                remote=False))
    upsert_job(db_session, source, _job_fields(source.id, external_job_id="3", company="Beta Inc",
                                                location_raw="Denver, CO"))

    repo = CompanyRepository()
    stats = {s.company: s for s in repo.get_company_stats(db_session)}

    assert stats["Acme Corp"].job_count == 2
    assert stats["Acme Corp"].remote_count == 1
    assert stats["Acme Corp"].avg_salary_midpoint == 110000
    assert stats["Acme Corp"].salary_known_count == 1
    assert stats["Beta Inc"].job_count == 1
    assert stats["Beta Inc"].avg_salary_midpoint is None


def test_company_stats_excludes_inactive_jobs(db_session):
    source = _make_source(db_session)
    job, _ = upsert_job(db_session, source, _job_fields(source.id))
    job.is_active = False
    db_session.flush()

    repo = CompanyRepository()
    assert repo.get_company_stats(db_session) == []


def test_job_source_repository_crud(db_session):
    repo = JobSourceRepository()
    source = repo.create(db_session, name="Acme (Greenhouse)", source_type="greenhouse",
                          config={"board_token": "acme"})

    assert repo.get(db_session, source.id).name == "Acme (Greenhouse)"
    assert len(repo.list_all(db_session)) == 1

    repo.set_enabled(db_session, source.id, False)
    assert repo.get(db_session, source.id).enabled is False

    repo.delete(db_session, source.id)
    assert repo.get(db_session, source.id) is None
    assert repo.list_all(db_session) == []
