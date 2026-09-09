"""Layer 3 - skill matching (section 8).

Deliberately more than a keyword-equality check: a skill mentioned in
the job can be an EXACT match, a RELATED match (a skill the candidate
has that is closely associated with the required one, e.g. PyTorch for
a TensorFlow requirement), or MISSING entirely. The related-skill map
below is intentionally small and curated rather than exhaustive - it
exists to avoid unfairly zeroing out a strong candidate over a
near-synonym, not to claim skills the resume never mentioned (section
33: never fabricate evidence).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.resume.skills_taxonomy import (
    CLOUD_PLATFORMS,
    DATABASES,
    FRAMEWORKS_LIBRARIES,
    PROGRAMMING_LANGUAGES,
    SOFTWARE_TOOLS,
)

# Skills mentioned often enough in job postings, without appearing in the
# resume-extraction taxonomy verbatim, that they're worth recognizing here
# too (e.g. broad domain terms rather than specific tools).
_EXTRA_JOB_SKILL_TERMS = [
    "CFD", "FEA", "thermal analysis", "multiphysics", "machine learning",
    "deep learning", "natural language processing", "computer vision",
    "data engineering", "data science", "MLOps", "CI/CD", "microservices",
    "distributed systems", "embedded systems", "robotics", "signal processing",
    "structural analysis", "heat transfer", "fluid dynamics", "systems engineering",
]

ALL_KNOWN_SKILLS = sorted(
    set(
        PROGRAMMING_LANGUAGES
        + SOFTWARE_TOOLS
        + FRAMEWORKS_LIBRARIES
        + DATABASES
        + CLOUD_PLATFORMS
        + _EXTRA_JOB_SKILL_TERMS
    ),
    key=len,
    reverse=True,
)

# Curated related/transferable-skill groups. Any two terms in the same
# group count as a RELATED (not exact) match.
_RELATED_GROUPS: list[set[str]] = [
    {"pytorch", "tensorflow", "keras"},
    {"react", "vue.js", "angular", "svelte"},
    {"aws", "amazon web services", "azure", "microsoft azure", "gcp", "google cloud platform"},
    {"mysql", "postgresql", "mariadb", "sql server", "oracle database"},
    {"docker", "kubernetes"},
    {"ansys", "abaqus", "comsol", "fluent", "openfoam"},
    {"jenkins", "terraform", "ansible", "chef", "puppet"},
    {"pandas", "numpy", "scipy"},
    {"c++", "c"},
    {"scala", "java"},
]
_RELATED_LOOKUP: dict[str, set[str]] = {}
for group in _RELATED_GROUPS:
    for term in group:
        _RELATED_LOOKUP.setdefault(term, set()).update(group - {term})


def _find_skills_in_text(text: str) -> set[str]:
    lowered = f" {text.lower()} "
    found = set()
    for skill in ALL_KNOWN_SKILLS:
        pattern = r"(?<![a-z0-9])" + re.escape(skill.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, lowered):
            found.add(skill.lower())
    return found


@dataclass
class SkillMatchResult:
    score: float  # 0-100
    exact_matches: list[str] = field(default_factory=list)
    related_matches: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)


def match_skills(candidate_skills: list[str], job) -> SkillMatchResult:
    """`candidate_skills` should already combine technical_skills,
    programming_languages, software, and domain_expertise from the
    candidate profile."""
    candidate_lower = {s.lower() for s in candidate_skills if s.strip()}

    job_text = " ".join(
        [job.title or "", job.description or ""] + (job.requirements or []) + (job.preferred_qualifications or [])
    )
    required_text = " ".join([job.title or ""] + (job.requirements or []))

    job_skills = _find_skills_in_text(job_text)
    required_skills = _find_skills_in_text(required_text) or job_skills

    if not required_skills:
        # The posting doesn't name any recognizable specific skill (common
        # for very short/generic postings) - skill match is neutral, not
        # penalized, since there's nothing concrete to check against.
        return SkillMatchResult(score=70.0)

    exact, related, missing = [], [], []
    for skill in sorted(required_skills):
        if skill in candidate_lower:
            exact.append(skill)
            continue
        related_terms = _RELATED_LOOKUP.get(skill, set())
        if related_terms & candidate_lower:
            related.append(skill)
        else:
            missing.append(skill)

    total = len(required_skills)
    score = (len(exact) * 1.0 + len(related) * 0.6) / total * 100.0
    return SkillMatchResult(
        score=round(score, 1),
        exact_matches=exact,
        related_matches=related,
        missing_skills=missing,
    )
