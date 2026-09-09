"""Layer 1 - hard filters (section 8).

These run before anything expensive (embeddings, LLM calls) and are
deliberately conservative: a filter only rejects a job when the
mismatch is explicit and unambiguous. When information is missing
(unknown seniority, unknown country, ...) the filter lets the job
through rather than guessing it away - "Do not automatically reject
jobs where salary is unavailable" (section 3) generalizes to every
other optional field.

Pure functions, no database/network access - trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.constants import Seniority

_SENIORITY_ORDER = [
    Seniority.ENTRY.value,
    Seniority.MID.value,
    Seniority.SENIOR.value,
    Seniority.STAFF.value,
    Seniority.PRINCIPAL.value,
    Seniority.LEAD.value,
    Seniority.MANAGER.value,
    Seniority.DIRECTOR.value,
    Seniority.VP.value,
    Seniority.EXECUTIVE.value,
]


def seniority_rank(level: str) -> int | None:
    if not level or level == Seniority.ANY.value:
        return None
    try:
        return _SENIORITY_ORDER.index(level)
    except ValueError:
        return None


@dataclass
class HardFilterResult:
    passed: bool
    reason: str | None = None


def _text_blob(job) -> str:
    parts = [job.title or "", job.description or ""]
    parts.extend(job.requirements or [])
    parts.extend(job.preferred_qualifications or [])
    return " ".join(parts).lower()


def apply_hard_filters(job, prefs) -> HardFilterResult:
    """`job` is a `Job` ORM row, `prefs` a `UserPreferences` ORM row."""

    company_lower = (job.company or "").strip().lower()
    if company_lower and any(company_lower == c.strip().lower() for c in (prefs.excluded_companies or [])):
        return HardFilterResult(False, f"{job.company} is on your excluded companies list.")

    if prefs.employment_types and job.employment_type:
        if job.employment_type not in prefs.employment_types:
            return HardFilterResult(
                False, f"Employment type {job.employment_type!r} isn't one you're looking for."
            )

    seniority_levels = [s for s in (prefs.seniority_levels or []) if s != Seniority.ANY.value]
    if seniority_levels and job.seniority and job.seniority != Seniority.ANY.value:
        job_rank = seniority_rank(job.seniority)
        wanted_ranks = [r for r in (seniority_rank(s) for s in seniority_levels) if r is not None]
        if job_rank is not None and wanted_ranks:
            # Reject only a clear, large mismatch (more than one level off
            # from every level the user asked for) - close calls are left
            # for the scoring layers, not a hard reject.
            if min(abs(job_rank - r) for r in wanted_ranks) > 1:
                return HardFilterResult(False, f"Seniority {job.seniority!r} doesn't match your target levels.")

    countries = [c.strip() for c in (prefs.countries_willing_to_work or []) if c.strip()]
    countries_lower = {c.lower() for c in countries}
    if countries_lower and "worldwide" not in countries_lower and not job.remote:
        if job.country and job.country.strip().lower() not in countries_lower:
            return HardFilterResult(False, f"{job.country} isn't in your list of acceptable countries.")

    if prefs.visa_preference == "remote_only" and not job.remote:
        return HardFilterResult(False, "You're only considering remote roles, and this one isn't remote.")

    blob = _text_blob(job)
    for keyword in prefs.required_keywords or []:
        if keyword.strip() and keyword.strip().lower() not in blob:
            return HardFilterResult(False, f"Missing required keyword: {keyword!r}.")

    for keyword in prefs.excluded_keywords or []:
        if keyword.strip() and keyword.strip().lower() in blob:
            return HardFilterResult(False, f"Contains excluded keyword: {keyword!r}.")

    return HardFilterResult(True, None)
