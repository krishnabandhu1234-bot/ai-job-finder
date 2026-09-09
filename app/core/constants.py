"""Shared enums and constant lookup tables used across the app.

Centralized here so the database models, matching engine, and UI never
disagree about the set of valid values for a field.
"""

from __future__ import annotations

from enum import Enum


class Seniority(str, Enum):
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"
    LEAD = "lead"
    MANAGER = "manager"
    DIRECTOR = "director"
    VP = "vp"
    EXECUTIVE = "executive"
    ANY = "any"


class WorkArrangement(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    ANY = "any"


class EmploymentType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"


class VisaPreference(str, Enum):
    US_AUTHORIZED_NO_SPONSORSHIP = "us_authorized_no_sponsorship"
    SPONSORSHIP_REQUIRED = "sponsorship_required"
    NO_SPONSORSHIP_NEEDED_ANY_COUNTRY = "no_sponsorship_needed_any_country"
    WILLING_TO_RELOCATE = "willing_to_relocate"
    REMOTE_ONLY = "remote_only"
    NOT_SPECIFIED = "not_specified"


class MatchCategory(str, Enum):
    EXCEPTIONAL = "exceptional"  # 95-100
    EXCELLENT = "excellent"  # 90-94
    STRONG = "strong"  # 85-89
    GOOD = "good"  # 75-84
    POSSIBLE = "possible"  # 60-74
    POOR = "poor"  # <60

    @staticmethod
    def from_score(score: float) -> "MatchCategory":
        if score >= 95:
            return MatchCategory.EXCEPTIONAL
        if score >= 90:
            return MatchCategory.EXCELLENT
        if score >= 85:
            return MatchCategory.STRONG
        if score >= 75:
            return MatchCategory.GOOD
        if score >= 60:
            return MatchCategory.POSSIBLE
        return MatchCategory.POOR


class FeedbackRating(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    NOT_INTERESTED = "not_interested"
    POOR = "poor"
    NEVER_SHOW_SIMILAR = "never_show_similar"


class ApplicationStatus(str, Enum):
    INTERESTED = "interested"
    APPLIED = "applied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    ARCHIVED = "archived"


class ScanTrigger(str, Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    STARTUP = "startup"


class ScanStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class SourceType(str, Enum):
    # Implemented connectors, each backed by an ATS's own public
    # job-board JSON API (the endpoint that powers the embeddable board
    # companies put on their careers page) - never scraping.
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKABLE = "workable"
    SMARTRECRUITERS = "smartrecruiters"
    # Not one company's board: a query-driven search across every company
    # on the platforms that publish a public search endpoint. This is how
    # the app finds employers it was never told about - see
    # app/jobs/job_search.py.
    RESUME_SEARCH = "resume_search"
    DEMO = "demo"
    # Placeholders for connectors that don't exist yet - see
    # app/jobs/source.py. Kept so existing rows/config referencing them
    # stay valid; `build_source` returns None for these and the UI says
    # so rather than failing a scan.
    WORKDAY = "workday"
    COMPANY_CAREER_PAGE = "company_career_page"
    PUBLIC_JOB_API = "public_job_api"
    OTHER = "other"


class EmbeddingProvider(str, Enum):
    LOCAL = "local"
    OPENAI = "openai"
    VOYAGE = "voyage"  # Anthropic has no embeddings API; Voyage AI is their recommended partner


class LLMProvider(str, Enum):
    NONE = "none"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    LOCAL = "local"  # a model on this machine (Ollama/LM Studio/...)


class ScheduleFrequency(str, Enum):
    EVERY_12_HOURS = "every_12_hours"
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL_ONLY = "manual_only"


WORLD_REGIONS = [
    "Worldwide",
    "United States",
    "Canada",
    "Europe",
    "United Kingdom",
    "India",
    "Asia-Pacific",
    "Latin America",
    "Middle East",
    "Africa",
    "Remote Worldwide",
]

DEFAULT_SCORE_WEIGHTS = {
    "technical_skills": 0.25,
    "relevant_experience": 0.20,
    "role_title_match": 0.15,
    "seniority": 0.10,
    "industry_domain": 0.10,
    "location_work_arrangement": 0.05,
    "career_trajectory": 0.10,
    "user_preferences": 0.05,
}

# Default "only email me jobs at least this good" threshold.
#
# Empirically grounded, not aspirational. Measured against ~750 real
# postings, a genuinely strong match for a well-formed profile (right
# seniority, several verified skill overlaps) lands around 78-80 on this
# scale, and the 95-100 band is effectively unreachable because several
# components stay deliberately neutral whenever a posting simply doesn't
# state something (seniority, employment type, salary - most don't).
#
# This was 85, which meant the daily email silently never sent: the
# app's main output, never firing, with nothing in the UI to explain
# why. 75 is the floor of this module's own "good" band and matches what
# a real strong match actually scores. Users who want to be stricter can
# raise it on the Job Search Profile page. Migration 2 corrects existing
# installs still holding the old value (see app/database/migrations.py).
DEFAULT_MIN_EMAIL_SCORE = 75
DEFAULT_MAX_EMAIL_JOBS = 15
