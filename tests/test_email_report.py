"""Tests for assembling the daily report from real JobMatch/Job rows
(section 11) - never from fabricated content (section 32)."""

from __future__ import annotations

from app.database.models import Job, JobMatch, JobSourceConfig
from app.email.report import build_daily_report


def _seed(session, context, notified=False, score=90.0):
    context.config.email_to = "test@example.com"
    user = context.users_repo.get_or_create_default_user(session, "test@example.com")
    profile = context.candidate_profile_repo.get_current(session, user.id)
    source = JobSourceConfig(name="Demo", source_type="demo")
    session.add(source)
    session.flush()
    job = Job(
        external_job_id="1", source_id=source.id, company="NVIDIA", title="Principal Thermal Engineer",
        location_raw="Austin, TX", apply_url="https://example.com/apply", salary_min=180000,
        salary_max=220000, salary_currency="USD", notified=notified, is_active=True,
    )
    session.add(job)
    session.flush()
    match = JobMatch(
        job_id=job.id, candidate_profile_id=profile.id, overall_score=score, category="exceptional",
        passed_hard_filters=True, strengths=["15+ years of relevant experience."], gaps=[],
    )
    session.add(match)
    session.flush()
    return profile, job, match


def test_report_includes_unnotified_high_scoring_job(db_session, app_context):
    profile, job, match = _seed(db_session, app_context, notified=False, score=94.0)
    report = build_daily_report(db_session, app_context, profile.id, min_score=85, max_jobs=15)
    assert len(report.items) == 1
    assert report.items[0].title == "Principal Thermal Engineer"
    assert report.items[0].company == "NVIDIA"
    assert "1" in report.subject


def test_report_excludes_already_notified_job(db_session, app_context):
    profile, job, match = _seed(db_session, app_context, notified=True, score=94.0)
    report = build_daily_report(db_session, app_context, profile.id, min_score=85, max_jobs=15)
    assert report.items == []


def test_report_excludes_below_threshold_job(db_session, app_context):
    profile, job, match = _seed(db_session, app_context, notified=False, score=70.0)
    report = build_daily_report(db_session, app_context, profile.id, min_score=85, max_jobs=15)
    assert report.items == []


def _seed_multi_location_role(db_session, app_context, locations, score=92.0):
    """One role posted once per office - what Greenhouse/Lever actually
    return, and what the deduplicator (correctly) keeps as distinct Job
    rows."""
    app_context.config.email_to = "test@example.com"
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    source = JobSourceConfig(name="Demo", source_type="demo")
    db_session.add(source)
    db_session.flush()
    jobs = []
    for i, location in enumerate(locations):
        job = Job(
            external_job_id=f"role-{i}", source_id=source.id, company="Anthropic",
            title="Research Engineer, Machine Learning", location_raw=location, is_active=True,
        )
        db_session.add(job)
        db_session.flush()
        db_session.add(JobMatch(
            job_id=job.id, candidate_profile_id=profile.id, overall_score=score - i,
            category="exceptional", passed_hard_filters=True,
        ))
        jobs.append(job)
    db_session.flush()
    return profile, jobs


def test_report_collapses_one_role_posted_across_many_offices(db_session, app_context):
    """Five copies of one role would otherwise eat a third of a 15-job
    email while surfacing a single opportunity."""
    profile, jobs = _seed_multi_location_role(
        db_session, app_context,
        ["San Francisco, CA", "New York City, NY", "Seattle, WA", "London, UK", "Tokyo, Japan"],
    )

    report = build_daily_report(db_session, app_context, profile.id, min_score=85, max_jobs=15)

    assert len(report.items) == 1
    item = report.items[0]
    assert item.location == "San Francisco, CA"  # best-scoring posting stays primary
    assert len(item.other_locations) == 4
    assert "+4 other locations" in item.location_display


def test_collapsed_report_marks_every_underlying_posting_notified(db_session, app_context):
    """If only the primary were marked notified, the four folded-in
    copies would come back as "new" tomorrow - the duplicate-notification
    problem section 11 forbids."""
    profile, jobs = _seed_multi_location_role(
        db_session, app_context, ["San Francisco, CA", "New York City, NY", "Seattle, WA"]
    )

    report = build_daily_report(db_session, app_context, profile.id, min_score=85, max_jobs=15)

    assert len(report.items) == 1
    assert len(report.items[0].all_job_ids) == 3
    assert len(report.job_match_ids) == 3  # all three, not just the shown one


def test_report_keeps_genuinely_different_roles_separate(db_session, app_context):
    """Collapsing must key on company AND title - two different roles at
    the same company are two different opportunities."""
    app_context.config.email_to = "test@example.com"
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    source = JobSourceConfig(name="Demo", source_type="demo")
    db_session.add(source)
    db_session.flush()
    for i, title in enumerate(["ML Engineer", "Backend Engineer"]):
        job = Job(
            external_job_id=str(i), source_id=source.id, company="Anthropic",
            title=title, location_raw="San Francisco, CA", is_active=True,
        )
        db_session.add(job)
        db_session.flush()
        db_session.add(JobMatch(
            job_id=job.id, candidate_profile_id=profile.id, overall_score=90.0,
            category="exceptional", passed_hard_filters=True,
        ))
    db_session.flush()

    report = build_daily_report(db_session, app_context, profile.id, min_score=85, max_jobs=15)

    assert len(report.items) == 2


def test_collapsing_still_fills_the_email_to_max_jobs(db_session, app_context):
    """Collapsing shrinks the result set, so the query over-fetches -
    otherwise a company with many multi-office roles would produce a
    near-empty email."""
    app_context.config.email_to = "test@example.com"
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    source = JobSourceConfig(name="Demo", source_type="demo")
    db_session.add(source)
    db_session.flush()
    # 10 distinct roles, each posted in 3 offices = 30 Job rows.
    for role in range(10):
        for office in range(3):
            job = Job(
                external_job_id=f"{role}-{office}", source_id=source.id, company="BigCo",
                title=f"Engineer Level {role}", location_raw=f"Office {office}", is_active=True,
            )
            db_session.add(job)
            db_session.flush()
            db_session.add(JobMatch(
                job_id=job.id, candidate_profile_id=profile.id, overall_score=95.0 - role,
                category="exceptional", passed_hard_filters=True,
            ))
    db_session.flush()

    report = build_daily_report(db_session, app_context, profile.id, min_score=85, max_jobs=5)

    assert len(report.items) == 5  # 5 distinct roles, not 5 copies of one
    assert len({i.title for i in report.items}) == 5


def test_report_respects_max_jobs_limit(db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    source = JobSourceConfig(name="Demo", source_type="demo")
    db_session.add(source)
    db_session.flush()
    for i in range(5):
        job = Job(external_job_id=str(i), source_id=source.id, company=f"Co{i}", title=f"Engineer {i}", is_active=True)
        db_session.add(job)
        db_session.flush()
        db_session.add(
            JobMatch(job_id=job.id, candidate_profile_id=profile.id, overall_score=90.0, passed_hard_filters=True)
        )
    db_session.flush()

    report = build_daily_report(db_session, app_context, profile.id, min_score=85, max_jobs=2)
    assert len(report.items) == 2
