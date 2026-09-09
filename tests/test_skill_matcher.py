"""Tests for Layer 3 skill matching (section 8): exact, related, and
missing skill detection - never plain keyword-count matching."""

from __future__ import annotations

from app.ai.skill_matcher import match_skills
from app.database.models import Job


def _job(**overrides) -> Job:
    base = dict(
        external_job_id="1", source_id=1, company="Acme Corp", title="ML Engineer",
        description="", requirements=[], preferred_qualifications=[],
    )
    base.update(overrides)
    return Job(**base)


def test_exact_match_detected():
    job = _job(requirements=["3+ years of Python experience", "Experience with PostgreSQL"])
    result = match_skills(["Python", "PostgreSQL"], job)
    assert "python" in result.exact_matches
    assert "postgresql" in result.exact_matches
    assert result.missing_skills == []
    assert result.score == 100.0


def test_related_skill_counts_partially_not_fully():
    job = _job(requirements=["Strong TensorFlow background required."])
    result = match_skills(["PyTorch"], job)
    assert "tensorflow" in result.related_matches
    assert 0 < result.score < 100


def test_missing_skill_detected_honestly():
    job = _job(requirements=["Must have Kubernetes and Docker experience."])
    result = match_skills(["Python"], job)
    assert "kubernetes" in result.missing_skills
    assert "docker" in result.missing_skills
    assert result.score == 0.0


def test_no_recognizable_skills_is_neutral_not_penalized():
    job = _job(requirements=["Great communicator, works well with others."])
    result = match_skills(["Python"], job)
    assert result.score == 70.0
    assert result.missing_skills == []


def test_case_insensitive_and_word_boundary_safe():
    # "R" as a language shouldn't match inside "Research" or "PowerPoint"
    job = _job(description="Strong research background and PowerPoint skills required.")
    result = match_skills(["R"], job)
    assert "r" not in result.exact_matches
