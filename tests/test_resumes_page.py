"""Tests for the Resumes page's candidate-profile rebuild logic (section 2):
in particular, that removing every resume actually clears the derived
candidate profile rather than leaving stale data an AI matching run would
keep using indefinitely."""

from __future__ import annotations

from pathlib import Path

from app.database.models import Resume
from app.ui.pages.resumes import ResumesPage

_SAMPLE_RESUME_TEXT = (Path(__file__).parent / "fixtures" / "sample_resume.txt").read_text(encoding="utf-8")


def _make_page(qtbot, app_context):
    # ResumesPage._get_user() resolves the current user via
    # context.config.email_to, not a fixed address - match it so the
    # page operates on the same user row the test sets up.
    app_context.config.email_to = "test@example.com"
    page = ResumesPage(app_context)
    qtbot.addWidget(page)
    return page


def test_rebuild_profile_populates_fields_from_a_resume(qtbot, db_session, app_context):
    page = _make_page(qtbot, app_context)
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    db_session.add(
        Resume(
            user_id=user.id, filename="resume.txt", file_path="/tmp/resume.txt", file_type="txt",
            raw_text=_SAMPLE_RESUME_TEXT,
        )
    )
    db_session.flush()
    db_session.commit()

    page._rebuild_candidate_profile()
    db_session.commit()

    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    assert profile.years_experience > 0
    assert profile.software  # ANSYS/Fluent/OpenFOAM/SolidWorks


def test_removing_all_resumes_clears_the_candidate_profile(qtbot, db_session, app_context):
    """Section 2/33: matching must never keep using a candidate profile
    whose source resume(s) no longer exist - a stale profile would let
    the AI matching engine keep scoring jobs against data the user
    explicitly removed."""
    page = _make_page(qtbot, app_context)
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    resume = Resume(
        user_id=user.id, filename="resume.txt", file_path="/tmp/resume.txt", file_type="txt",
        raw_text=_SAMPLE_RESUME_TEXT,
    )
    db_session.add(resume)
    db_session.flush()
    db_session.commit()

    page._rebuild_candidate_profile()
    db_session.commit()
    profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    assert profile.software  # sanity check the profile was actually populated first

    app_context.resumes_repo.deactivate(db_session, resume.id)
    db_session.commit()
    page._rebuild_candidate_profile()
    # `_rebuild_candidate_profile()` writes through its own separate
    # session_scope(); db_session's engine uses expire_on_commit=False
    # (deliberately, for production performance), so db_session's own
    # identity-mapped CandidateProfile object won't reflect that other
    # session's changes without an explicit refresh.
    db_session.commit()
    db_session.expire_all()

    cleared_profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    assert cleared_profile.software == []
    assert cleared_profile.target_roles == []
    assert cleared_profile.years_experience == 0.0
    assert cleared_profile.seniority == ""
