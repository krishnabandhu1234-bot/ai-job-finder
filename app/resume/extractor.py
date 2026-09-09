"""Structured field extraction from raw resume text (section 2).

This is a rule-based/heuristic extractor: section-header detection, date
range parsing, and a curated skills taxonomy (skills_taxonomy.py) - no
external API calls, no heavy NLP dependencies, works fully offline in
Demo Mode. It intentionally does not try to be perfect; it's designed to
get a strong first-pass structured profile that the user can review and
edit (section 2: "Allow the user to see and edit the extracted candidate
profile"). Feeding this text through an LLM for higher-fidelity extraction
is a natural enhancement once Phase 5's LLM layer exists, gated the same
way as everywhere else in this app (opt-in, never required, local-only
mode disables it).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from app.resume.skills_taxonomy import (
    CERTIFICATIONS,
    CLOUD_PLATFORMS,
    DATABASES,
    DEGREE_KEYWORDS,
    FRAMEWORKS_LIBRARIES,
    LEADERSHIP_PHRASES,
    LEADERSHIP_TITLE_MARKERS,
    PROGRAMMING_LANGUAGES,
    SECTION_HEADERS,
    SOFTWARE_TOOLS,
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?", re.IGNORECASE)

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAMES = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_DATE_TOKEN = rf"(?:{_MONTH_NAMES})\.?\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}}"
_DATE_RANGE_RE = re.compile(
    rf"({_DATE_TOKEN})\s*(?:-|–|—|to)\s*(Present|Current|Now|{_DATE_TOKEN})",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^[\s•\-\*•▪‣⁃]+")
_HAS_METRIC_RE = re.compile(r"\d")


@dataclass
class ContactInfo:
    name: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""


@dataclass
class ExperienceEntry:
    title: str = ""
    company: str = ""
    date_range_text: str = ""
    start_months: int | None = None  # months since year 0, for duration math
    end_months: int | None = None
    bullets: list[str] = field(default_factory=list)


@dataclass
class EducationEntry:
    degree: str = ""
    institution: str = ""
    year: str = ""


@dataclass
class ExtractedResume:
    contact: ContactInfo = field(default_factory=ContactInfo)
    experience: list[ExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)
    years_experience: float = 0.0
    technical_skills: list[str] = field(default_factory=list)
    programming_languages: list[str] = field(default_factory=list)
    software: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    leadership: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    publications: list[str] = field(default_factory=list)
    sections_found: list[str] = field(default_factory=list)


def extract_resume(text: str, reference_date: dt.date | None = None) -> ExtractedResume:
    reference_date = reference_date or dt.date.today()
    sections = _split_sections(text)

    contact = _extract_contact(text)
    experience = _extract_experience(sections.get("experience", ""), reference_date)
    education = _extract_education(sections.get("education", ""))

    technical_skills = _find_terms(text, SOFTWARE_TOOLS + FRAMEWORKS_LIBRARIES + DATABASES + CLOUD_PLATFORMS)
    programming_languages = _find_terms(text, PROGRAMMING_LANGUAGES)
    certifications = _find_terms(text, CERTIFICATIONS)

    return ExtractedResume(
        contact=contact,
        experience=experience,
        education=education,
        target_roles=_infer_target_roles(experience),
        years_experience=_compute_years_experience(experience),
        technical_skills=technical_skills,
        programming_languages=programming_languages,
        software=_find_terms(text, SOFTWARE_TOOLS),
        certifications=certifications,
        companies=_dedup_preserve_order([e.company for e in experience if e.company]),
        leadership=_extract_leadership(experience, text),
        achievements=_extract_achievements(experience),
        projects=_split_into_bullets(sections.get("projects", "")),
        publications=_split_into_bullets(sections.get("publications", "")),
        sections_found=sorted(sections.keys()),
    )


def _split_sections(text: str) -> dict[str, str]:
    lines = text.split("\n")
    headers: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        cleaned = line.strip().strip(":").strip()
        if not cleaned or len(cleaned) > 40:
            continue
        lowered = cleaned.lower()
        for canonical, terms in SECTION_HEADERS.items():
            if lowered in terms:
                headers.append((i, canonical))
                break

    sections: dict[str, str] = {}
    for idx, (line_idx, canonical) in enumerate(headers):
        start = line_idx + 1
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        chunk = "\n".join(lines[start:end]).strip()
        sections[canonical] = f"{sections[canonical]}\n{chunk}" if canonical in sections else chunk
    return sections


def _extract_contact(text: str) -> ContactInfo:
    email_match = _EMAIL_RE.search(text)
    phone_match = _PHONE_RE.search(text)
    linkedin_match = _LINKEDIN_RE.search(text)

    name = ""
    for line in text.split("\n")[:5]:
        candidate = line.strip()
        if not candidate or len(candidate) > 60:
            continue
        if _EMAIL_RE.search(candidate) or _PHONE_RE.search(candidate):
            continue
        if any(ch.isdigit() for ch in candidate):
            continue
        # A plausible name: 2-4 words, each starting with a capital letter.
        words = candidate.split()
        if 1 < len(words) <= 4 and all(w[0].isupper() for w in words if w):
            name = candidate
            break

    return ContactInfo(
        name=name,
        email=email_match.group(0) if email_match else "",
        phone=phone_match.group(0) if phone_match else "",
        linkedin=linkedin_match.group(0) if linkedin_match else "",
    )


def _parse_date_token(token: str, reference_date: dt.date) -> int | None:
    token = token.strip()
    if token.lower() in ("present", "current", "now"):
        return reference_date.year * 12 + reference_date.month

    m = re.match(r"^(\d{1,2})/(\d{4})$", token)
    if m:
        return int(m.group(2)) * 12 + int(m.group(1))

    m = re.match(rf"^({_MONTH_NAMES})\.?\s+(\d{{4}})$", token, re.IGNORECASE)
    if m:
        month_num = _MONTH_ABBR.get(m.group(1)[:3].lower())
        if month_num:
            return int(m.group(2)) * 12 + month_num

    m = re.match(r"^(\d{4})$", token)
    if m:
        return int(m.group(1)) * 12 + 1  # assume January when only a year is given

    return None


def _extract_experience(section_text: str, reference_date: dt.date) -> list[ExperienceEntry]:
    if not section_text:
        return []

    lines = [line for line in section_text.split("\n")]
    entries: list[ExperienceEntry] = []
    current_entry: ExperienceEntry | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        date_match = _DATE_RANGE_RE.search(stripped)
        if date_match:
            header_remainder = (stripped[: date_match.start()] + stripped[date_match.end() :]).strip(" -–—|,.")
            if len(header_remainder) < 3:
                # The date range sat on its own line; the title/company is
                # on the previous non-empty line instead.
                header_remainder = ""
                for prev in reversed(lines[:i]):
                    if prev.strip():
                        header_remainder = prev.strip()
                        break

            title, company = _split_title_company(header_remainder)
            entry = ExperienceEntry(
                title=title,
                company=company,
                date_range_text=date_match.group(0),
                start_months=_parse_date_token(date_match.group(1), reference_date),
                end_months=_parse_date_token(date_match.group(2), reference_date),
            )
            entries.append(entry)
            current_entry = entry
            continue

        if current_entry is not None and _BULLET_RE.match(line):
            bullet_text = _BULLET_RE.sub("", stripped).strip()
            if bullet_text:
                current_entry.bullets.append(bullet_text)

    return entries


def _split_title_company(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    for sep in (" — ", " – ", " | ", " at ", ", "):
        if sep in text:
            parts = text.split(sep, 1)
            return parts[0].strip(" -–—"), parts[1].strip(" -–—")
    return text.strip(" -–—"), ""


def _extract_education(section_text: str) -> list[EducationEntry]:
    if not section_text:
        return []

    entries: list[EducationEntry] = []
    lines = [line.strip() for line in section_text.split("\n") if line.strip()]
    for i, line in enumerate(lines):
        matched_degree = next((d for d in DEGREE_KEYWORDS if _term_in_text(d, line)), None)
        if not matched_degree:
            continue
        year_match = re.search(r"\b(19|20)\d{2}\b", line)
        year = year_match.group(0) if year_match else ""

        institution = ""
        # The institution is often on the same line after a delimiter, or
        # on the adjacent line.
        for sep in (" — ", " – ", " | ", ", "):
            if sep in line:
                parts = [p.strip() for p in line.split(sep) if matched_degree.lower() not in p.lower()]
                if parts:
                    institution = parts[0]
                break
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        next_line_is_bare_year = bool(re.fullmatch(r"(19|20)\d{2}", next_line))
        if not institution and next_line and not next_line_is_bare_year:
            institution = next_line

        if not year:
            # A short "just the year" line commonly sits right after (or,
            # less often, before) the degree/institution line.
            for neighbor in (next_line, lines[i - 1] if i > 0 else ""):
                neighbor_year = re.search(r"\b(19|20)\d{2}\b", neighbor)
                if neighbor_year and len(neighbor) <= 6:
                    year = neighbor_year.group(0)
                    break

        entries.append(EducationEntry(degree=matched_degree, institution=institution, year=year))
    return entries


def _find_terms(text: str, terms: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for term in terms:
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
        if pattern.search(text):
            key = term.lower()
            if key not in seen:
                seen.add(key)
                found.append(term)
    return found


def _term_in_text(term: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _compute_years_experience(entries: list[ExperienceEntry]) -> float:
    intervals = [
        (e.start_months, e.end_months)
        for e in entries
        if e.start_months is not None and e.end_months is not None and e.end_months >= e.start_months
    ]
    if not intervals:
        return 0.0

    intervals.sort()
    merged: list[list[int]] = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    total_months = sum(end - start for start, end in merged)
    return round(total_months / 12, 1)


def _infer_target_roles(entries: list[ExperienceEntry]) -> list[str]:
    # Most recent roles first (entries are extracted in document order,
    # which is conventionally reverse-chronological on a resume).
    titles = [e.title for e in entries if e.title]
    return _dedup_preserve_order(titles)[:5]


def _extract_leadership(entries: list[ExperienceEntry], full_text: str) -> list[str]:
    found: list[str] = []
    lowered_text = full_text.lower()
    for phrase in LEADERSHIP_PHRASES:
        if phrase in lowered_text:
            found.append(phrase)

    for entry in entries:
        title_lower = entry.title.lower()
        if any(marker in title_lower for marker in LEADERSHIP_TITLE_MARKERS):
            found.append(entry.title)

    return _dedup_preserve_order(found)


def _extract_achievements(entries: list[ExperienceEntry], max_items: int = 15) -> list[str]:
    achievements: list[str] = []
    for entry in entries:
        for bullet in entry.bullets:
            if _HAS_METRIC_RE.search(bullet):
                achievements.append(bullet)
    return _dedup_preserve_order(achievements)[:max_items]


def _split_into_bullets(section_text: str) -> list[str]:
    if not section_text:
        return []
    items = []
    for line in section_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        items.append(_BULLET_RE.sub("", stripped).strip())
    return [item for item in items if item]


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result
