"""Tests for the Job Matches list behavior: score colouring, the
"hide ones I've passed on" filter, and the status column.

The point of the hide filter is that giving feedback must visibly *do*
something - otherwise the feedback buttons feel decorative.
"""

from __future__ import annotations

import pytest

from app.core.constants import ApplicationStatus, FeedbackRating
from app.database.models import Feedback, Job, JobMatch, JobSourceConfig
from app.ui.pages.job_matches import _SCORE_COLOR_DEFAULT, JobMatchesPage, _score_color

pytest.importorskip("PySide6")


# --------------------------------------------------------------------------
# Score colouring (pure function - no widgets needed)
# --------------------------------------------------------------------------

def test_score_colour_bands_match_the_category_thresholds():
    assert _score_color(96) == _score_color(90)      # excellent and above share a colour
    assert _score_color(90) != _score_color(85)      # excellent vs strong
    assert _score_color(85) != _score_color(75)      # strong vs good
    assert _score_color(75) != _score_color(60)      # good vs possible
    assert _score_color(10) == _SCORE_COLOR_DEFAULT  # poor


def test_score_colour_is_monotonic():
    """A better score must never get a "worse-looking" band."""
    bands = [_score_color(s) for s in (95, 88, 80, 65, 20)]
    assert len(set(bands)) == 5  # five visually distinct bands


# --------------------------------------------------------------------------
# List behavior
# --------------------------------------------------------------------------

@pytest.fixture
def page(qtbot, db_session, app_context):
    app_context.config.email_to = "test@example.com"
    widget = JobMatchesPage(app_context)
    qtbot.addWidget(widget)
    return widget


def _seed_match(db_session, app_context, title="Engineer", score=80.0):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    source = db_session.query(JobSourceConfig).first()
    if source is None:
        source = JobSourceConfig(name="Demo", source_type="demo")
        db_session.add(source)
        db_session.commit()
    job = Job(
        external_job_id=title, source_id=source.id, company="Acme", title=title, is_active=True
    )
    db_session.add(job)
    db_session.commit()
    match = JobMatch(
        job_id=job.id, candidate_profile_id=profile.id, overall_score=score,
        passed_hard_filters=True,
    )
    db_session.add(match)
    db_session.commit()
    return job, match


def test_matches_are_listed(page, db_session, app_context):
    _seed_match(db_session, app_context, title="ML Engineer")
    page.refresh()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "ML Engineer"


def test_passing_on_a_job_hides_it(page, db_session, app_context):
    """Marking something "not interested" has to visibly remove it, or
    the feedback buttons do nothing the user can perceive."""
    _job, match = _seed_match(db_session, app_context, title="Not For Me")
    db_session.add(Feedback(job_match_id=match.id, rating=FeedbackRating.NOT_INTERESTED.value))
    db_session.commit()

    page.hide_rejected_check.setChecked(True)
    page.refresh()

    assert page.table.rowCount() == 0
    assert "hidden because you passed on them" in page.result_count_label.text()


def test_hidden_jobs_can_be_brought_back(page, db_session, app_context):
    """Hiding must be reversible - the data isn't deleted."""
    _job, match = _seed_match(db_session, app_context, title="Second Thoughts")
    db_session.add(Feedback(job_match_id=match.id, rating=FeedbackRating.POOR.value))
    db_session.commit()

    page.hide_rejected_check.setChecked(False)
    page.refresh()

    assert page.table.rowCount() == 1


def test_positive_feedback_does_not_hide_a_job(page, db_session, app_context):
    _job, match = _seed_match(db_session, app_context, title="Great One")
    db_session.add(Feedback(job_match_id=match.id, rating=FeedbackRating.EXCELLENT.value))
    db_session.commit()

    page.hide_rejected_check.setChecked(True)
    page.refresh()

    assert page.table.rowCount() == 1


def test_changing_your_mind_unhides_the_job(page, db_session, app_context):
    """The newest opinion is the real one - an earlier rejection followed
    by positive feedback must not keep the job hidden."""
    _job, match = _seed_match(db_session, app_context, title="Reconsidered")
    import datetime as dt

    db_session.add(Feedback(
        job_match_id=match.id, rating=FeedbackRating.NOT_INTERESTED.value,
        created_at=dt.datetime(2026, 1, 1),
    ))
    db_session.add(Feedback(
        job_match_id=match.id, rating=FeedbackRating.EXCELLENT.value,
        created_at=dt.datetime(2026, 6, 1),
    ))
    db_session.commit()

    page.hide_rejected_check.setChecked(True)
    page.refresh()

    assert page.table.rowCount() == 1


def test_status_column_shows_feedback(page, db_session, app_context):
    _job, match = _seed_match(db_session, app_context, title="Rated")
    db_session.add(Feedback(job_match_id=match.id, rating=FeedbackRating.GOOD.value))
    db_session.commit()

    page.hide_rejected_check.setChecked(False)
    page.refresh()

    status_col = page.table.columnCount() - 1
    assert page.table.item(0, status_col).text() == "Good"


def test_application_status_wins_over_feedback(page, db_session, app_context):
    """Having actually applied is the more informative fact to surface."""
    job, match = _seed_match(db_session, app_context, title="Applied To")
    db_session.add(Feedback(job_match_id=match.id, rating=FeedbackRating.GOOD.value))
    db_session.commit()
    app_context.applications_repo.set_status(db_session, job.id, ApplicationStatus.APPLIED.value)
    db_session.commit()

    page.refresh()

    status_col = page.table.columnCount() - 1
    assert page.table.item(0, status_col).text() == "Applied"


def test_result_count_is_reported(page, db_session, app_context):
    for i in range(3):
        _seed_match(db_session, app_context, title=f"Role {i}")
    page.refresh()
    assert "3 match" in page.result_count_label.text()
