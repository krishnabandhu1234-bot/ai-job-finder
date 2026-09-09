"""Combines Layers 1-5 into a single heuristic `MatchResult` (section 9's
weighted score) without any embedding or LLM call - cheap enough to run
over every job that survives hard filtering, which is what makes the
funnel in `app.ai.ranker` affordable (section 17).

Embedding similarity (Layer 2) is folded in afterwards by the ranker,
which is the only place with a loaded embedding backend; `technical_match`
here is skill-matcher-only until `apply_embedding_similarity` blends it in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.feedback import learned_title_bonus
from app.ai.hard_filters import HardFilterResult, apply_hard_filters
from app.ai.scoring import (
    career_trajectory_score,
    experience_match_score,
    industry_match_score,
    location_match_score,
    seniority_match_score,
    title_match_score,
    user_preference_bonus_score,
)
from app.ai.skill_matcher import SkillMatchResult, match_skills
from app.core.constants import DEFAULT_SCORE_WEIGHTS, MatchCategory


@dataclass
class MatchResult:
    passed_hard_filters: bool
    hard_filter_reason: str | None
    overall_score: float
    category: str
    technical_match: float
    experience_match: float
    industry_match: float
    seniority_match: float
    location_match: float
    skill_match: float
    career_fit: float
    role_title_match: float
    user_preferences_match: float
    embedding_similarity: float | None = None
    confidence: float | None = None
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    reasoning: str = ""
    skills: SkillMatchResult | None = None


def _candidate_skills(profile) -> list[str]:
    return list(
        {
            *(profile.technical_skills or []),
            *(profile.programming_languages or []),
            *(profile.software or []),
            *(profile.domain_expertise or []),
        }
    )


def _weights(prefs) -> dict[str, float]:
    weights = dict(DEFAULT_SCORE_WEIGHTS)
    if prefs.score_weights:
        weights.update({k: v for k, v in prefs.score_weights.items() if k in weights})
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def _recompute_overall(result: MatchResult, prefs) -> None:
    weights = _weights(prefs)
    overall = (
        result.technical_match * weights["technical_skills"]
        + result.experience_match * weights["relevant_experience"]
        + result.role_title_match * weights["role_title_match"]
        + result.seniority_match * weights["seniority"]
        + result.industry_match * weights["industry_domain"]
        + result.location_match * weights["location_work_arrangement"]
        + result.career_fit * weights["career_trajectory"]
        + result.user_preferences_match * weights["user_preferences"]
    )
    overall = round(min(100.0, max(0.0, overall)), 1)
    if not result.passed_hard_filters:
        # Hard requirements stay hard (section 9): a filtered-out job is
        # never shown as a "match" regardless of how the layers scored.
        overall = min(overall, 40.0)
    result.overall_score = overall
    result.category = MatchCategory.from_score(overall).value


def evaluate_match(profile, job, prefs, title_affinity: dict[str, float] | None = None) -> MatchResult:
    hard = apply_hard_filters(job, prefs)

    skills = match_skills(_candidate_skills(profile), job)
    role_title = title_match_score(profile.target_roles or [], job.title)
    seniority = seniority_match_score(profile.seniority, job.seniority)
    experience = experience_match_score(profile.years_experience or 0.0, job.seniority)
    career = career_trajectory_score(profile.years_experience or 0.0, profile.seniority, job.seniority)
    industry = industry_match_score(profile.industries or [], job)
    location = location_match_score(job, prefs)
    user_pref = user_preference_bonus_score(job, prefs)
    if title_affinity:
        # Section 16: learned preference nudges the user-preferences
        # component only - never strong enough on its own to overturn
        # what the evidence-based layers found.
        user_pref = max(0.0, min(100.0, user_pref + learned_title_bonus(job.title, title_affinity)))

    result = MatchResult(
        passed_hard_filters=hard.passed,
        hard_filter_reason=hard.reason,
        overall_score=0.0,
        category="",
        technical_match=skills.score,
        experience_match=experience,
        industry_match=industry,
        seniority_match=seniority,
        location_match=location,
        skill_match=skills.score,
        career_fit=career,
        role_title_match=role_title,
        user_preferences_match=user_pref,
        skills=skills,
    )
    _recompute_overall(result, prefs)
    _fill_explanation(result, profile, job)
    return result


# How much the stronger of the two technical signals (verified skill
# overlap vs. semantic similarity) dominates the blend. See
# `apply_embedding_similarity` for why this is deliberately not a plain
# average.
_STRONGER_SIGNAL_WEIGHT = 0.75


def apply_embedding_similarity(result: MatchResult, similarity: float, prefs) -> MatchResult:
    """Blends Layer 2 semantic similarity into the technical-match score
    and recomputes the overall figure - called only for jobs that made it
    into the embedding-scored shortlist (section 17's funnel).

    The two inputs measure different things and are NOT averaged. Skill
    matching is a *precision* signal: it found specific, verifiable
    overlap ("this posting requires Kubernetes, AWS and Python; the
    resume evidences all three"). Embedding similarity is a *recall*
    signal: fuzzy, compressed (see `calibrate_similarity`), and good at
    surfacing a strong match phrased in words the skill taxonomy doesn't
    know - but weak evidence that a job is a BAD fit.

    Averaging them let the noisier signal veto the stronger one: a job
    with five verified exact skill matches was dragged down ~17 points by
    a middling cosine score, which is how a genuinely excellent match
    ended up below the daily-email threshold and no email was ever sent.
    Weighting toward whichever signal is stronger keeps the upside (a
    high similarity still lifts a job the keyword matcher missed) without
    that downside."""
    result.embedding_similarity = similarity
    stronger = max(result.technical_match, similarity)
    weaker = min(result.technical_match, similarity)
    result.technical_match = round(
        stronger * _STRONGER_SIGNAL_WEIGHT + weaker * (1 - _STRONGER_SIGNAL_WEIGHT), 1
    )
    result.skill_match = result.technical_match
    _recompute_overall(result, prefs)
    return result


def apply_llm_analysis(result: MatchResult, llm, prefs) -> MatchResult:
    """Lets the LLM (Layer 6) refine the final component scores for the
    smallest shortlist only. The LLM's `strengths`/`gaps`/`concerns`
    replace the heuristic ones (it has read the full job text, not just
    detected skill tokens) but only ever contain what it was told - the
    system prompt in `app.ai.llm_analyzer` explicitly forbids inventing
    qualifications (section 33)."""
    result.technical_match = llm.technical_match
    result.experience_match = llm.experience_match
    result.industry_match = llm.industry_match
    result.seniority_match = llm.seniority_match
    result.location_match = llm.location_match
    result.skill_match = llm.skill_match
    result.career_fit = llm.career_fit
    result.confidence = llm.confidence
    if llm.strengths:
        result.strengths = llm.strengths[:8]
    if llm.gaps:
        result.gaps = llm.gaps[:8]
    if llm.concerns:
        result.concerns = llm.concerns[:8]
    if llm.reasoning:
        result.reasoning = llm.reasoning
    _recompute_overall(result, prefs)
    return result


def _fill_explanation(result: MatchResult, profile, job) -> None:
    """Grounded, evidence-based explanation text (sections 10 & 33) - every
    claim here traces back to a field actually present on the profile or
    a skill actually detected in the job text. Never invents a
    qualification the resume doesn't mention."""
    strengths: list[str] = []
    gaps: list[str] = []
    concerns: list[str] = []

    if result.skills and result.skills.exact_matches:
        shown = ", ".join(sorted(result.skills.exact_matches)[:6])
        strengths.append(f"Direct experience with {shown}, which this role requires.")
    if result.skills and result.skills.related_matches:
        shown = ", ".join(sorted(result.skills.related_matches)[:4])
        strengths.append(f"Related/transferable experience for {shown}.")
    if profile.years_experience and result.experience_match >= 80:
        strengths.append(f"{profile.years_experience:.0f}+ years of experience aligns with this role's level.")
    if result.role_title_match >= 60:
        strengths.append("Target role closely matches this job's title.")
    if result.industry_match >= 80:
        strengths.append("Industry background matches what this employer is hiring for.")
    if job.remote and (profile.locations or []):
        strengths.append("This role is remote.")

    if result.skills and result.skills.missing_skills:
        shown = ", ".join(sorted(result.skills.missing_skills)[:5])
        gaps.append(f"Resume does not explicitly mention: {shown}.")

    if not result.passed_hard_filters and result.hard_filter_reason:
        concerns.append(result.hard_filter_reason)
    if result.career_fit < 50:
        concerns.append("This role's seniority level may not fit your career trajectory well.")
    if result.location_match < 40:
        concerns.append("Location/work-arrangement may not match your preferences.")

    result.strengths = strengths[:6]
    result.gaps = gaps[:6]
    result.concerns = concerns[:4]
    result.reasoning = (
        f"Overall {result.overall_score:.0f}/100 ({result.category}). "
        + (strengths[0] if strengths else "Limited concrete overlap found with the candidate profile.")
    )
