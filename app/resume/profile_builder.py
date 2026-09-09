"""Merges one or more extracted resumes into a single CandidateProfile
(section 2: "If multiple resumes are uploaded, intelligently combine them
while preserving source information").

Pure functions only - no database access here, so this stays trivially
testable. The caller (Resumes UI page) is responsible for persisting the
returned dict via the CandidateProfileRepository.
"""

from __future__ import annotations

import re

from app.core.constants import Seniority
from app.resume.extractor import ExtractedResume


def build_candidate_profile_fields(extracted_resumes: list[tuple[int, ExtractedResume]]) -> dict:
    """`extracted_resumes` is a list of (resume_id, ExtractedResume) pairs -
    the resume_id lets the resulting profile record which resume(s) each
    piece of data ultimately came from (`source_resume_ids`), satisfying
    the "preserving source information" requirement even though individual
    fields are merged/deduplicated here."""

    target_roles: list[str] = []
    technical_skills: list[str] = []
    programming_languages: list[str] = []
    software: list[str] = []
    certifications: list[str] = []
    companies: list[str] = []
    leadership: list[str] = []
    achievements: list[str] = []
    education: list[str] = []
    projects: list[str] = []
    publications: list[str] = []
    source_resume_ids: list[int] = []
    years_experience = 0.0

    for resume_id, extracted in extracted_resumes:
        source_resume_ids.append(resume_id)
        target_roles.extend(extracted.target_roles)
        technical_skills.extend(extracted.technical_skills)
        programming_languages.extend(extracted.programming_languages)
        software.extend(extracted.software)
        certifications.extend(extracted.certifications)
        companies.extend(extracted.companies)
        leadership.extend(extracted.leadership)
        achievements.extend(extracted.achievements)
        projects.extend(extracted.projects)
        publications.extend(extracted.publications)
        education.extend(
            f"{e.degree} - {e.institution}".strip(" -") if e.institution else e.degree
            for e in extracted.education
        )
        # Different resumes may cover different date ranges (e.g. an older
        # resume vs. an updated one) - take the max rather than summing,
        # since summing would double-count overlapping career history.
        years_experience = max(years_experience, extracted.years_experience)

    return {
        "source_resume_ids": source_resume_ids,
        "target_roles": _dedup(target_roles)[:8],
        "seniority": infer_seniority(years_experience, target_roles).value,
        "years_experience": years_experience,
        "technical_skills": _dedup(technical_skills),
        "programming_languages": _dedup(programming_languages),
        "software": _dedup(software),
        "domain_expertise": [],  # not reliably inferable from text alone - left for the user to fill in
        "leadership": _dedup(leadership),
        "education": _dedup(education),
        "certifications": _dedup(certifications),
        "companies": _dedup(companies),
        "locations": [],  # location extraction is deferred - see Phase 2 known limitations in README
        "achievements": _dedup(achievements)[:20],
        "publications": _dedup(publications),
        "projects": _dedup(projects),
    }


_SENIOR_TITLE_MARKERS = {
    Seniority.EXECUTIVE: ["chief", "ceo", "cto", "cfo", "coo"],
    Seniority.VP: ["vice president", "vp"],
    Seniority.DIRECTOR: ["director"],
    Seniority.PRINCIPAL: ["principal"],
    Seniority.STAFF: ["staff"],
    Seniority.MANAGER: ["manager"],
    Seniority.LEAD: ["lead", "tech lead", "team lead"],
}


def _contains_marker(text: str, marker: str) -> bool:
    """Word-boundary-safe substring check. A naive `marker in text` check
    is wrong here: "cto" (meant to catch the abbreviation CTO) is also a
    substring of "director" (di-re-CTO-r), which would misclassify a
    Director as an Executive. Non-alphanumeric characters (spaces,
    punctuation, string edges) count as boundaries."""
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])")
    return pattern.search(text) is not None


def infer_seniority(years_experience: float, titles: list[str]) -> Seniority:
    """A first-pass heuristic, not a hard fact - shown as editable on the
    Resumes page, never silently trusted downstream without the user being
    able to correct it."""
    lowered_titles = " | ".join(titles).lower()
    for level, markers in _SENIOR_TITLE_MARKERS.items():
        if any(_contains_marker(lowered_titles, marker) for marker in markers):
            return level

    if years_experience >= 15:
        return Seniority.PRINCIPAL
    if years_experience >= 8:
        return Seniority.SENIOR
    if years_experience >= 4:
        return Seniority.MID
    if years_experience > 0:
        return Seniority.ENTRY
    return Seniority.ANY


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result
