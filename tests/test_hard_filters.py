"""Tests for Layer 1 hard filters (section 8)."""

from __future__ import annotations

from app.ai.hard_filters import apply_hard_filters
from app.database.models import Job, UserPreferences


def _job(**overrides) -> Job:
    base = dict(
        external_job_id="1", source_id=1, company="Acme Corp", title="Senior Engineer",
        description="Build things.", requirements=[], preferred_qualifications=[],
        location_raw="Austin, TX", city="Austin", state_province="TX", country="United States",
        remote=False, work_arrangement="onsite", employment_type="full_time", seniority="senior",
    )
    base.update(overrides)
    return Job(**base)


def _prefs(**overrides) -> UserPreferences:
    base = dict(
        excluded_companies=[], employment_types=[], seniority_levels=[],
        countries_willing_to_work=[], visa_preference="not_specified",
        required_keywords=[], excluded_keywords=[],
    )
    base.update(overrides)
    return UserPreferences(**base)


def test_passes_with_no_preferences_set():
    result = apply_hard_filters(_job(), _prefs())
    assert result.passed is True
    assert result.reason is None


def test_rejects_excluded_company_case_insensitive():
    result = apply_hard_filters(_job(company="Acme Corp"), _prefs(excluded_companies=["acme corp"]))
    assert result.passed is False
    assert "excluded" in result.reason.lower()


def test_rejects_wrong_employment_type():
    result = apply_hard_filters(
        _job(employment_type="internship"), _prefs(employment_types=["full_time", "contract"])
    )
    assert result.passed is False


def test_allows_close_seniority_mismatch():
    # senior vs staff is only one level apart - not a hard reject
    result = apply_hard_filters(_job(seniority="staff"), _prefs(seniority_levels=["senior"]))
    assert result.passed is True


def test_rejects_far_seniority_mismatch():
    result = apply_hard_filters(_job(seniority="entry"), _prefs(seniority_levels=["director"]))
    assert result.passed is False


def test_unknown_seniority_never_filtered():
    result = apply_hard_filters(_job(seniority=""), _prefs(seniority_levels=["director"]))
    assert result.passed is True


def test_rejects_country_not_in_list_when_not_remote():
    result = apply_hard_filters(
        _job(country="Germany", remote=False), _prefs(countries_willing_to_work=["United States"])
    )
    assert result.passed is False


def test_allows_remote_job_regardless_of_country():
    result = apply_hard_filters(
        _job(country="Germany", remote=True), _prefs(countries_willing_to_work=["United States"])
    )
    assert result.passed is True


def test_worldwide_disables_country_filter():
    result = apply_hard_filters(
        _job(country="Germany", remote=False), _prefs(countries_willing_to_work=["Worldwide"])
    )
    assert result.passed is True


def test_remote_only_preference_rejects_onsite_job():
    result = apply_hard_filters(_job(remote=False), _prefs(visa_preference="remote_only"))
    assert result.passed is False


def test_required_keyword_missing_rejects():
    result = apply_hard_filters(_job(description="general work"), _prefs(required_keywords=["Kubernetes"]))
    assert result.passed is False


def test_required_keyword_present_passes():
    result = apply_hard_filters(
        _job(description="Must know Kubernetes well."), _prefs(required_keywords=["Kubernetes"])
    )
    assert result.passed is True


def test_excluded_keyword_present_rejects():
    result = apply_hard_filters(_job(description="Heavy on-call rotation."), _prefs(excluded_keywords=["on-call"]))
    assert result.passed is False


def test_salary_unavailable_never_filters():
    """Section 3: never automatically reject on missing salary - hard
    filters don't even look at salary, but this documents the intent."""
    job = _job(salary_min=None, salary_max=None)
    result = apply_hard_filters(job, _prefs())
    assert result.passed is True
