"""Tests for the Resume and CandidateProfile repositories."""

from __future__ import annotations

from app.database.repository import CandidateProfileRepository, ResumeRepository


def test_resume_create_and_list(db_session, users_repo):
    user = users_repo.get_or_create_default_user(db_session, "test@example.com")
    repo = ResumeRepository()

    repo.create(
        db_session, user_id=user.id, filename="resume.pdf", file_path="/tmp/resume.pdf",
        file_type="pdf", raw_text="Some resume text",
    )
    repo.create(
        db_session, user_id=user.id, filename="bad.pdf", file_path="/tmp/bad.pdf",
        file_type="pdf", parse_error="Could not open PDF",
    )

    resumes = repo.list_for_user(db_session, user.id)
    assert len(resumes) == 2
    assert {r.filename for r in resumes} == {"resume.pdf", "bad.pdf"}


def test_resume_deactivate_hides_from_list(db_session, users_repo):
    user = users_repo.get_or_create_default_user(db_session, "test@example.com")
    repo = ResumeRepository()
    resume = repo.create(
        db_session, user_id=user.id, filename="resume.pdf", file_path="/tmp/resume.pdf",
        file_type="pdf", raw_text="text",
    )

    repo.deactivate(db_session, resume.id)

    assert repo.list_for_user(db_session, user.id) == []
    # The row itself still exists (soft delete), it's just filtered out of listings.
    assert repo.get(db_session, resume.id).is_active is False


def test_candidate_profile_defaults_and_save(db_session, users_repo):
    user = users_repo.get_or_create_default_user(db_session, "test@example.com")
    repo = CandidateProfileRepository()

    profile = repo.get_current(db_session, user.id)
    assert profile.target_roles == []
    assert profile.years_experience == 0.0

    repo.save(
        db_session, profile,
        target_roles=["Thermal Engineer"],
        technical_skills=["ANSYS", "Fluent"],
        years_experience=9.0,
        seniority="senior",
    )

    reloaded = repo.get_current(db_session, user.id)
    assert reloaded.target_roles == ["Thermal Engineer"]
    assert reloaded.technical_skills == ["ANSYS", "Fluent"]
    assert reloaded.seniority == "senior"


def test_candidate_profile_get_current_is_idempotent(db_session, users_repo):
    user = users_repo.get_or_create_default_user(db_session, "test@example.com")
    repo = CandidateProfileRepository()
    first = repo.get_current(db_session, user.id)
    second = repo.get_current(db_session, user.id)
    assert first.id == second.id
