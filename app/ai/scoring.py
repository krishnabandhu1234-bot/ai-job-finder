"""Layers 4-5 (experience, seniority, career trajectory) plus title,
industry, and location scoring - all pure heuristics, no ML/API calls,
so they run over every job that survives hard filtering (section 17's
funnel puts embeddings/LLM only on the smaller shortlists that follow).

Every score is 0-100. "Unknown" inputs score neutrally (around 60-70)
rather than being punished, consistent with "do not automatically
reject" guidance applied to scoring as well as filtering.
"""

from __future__ import annotations

import re

from app.ai.hard_filters import seniority_rank
from app.core.constants import Seniority

_EXPECTED_YEARS_BY_SENIORITY = {
    Seniority.ENTRY.value: (0, 2),
    Seniority.MID.value: (2, 5),
    Seniority.SENIOR.value: (5, 9),
    Seniority.STAFF.value: (8, 14),
    Seniority.PRINCIPAL.value: (10, 20),
    Seniority.LEAD.value: (6, 14),
    Seniority.MANAGER.value: (6, 15),
    Seniority.DIRECTOR.value: (10, 20),
    Seniority.VP.value: (14, 25),
    Seniority.EXECUTIVE.value: (16, 30),
}

_STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "at", "with", "senior",
    "junior", "ii", "iii", "iv", "i",
}


def title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9+#.]*", (title or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def title_match_score(target_roles: list[str], job_title: str) -> float:
    if not target_roles or not job_title:
        return 60.0
    job_tokens = title_tokens(job_title)
    if not job_tokens:
        return 60.0
    best = 0.0
    for role in target_roles:
        role_tokens = title_tokens(role)
        if not role_tokens:
            continue
        overlap = len(role_tokens & job_tokens) / len(role_tokens | job_tokens)
        best = max(best, overlap)
    return round(best * 100.0, 1)


def seniority_match_score(candidate_seniority: str, job_seniority: str) -> float:
    job_rank = seniority_rank(job_seniority)
    cand_rank = seniority_rank(candidate_seniority)
    if job_rank is None or cand_rank is None:
        return 65.0
    distance = abs(job_rank - cand_rank)
    return max(0.0, 100.0 - distance * 25.0)


def experience_match_score(years_experience: float, job_seniority: str) -> float:
    expected = _EXPECTED_YEARS_BY_SENIORITY.get(job_seniority)
    if expected is None or years_experience <= 0:
        return 65.0
    low, high = expected
    if low <= years_experience <= high:
        return 100.0
    if years_experience < low:
        shortfall = low - years_experience
        return max(0.0, 100.0 - shortfall * 15.0)
    excess = years_experience - high
    # Overqualification matters, but less sharply than being underqualified -
    # a very senior candidate can still genuinely want a slightly smaller role.
    return max(30.0, 100.0 - excess * 8.0)


def career_trajectory_score(years_experience: float, candidate_seniority: str, job_seniority: str) -> float:
    """Section 8 Layer 5: "A candidate with 20 years of specialized
    engineering experience should not be ranked highly for an
    entry-level job merely because the keywords match." Penalizes large
    seniority gaps in EITHER direction, with a heavier penalty for
    "wildly overqualified for an entry-level role" than for a modest
    stretch upward."""
    job_rank = seniority_rank(job_seniority)
    cand_rank = seniority_rank(candidate_seniority)
    if job_rank is None or cand_rank is None:
        return 70.0
    distance = cand_rank - job_rank
    if distance <= 0:
        # candidate at or below the job's level: a normal or stretch application
        return max(40.0, 100.0 - abs(distance) * 12.0)
    # candidate significantly above the job's level
    if job_rank <= 1 and years_experience >= 12:
        return max(10.0, 40.0 - distance * 10.0)
    return max(25.0, 100.0 - distance * 18.0)


def industry_match_score(candidate_industries: list[str], job) -> float:
    if not candidate_industries:
        return 60.0
    haystack = f"{job.company} {job.title} {job.description}".lower()
    hits = sum(1 for ind in candidate_industries if ind.strip() and ind.strip().lower() in haystack)
    if hits == 0:
        return 45.0
    return min(100.0, 60.0 + hits * 20.0)


def location_match_score(job, prefs) -> float:
    work_pref = (prefs.work_arrangement or "any").lower()
    if work_pref == "any" or not work_pref:
        base = 85.0
    elif work_pref == "remote":
        base = 100.0 if job.remote else 25.0
    elif work_pref in ("hybrid", "onsite"):
        base = 100.0 if job.work_arrangement == work_pref else (60.0 if job.remote else 55.0)
    else:
        base = 70.0

    countries = [c.strip().lower() for c in (prefs.countries_willing_to_work or []) if c.strip()]
    if countries and "worldwide" not in countries and job.country and not job.remote:
        if job.country.strip().lower() not in countries:
            base = min(base, 20.0)
    return round(base, 1)


def user_preference_bonus_score(job, prefs) -> float:
    """A small explicit-preference nudge (section 9's 5% "user
    preferences" bucket): preferred companies and preferred keywords."""
    score = 60.0
    company_lower = (job.company or "").strip().lower()
    if company_lower and any(company_lower == c.strip().lower() for c in (prefs.preferred_companies or [])):
        score += 25.0
    blob = f"{job.title} {job.description}".lower()
    preferred = [k.strip().lower() for k in (prefs.preferred_keywords or []) if k.strip()]
    if preferred:
        hits = sum(1 for k in preferred if k in blob)
        score += min(15.0, hits * 5.0)
    return min(100.0, score)
