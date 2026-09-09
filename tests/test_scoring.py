"""Tests for Layers 4-5 heuristics (experience, seniority, career
trajectory) plus title/industry/location scoring."""

from __future__ import annotations

from app.ai.scoring import (
    career_trajectory_score,
    experience_match_score,
    industry_match_score,
    location_match_score,
    seniority_match_score,
    title_match_score,
    user_preference_bonus_score,
)
from app.database.models import Job, UserPreferences


def _job(**overrides) -> Job:
    base = dict(
        external_job_id="1", source_id=1, company="Acme Corp", title="Senior Simulation Engineer",
        description="", remote=False, work_arrangement="onsite", country="United States",
    )
    base.update(overrides)
    return Job(**base)


def _prefs(**overrides) -> UserPreferences:
    base = dict(
        work_arrangement="any", countries_willing_to_work=[], preferred_companies=[], preferred_keywords=[],
    )
    base.update(overrides)
    return UserPreferences(**base)


def test_title_match_scores_high_for_close_title():
    score = title_match_score(["Principal Simulation Engineer"], "Senior Simulation Engineer")
    assert score > 40


def test_title_match_neutral_when_unspecified():
    assert title_match_score([], "Senior Simulation Engineer") == 60.0


def test_seniority_match_perfect_for_same_level():
    assert seniority_match_score("senior", "senior") == 100.0


def test_seniority_match_degrades_with_distance():
    close = seniority_match_score("senior", "staff")
    far = seniority_match_score("entry", "director")
    assert close > far


def test_experience_match_in_expected_range_is_full():
    assert experience_match_score(7, "senior") == 100.0


def test_experience_match_penalizes_underqualification():
    assert experience_match_score(1, "senior") < 100.0


def test_experience_match_softly_penalizes_overqualification():
    score = experience_match_score(25, "senior")
    assert 30 <= score < 100


def test_career_trajectory_penalizes_veteran_applying_to_entry_role():
    """Section 8 Layer 5's explicit example: 20 years of experience
    should not score well for an entry-level role."""
    score = career_trajectory_score(20, "principal", "entry")
    assert score < 40


def test_career_trajectory_neutral_for_matched_levels():
    score = career_trajectory_score(8, "senior", "senior")
    assert score >= 90


def test_industry_match_detects_overlap():
    job = _job(company="Tesla", description="Automotive battery systems.")
    assert industry_match_score(["Automotive"], job) > 60


def test_industry_match_neutral_when_no_industries_specified():
    assert industry_match_score([], _job()) == 60.0


def test_location_match_remote_preference_rejects_onsite():
    job = _job(remote=False)
    score = location_match_score(job, _prefs(work_arrangement="remote"))
    assert score < 50


def test_location_match_remote_preference_accepts_remote_job():
    job = _job(remote=True, work_arrangement="remote")
    score = location_match_score(job, _prefs(work_arrangement="remote"))
    assert score == 100.0


def test_user_preference_bonus_for_preferred_company():
    job = _job(company="NVIDIA")
    score = user_preference_bonus_score(job, _prefs(preferred_companies=["NVIDIA"]))
    assert score > 60.0
