"""Tests for the Setup Guide page (`app/ui/pages/setup_guide.py`).

Its whole job is telling the user which link in the setup chain is
missing, so what's tested is that its step detection reflects real
database state rather than that widgets render.
"""

from __future__ import annotations

import pytest

from app.database.models import Job, JobMatch, JobSourceConfig
from app.ui.pages.setup_guide import SetupGuidePage

pytest.importorskip("PySide6")


@pytest.fixture
def page(qtbot, db_session, app_context):
    # Three things this fixture has to line up:
    #  * `db_session` initializes the global engine that the page's own
    #    `session_scope()` calls rely on;
    #  * the page resolves its user from `config.email_to`, so tests must
    #    seed data under that same address or the page looks at a
    #    different (empty) user;
    #  * the page opens its OWN session (as it does in the real app), so
    #    tests must COMMIT, not just flush, to be visible to it.
    app_context.config.email_to = "test@example.com"
    widget = SetupGuidePage(app_context)
    qtbot.addWidget(widget)
    return widget


def _steps_by_number(page) -> dict[int, object]:
    return {s.number: s for s in page._collect_steps()}


def test_fresh_install_shows_nothing_done(page):
    steps = _steps_by_number(page)
    assert steps[1].done is False  # resume
    assert steps[3].done is False  # target titles
    assert steps[4].done is False  # job sources
    assert steps[5].done is False  # matches


def test_fresh_install_explains_the_very_first_action(page):
    """A brand-new user must be told where to start, not shown zeros."""
    page.refresh()
    assert "0 of" in page.summary_label.text()
    assert "step 1" in page.intro_label.text().lower()


def test_uploading_a_resume_completes_step_one(page, db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.resumes_repo.create(
        db_session, user_id=user.id, filename="cv.txt", file_path="/tmp/cv.txt",
        file_type="txt", raw_text="Jane Doe\nSenior Engineer\nPython",
    )
    db_session.commit()

    assert _steps_by_number(page)[1].done is True


def test_a_resume_that_failed_to_parse_does_not_count(page, db_session, app_context):
    """An unreadable upload leaves nothing to build a profile from, so
    the step must stay red rather than looking complete."""
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.resumes_repo.create(
        db_session, user_id=user.id, filename="scan.pdf", file_path="/tmp/scan.pdf",
        file_type="pdf", raw_text="", parse_error="No extractable text (scanned image?)",
    )
    db_session.commit()

    assert _steps_by_number(page)[1].done is False


def test_adding_a_job_source_completes_step_four(page, db_session, app_context):
    app_context.job_sources_repo.create(
        db_session, name="Acme", source_type="greenhouse", config={"board_token": "acme"}
    )
    db_session.commit()

    assert _steps_by_number(page)[4].done is True


def test_a_disabled_job_source_does_not_count(page, db_session, app_context):
    """A disabled source is never scanned, so it can't be what makes the
    step complete."""
    source = app_context.job_sources_repo.create(
        db_session, name="Acme", source_type="greenhouse", config={"board_token": "acme"}
    )
    db_session.commit()
    app_context.job_sources_repo.set_enabled(db_session, source.id, False)
    db_session.commit()

    assert _steps_by_number(page)[4].done is False


def test_target_titles_complete_step_three(page, db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    prefs = app_context.preferences_repo.get_active(db_session, user.id)
    app_context.preferences_repo.save(db_session, prefs, target_titles=["ML Engineer"])
    db_session.commit()

    step = _steps_by_number(page)[3]
    assert step.done is True
    assert "ML Engineer" in step.detail  # shows what it will actually search for


def test_having_matches_completes_step_five(page, db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    source = JobSourceConfig(name="Demo", source_type="demo")
    db_session.add(source)
    db_session.commit()
    job = Job(external_job_id="1", source_id=source.id, company="Acme", title="Eng", is_active=True)
    db_session.add(job)
    db_session.commit()
    db_session.add(JobMatch(
        job_id=job.id, candidate_profile_id=profile.id, overall_score=80.0, passed_hard_filters=True
    ))
    db_session.commit()

    assert _steps_by_number(page)[5].done is True


def test_email_step_is_optional(page):
    """The app is fully usable without email, so an unconfigured email
    step must not make setup look incomplete."""
    steps = _steps_by_number(page)
    assert steps[6].required is False

    page.refresh()
    # 5 required steps, none done - the optional one isn't counted.
    assert "0 of 5" in page.summary_label.text()


def test_completing_everything_reports_all_set(page, db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.resumes_repo.create(
        db_session, user_id=user.id, filename="cv.txt", file_path="/tmp/cv.txt",
        file_type="txt", raw_text="Jane Doe Python",
    )
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    app_context.candidate_profile_repo.save(
        db_session, profile, target_roles=["Engineer"], technical_skills=["Python"]
    )
    prefs = app_context.preferences_repo.get_active(db_session, user.id)
    app_context.preferences_repo.save(db_session, prefs, target_titles=["Engineer"])
    source = JobSourceConfig(name="Demo", source_type="demo")
    db_session.add(source)
    db_session.commit()
    job = Job(external_job_id="1", source_id=source.id, company="Acme", title="Eng", is_active=True)
    db_session.add(job)
    db_session.commit()
    db_session.add(JobMatch(
        job_id=job.id, candidate_profile_id=profile.id, overall_score=80.0, passed_hard_filters=True
    ))
    db_session.commit()

    page.refresh()
    assert "all set up" in page.summary_label.text().lower()


def test_refresh_is_repeatable_without_duplicating_cards(page):
    """The page is refreshed on every navigation - stale cards must be
    cleared rather than stacking up."""
    page.refresh()
    first = page.steps_container.count()
    page.refresh()
    page.refresh()
    assert page.steps_container.count() == first

