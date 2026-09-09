"""Turns a source-shaped `RawJobPosting` into the app's canonical `Job` DB
schema (section 6): parsed salary, split location, normalized employment
type, and a stable cross-source dedup fingerprint (section 7).

This is heuristic, like resume extraction - salary/location text in the
wild is wildly inconsistent. When something can't be confidently parsed,
we store it as unknown/blank rather than guessing (section 5: "Do not
make false assumptions about salary when the posting doesn't provide
it").
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re

from app.core.constants import EmploymentType, Seniority

_REMOTE_KEYWORDS = ("remote", "work from home", "wfh", "distributed", "anywhere")

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY"}
_KNOWN_CURRENCY_CODES = {"USD", "EUR", "GBP", "INR", "CAD", "AUD", "SGD", "JPY"}

_SALARY_RANGE_RE = re.compile(
    r"(?P<cur1>[$€£₹¥]|USD|EUR|GBP|INR|CAD|AUD|SGD|JPY)\s*"
    r"(?P<min>[\d][\d,]*(?:\.\d+)?)\s*(?P<min_k>[kK])?"
    r"\s*(?:-|–|—|to)\s*"
    r"(?P<cur2>[$€£₹¥]|USD|EUR|GBP|INR|CAD|AUD|SGD|JPY)?\s*"
    r"(?P<max>[\d][\d,]*(?:\.\d+)?)\s*(?P<max_k>[kK])?"
)
_SALARY_SINGLE_RE = re.compile(
    r"(?P<cur>[$€£₹¥]|USD|EUR|GBP|INR|CAD|AUD|SGD|JPY)\s*"
    r"(?P<amount>[\d][\d,]*(?:\.\d+)?)\s*(?P<k>[kK])?"
)

_US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}
_KNOWN_COUNTRY_NAMES = {
    "united states", "usa", "us", "u.s.", "u.s.a.", "united kingdom", "uk", "canada", "india",
    "germany", "france", "australia", "singapore", "japan", "ireland", "netherlands", "spain",
    "italy", "brazil", "mexico", "china", "sweden", "switzerland", "poland", "israel",
    "new zealand", "south africa", "philippines", "portugal", "denmark", "norway", "finland",
}


def _to_number(raw: str, is_k: bool) -> float:
    value = float(raw.replace(",", ""))
    return value * 1000 if is_k else value


def _resolve_currency(symbol_or_code: str | None) -> str:
    if not symbol_or_code:
        return ""
    if symbol_or_code in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[symbol_or_code]
    upper = symbol_or_code.upper()
    return upper if upper in _KNOWN_CURRENCY_CODES else ""


def parse_salary(text: str) -> tuple[float | None, float | None, str]:
    """Returns (salary_min, salary_max, currency). All blank/None when no
    confident parse is possible - callers must treat that as "Unknown",
    never as zero."""
    if not text:
        return None, None, ""

    range_match = _SALARY_RANGE_RE.search(text)
    if range_match:
        currency = _resolve_currency(range_match.group("cur1") or range_match.group("cur2"))
        salary_min = _to_number(range_match.group("min"), bool(range_match.group("min_k")))
        salary_max = _to_number(range_match.group("max"), bool(range_match.group("max_k")))
        if salary_min > salary_max:
            salary_min, salary_max = salary_max, salary_min
        return salary_min, salary_max, currency

    single_match = _SALARY_SINGLE_RE.search(text)
    if single_match:
        currency = _resolve_currency(single_match.group("cur"))
        amount = _to_number(single_match.group("amount"), bool(single_match.group("k")))
        return amount, amount, currency

    return None, None, ""


def parse_location(location_raw: str) -> tuple[str, str, str, bool]:
    """Returns (city, state_province, country, remote). Heuristic and
    intentionally conservative - an ambiguous single token is treated as a
    city, never guessed into a country/state that isn't clearly named."""
    if not location_raw:
        return "", "", "", False

    lowered = location_raw.lower()
    remote = any(keyword in lowered for keyword in _REMOTE_KEYWORDS)

    cleaned = re.sub(r"(?i)\bremote\b", "", location_raw)
    cleaned = cleaned.strip(" ,-|()")
    if not cleaned:
        return "", "", "", remote

    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    city = state = country = ""

    if len(parts) >= 3:
        city, state, country = parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        first, second = parts
        if second.upper() in _US_STATE_ABBR:
            city, state, country = first, second, "United States"
        elif second.lower() in _KNOWN_COUNTRY_NAMES:
            city, country = first, second
        else:
            city, state = first, second
    else:
        single = parts[0]
        if single.lower() in _KNOWN_COUNTRY_NAMES:
            country = single
        elif single.upper() in _US_STATE_ABBR:
            state, country = single, "United States"
        else:
            city = single

    return city, state, country, remote


# Seniority markers as they appear in JOB titles, most senior first so a
# "Senior Engineering Manager" resolves to manager rather than senior.
# Deliberately separate from the resume-side markers in
# `app.resume.profile_builder`: a resume lists what someone HAS been,
# while a posting states what it IS, and the two vocabularies differ
# ("new grad"/"university" only ever appear in postings).
_JOB_TITLE_SENIORITY_MARKERS: list[tuple[str, list[str]]] = [
    (Seniority.EXECUTIVE.value, ["chief", "ceo", "cto", "cfo", "coo", "head of"]),
    (Seniority.VP.value, ["vice president", "vp"]),
    (Seniority.DIRECTOR.value, ["director"]),
    (Seniority.PRINCIPAL.value, ["principal", "distinguished", "fellow"]),
    (Seniority.STAFF.value, ["staff"]),
    (Seniority.MANAGER.value, ["manager", "mgr"]),
    (Seniority.LEAD.value, ["lead", "tech lead", "team lead"]),
    (Seniority.SENIOR.value, ["senior", "sr", "sr.", "iii", "iv"]),
    (Seniority.ENTRY.value, [
        "intern", "internship", "new grad", "new graduate", "university grad",
        "entry level", "entry-level", "junior", "jr", "jr.", "associate", "apprentice",
    ]),
]


def _contains_word(text: str, marker: str) -> bool:
    """Word-boundary-safe check - a plain substring test would read
    "cto" out of "dire-cto-r" and "sr" out of "u-sr-name"."""
    return re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text) is not None


def infer_job_seniority(title: str, description: str = "") -> str:
    """Infers a posting's seniority level from its title.

    Job boards almost never expose seniority as a structured field, but
    titles state it plainly and regularly ("Staff Software Engineer",
    "Senior ML Engineer", "Engineering Manager"). Without this, every
    posting arrives with `seniority=""`, and the three scoring layers
    that depend on it (experience 20%, seniority 10%, career trajectory
    10%) all fall back to their neutral "unknown" defaults - pinning 40%
    of every job's score at a flat ~65 and making it impossible for even
    a perfect match to reach the "excellent" band.

    Returns "" when the title says nothing about level, which is
    honest - the scoring layers handle unknown by staying neutral rather
    than guessing (section 33: never invent a fact about a job)."""
    haystack = (title or "").lower()
    if not haystack:
        return ""
    for level, markers in _JOB_TITLE_SENIORITY_MARKERS:
        if any(_contains_word(haystack, marker) for marker in markers):
            return level
    return ""


def normalize_employment_type(raw: str) -> str:
    lowered = (raw or "").lower()
    if "intern" in lowered:
        return EmploymentType.INTERNSHIP.value
    if "contract" in lowered:
        return EmploymentType.CONTRACT.value
    if "part" in lowered and "time" in lowered:
        return EmploymentType.PART_TIME.value
    if "temp" in lowered:
        return EmploymentType.TEMPORARY.value
    if lowered:
        return EmploymentType.FULL_TIME.value
    return ""  # unknown - never guess full-time when the source said nothing


def to_naive_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Converts a timezone-aware datetime to the app's naive-UTC
    convention (see app.database.models.utc_now); passes naive values
    through unchanged."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


def parse_iso_datetime(value: str | None) -> dt.datetime | None:
    """Parses an ISO-8601 timestamp (as returned by Greenhouse/Ashby,
    typically with a trailing 'Z') into a naive-UTC datetime, or None if
    it's missing/unparseable - never raises."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return to_naive_utc(parsed)


def parse_epoch_millis(value) -> dt.datetime | None:
    """Parses a Unix-epoch-milliseconds timestamp (as returned by Lever)
    into a naive-UTC datetime, or None if missing/unparseable."""
    if not value:
        return None
    try:
        return to_naive_utc(dt.datetime.fromtimestamp(int(value) / 1000, dt.timezone.utc))
    except (ValueError, OSError, OverflowError):
        return None


def compute_fingerprint(company: str, title: str, location_raw: str) -> str:
    """A stable cross-source dedup key (section 7): the same posting on
    LinkedIn, Indeed, and the company's own Greenhouse board should
    collapse to one `Job` row. Deliberately based on normalized text, not
    source-specific IDs, since those never match across sources."""

    def clean(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "")).strip().lower()

    normalized = "|".join([clean(company), clean(title), clean(location_raw)])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_posting(raw, source_id: int) -> dict:
    """`raw` is a `RawJobPosting`. Returns kwargs ready to construct/update
    a `Job` ORM row (everything except id/timestamps/fingerprint, which
    the deduplicator sets)."""
    city, state, country, remote_from_location = parse_location(raw.location_raw)
    remote = raw.remote_hint or remote_from_location

    salary_min, salary_max, salary_currency = raw.salary_min, raw.salary_max, raw.salary_currency
    if salary_min is None and salary_max is None:
        salary_min, salary_max, salary_currency = parse_salary(raw.salary_raw_text or raw.description)

    return {
        "external_job_id": raw.external_job_id,
        "source_id": source_id,
        "company": raw.company,
        "title": raw.title,
        "description": raw.description,
        "requirements": raw.requirements,
        "preferred_qualifications": raw.preferred_qualifications,
        "location_raw": raw.location_raw,
        "city": city,
        "state_province": state,
        "country": country,
        "remote": remote,
        "work_arrangement": "remote" if remote else "",
        "employment_type": normalize_employment_type(raw.employment_type_raw),
        # Inferred from the title, since job boards essentially never
        # publish seniority as a structured field - see
        # `infer_job_seniority` for why leaving this empty silently
        # flattens 40% of the match score.
        "seniority": infer_job_seniority(raw.title, raw.description),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "salary_raw_text": raw.salary_raw_text,
        "posted_date": raw.posted_date,
        "apply_url": raw.apply_url,
        "company_url": raw.company_url,
        "raw_source_data": raw.raw_source_data,
    }
