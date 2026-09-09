"""Tests for the combined heuristic matcher (section 9's weighted score)."""

from __future__ import annotations

from app.ai.llm_analyzer import LLMAnalysis
from app.ai.matcher import apply_embedding_similarity, apply_llm_analysis, evaluate_match
from app.core.constants import MatchCategory
from app.database.models import CandidateProfile, Job, UserPreferences


def _profile(**overrides) -> CandidateProfile:
    base = dict(
        target_roles=["Simulation Engineer"], seniority="senior", years_experience=8.0,
        industries=["Aerospace"], technical_skills=["CFD", "thermal analysis"],
        programming_languages=["Python"], software=["ANSYS"], domain_expertise=[],
        leadership=[], education=[], certifications=[], companies=[], locations=[],
        achievements=[], publications=[], projects=[],
    )
    base.update(overrides)
    return CandidateProfile(**base)


def _job(**overrides) -> Job:
    base = dict(
        external_job_id="1", source_id=1, company="Acme Aerospace", title="Senior Simulation Engineer",
        description="Own CFD and thermal analysis simulations using ANSYS Fluent.",
        requirements=["Experience with CFD", "Python scripting", "ANSYS"],
        preferred_qualifications=[], location_raw="Austin, TX", city="Austin",
        state_province="TX", country="United States", remote=False, work_arrangement="onsite",
        employment_type="full_time", seniority="senior",
    )
    base.update(overrides)
    return Job(**base)


def _prefs(**overrides) -> UserPreferences:
    base = dict(
        excluded_companies=[], employment_types=[], seniority_levels=[], countries_willing_to_work=[],
        visa_preference="not_specified", required_keywords=[], excluded_keywords=[],
        work_arrangement="any", preferred_companies=[], preferred_keywords=[], score_weights={},
    )
    base.update(overrides)
    return UserPreferences(**base)


def test_strong_overlap_scores_well_above_threshold():
    result = evaluate_match(_profile(), _job(), _prefs())
    assert result.overall_score >= 75
    assert result.passed_hard_filters is True
    assert result.category in (
        MatchCategory.STRONG.value, MatchCategory.EXCELLENT.value, MatchCategory.EXCEPTIONAL.value,
        MatchCategory.GOOD.value,
    )


def test_hard_filter_failure_caps_score_even_with_good_skills():
    result = evaluate_match(_profile(), _job(company="Acme Aerospace"), _prefs(excluded_companies=["Acme Aerospace"]))
    assert result.passed_hard_filters is False
    assert result.overall_score <= 40


def test_explanation_only_cites_real_evidence():
    result = evaluate_match(_profile(), _job(), _prefs())
    joined = " ".join(result.strengths).lower()
    # Should mention a real detected skill, never an invented one like "Kubernetes"
    assert "kubernetes" not in joined


def test_missing_skills_are_reported_as_gaps():
    job = _job(requirements=["Experience with Kubernetes required."])
    result = evaluate_match(_profile(), job, _prefs())
    assert any("kubernetes" in g.lower() for g in result.gaps)


def test_veteran_candidate_scores_lower_for_entry_role():
    veteran = _profile(years_experience=22.0, seniority="principal")
    entry_job = _job(seniority="entry", title="Junior Simulation Engineer")
    result = evaluate_match(veteran, entry_job, _prefs())
    assert result.career_fit < 50


def test_apply_embedding_similarity_blends_and_recomputes_overall():
    result = evaluate_match(_profile(), _job(), _prefs())
    before = result.overall_score
    apply_embedding_similarity(result, 20.0, _prefs())
    assert result.embedding_similarity == 20.0
    assert result.overall_score != before


def test_weak_similarity_cannot_veto_verified_skill_matches():
    """Semantic similarity is a fuzzy recall signal, not evidence that a
    job with verified exact skill overlap is a bad fit. Averaging the two
    let a middling cosine score drag a strong match below the daily-email
    threshold, so no email was ever sent."""
    result = evaluate_match(_profile(), _job(), _prefs())
    strong_skill_score = result.technical_match
    assert strong_skill_score > 60  # precondition: the skill matcher is confident

    apply_embedding_similarity(result, 40.0, _prefs())

    # The weaker signal still pulls down somewhat, but nowhere near the
    # midpoint an average would produce.
    midpoint = (strong_skill_score + 40.0) / 2
    assert result.technical_match > midpoint


def test_strong_similarity_lifts_a_job_the_skill_matcher_missed():
    """The upside of the embedding pass: a genuinely relevant posting
    phrased in vocabulary the skill taxonomy doesn't know should still
    rise, which is the whole reason Layer 2 exists."""
    job = _job(description="Work on airflow modelling", requirements=[])
    result = evaluate_match(_profile(), job, _prefs())
    weak_skill_score = result.technical_match

    apply_embedding_similarity(result, 85.0, _prefs())

    assert result.technical_match > weak_skill_score


def test_embedding_blend_is_symmetric_in_which_signal_is_stronger():
    """Whichever of the two signals is higher dominates - the rule is
    about signal strength, not about which one it came from. Uses a job
    with only partial skill overlap so the skill score has headroom in
    both directions."""
    partial_job = _job(requirements=["CFD", "Rust", "Kubernetes"])

    baseline = evaluate_match(_profile(), partial_job, _prefs())
    skills_score = baseline.technical_match
    assert 0 < skills_score < 100  # precondition: headroom to move either way

    low = evaluate_match(_profile(), partial_job, _prefs())
    apply_embedding_similarity(low, 10.0, _prefs())

    high = evaluate_match(_profile(), partial_job, _prefs())
    apply_embedding_similarity(high, 100.0, _prefs())

    assert low.technical_match < skills_score < high.technical_match


def test_apply_llm_analysis_overrides_component_scores():
    result = evaluate_match(_profile(), _job(), _prefs())
    llm = LLMAnalysis(
        overall_score=90, technical_match=95, experience_match=90, industry_match=88,
        seniority_match=92, location_match=100, skill_match=95, career_fit=93, confidence=0.9,
        strengths=["Deep CFD expertise directly matches the role."], gaps=[], concerns=[],
        reasoning="Excellent fit.",
    )
    apply_llm_analysis(result, llm, _prefs())
    assert result.technical_match == 95
    assert result.reasoning == "Excellent fit."
    assert result.confidence == 0.9
