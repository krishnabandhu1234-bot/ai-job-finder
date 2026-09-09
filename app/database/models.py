"""SQLAlchemy ORM schema.

The full schema (section 21 of the spec) is created up front, even though
early phases only populate a handful of these tables. This means later
phases only ever add *additive* migrations (new nullable columns / new
tables), never a breaking rewrite of tables the UI already depends on.

Enum-like fields (seniority, match category, employment type, ...) are
stored as plain `String` rather than a DB-level ENUM/CHECK type. This is a
deliberate reliability choice: SQLite has no native enum type, and a
DB-level CHECK constraint would make adding a new enum value a migration
instead of a code change. Validation happens at the Python boundary using
the enums in `app.core.constants`.

All list/dict-shaped fields (skills, strengths, config blobs, ...) use
SQLAlchemy's `JSON` type, which SQLite stores as TEXT and (de)serializes
transparently.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.constants import DEFAULT_MIN_EMAIL_SCORE


class Base(DeclarativeBase):
    pass


def utc_now() -> dt.datetime:
    """The single convention for "now" used both as a column default and
    anywhere application code needs to compare against a datetime loaded
    from the database.

    Deliberately NAIVE (no tzinfo), always meaning UTC. SQLite has no real
    timezone-aware column type - SQLAlchemy silently strips tzinfo when a
    tz-aware datetime round-trips through it, so a value created with
    `datetime.now(timezone.utc)` and a value read back from a `Job` row
    end up with different `tzinfo` (aware vs naive) even though both
    represent the same UTC convention. Subtracting or comparing an aware
    "now" against a naive DB value raises `TypeError: can't subtract
    offset-naive and offset-aware datetimes`. Using this naive-everywhere
    helper for every "now" in the app (not just column defaults) avoids
    that trap entirely - see tests/test_models_datetime.py.
    """
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


_utcnow = utc_now  # internal alias used throughout this module's `default=`


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    resumes: Mapped[list["Resume"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    candidate_profiles: Mapped[list["CandidateProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    preferences: Mapped[list["UserPreferences"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# resumes
# ---------------------------------------------------------------------------
class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(500))
    file_path: Mapped[str] = mapped_column(String(1000))
    file_type: Mapped[str] = mapped_column(String(20))  # pdf | docx | txt
    raw_text: Mapped[str] = mapped_column(Text, default="")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)

    user: Mapped[User] = relationship(back_populates="resumes")


# ---------------------------------------------------------------------------
# candidate_profiles
# ---------------------------------------------------------------------------
class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source_resume_ids: Mapped[list] = mapped_column(JSON, default=list)

    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    seniority: Mapped[str] = mapped_column(String(30), default="")
    years_experience: Mapped[float] = mapped_column(Float, default=0.0)
    industries: Mapped[list] = mapped_column(JSON, default=list)
    technical_skills: Mapped[list] = mapped_column(JSON, default=list)
    software: Mapped[list] = mapped_column(JSON, default=list)
    programming_languages: Mapped[list] = mapped_column(JSON, default=list)
    domain_expertise: Mapped[list] = mapped_column(JSON, default=list)
    leadership: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)
    certifications: Mapped[list] = mapped_column(JSON, default=list)
    companies: Mapped[list] = mapped_column(JSON, default=list)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    achievements: Mapped[list] = mapped_column(JSON, default=list)
    publications: Mapped[list] = mapped_column(JSON, default=list)
    projects: Mapped[list] = mapped_column(JSON, default=list)

    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="candidate_profiles")
    matches: Mapped[list["JobMatch"]] = relationship(back_populates="candidate_profile")


# ---------------------------------------------------------------------------
# job_sources
# ---------------------------------------------------------------------------
class JobSourceConfig(Base):
    __tablename__ = "job_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scanned_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)

    jobs: Mapped[list["Job"]] = relationship(back_populates="source")


# ---------------------------------------------------------------------------
# company_candidates
# ---------------------------------------------------------------------------
class CompanyCandidate(Base):
    """A company name the app has heard of but not yet resolved to a job
    board - the queue that makes discovery unbounded.

    Greenhouse, Lever and Ashby only serve one company at a time, so the
    app can only read a board it can already name. Rather than accept
    that as a ceiling, every company name the app encounters anywhere
    (search results, aggregator feeds, jobs already ingested, the LLM's
    suggestions) is recorded here and probed against every supported ATS
    over subsequent runs.

    Persisting the queue is the point: probing is rate-limited, so a
    single run can only try a bounded number. Keeping state means each
    run continues where the last left off and the universe of watched
    companies compounds instead of resetting.

    `attempts`/`last_attempt_at` exist so a name that doesn't resolve is
    retried a couple of times (a board can be temporarily rate-limited)
    and then left alone, rather than burning the per-run budget forever
    on companies that simply don't use a supported platform.
    """

    __tablename__ = "company_candidates"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_company_candidate_name"),
        Index("ix_company_candidates_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # Lowercased/whitespace-collapsed, so the same employer arriving from
    # two feeds with different capitalisation is one row.
    normalized_name: Mapped[str] = mapped_column(String(255))
    # pending | resolved | unresolved
    status: Mapped[str] = mapped_column(String(20), default="pending")
    discovered_from: Mapped[str] = mapped_column(String(60), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    resolved_source_type: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------
class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_fingerprint", "fingerprint"),
        Index("ix_jobs_company_title", "company", "title"),
        Index("ix_jobs_posted_date", "posted_date"),
        Index("ix_jobs_first_seen_at", "first_seen_at"),
        UniqueConstraint("source_id", "external_job_id", name="uq_source_external_job"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_job_id: Mapped[str] = mapped_column(String(255))
    source_id: Mapped[int] = mapped_column(ForeignKey("job_sources.id"))

    company: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    preferred_qualifications: Mapped[list] = mapped_column(JSON, default=list)

    location_raw: Mapped[str] = mapped_column(String(500), default="")
    city: Mapped[str] = mapped_column(String(255), default="")
    state_province: Mapped[str] = mapped_column(String(255), default="")
    country: Mapped[str] = mapped_column(String(255), default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    work_arrangement: Mapped[str] = mapped_column(String(20), default="")  # remote|hybrid|onsite

    employment_type: Mapped[str] = mapped_column(String(30), default="")
    seniority: Mapped[str] = mapped_column(String(30), default="")

    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(10), default="")
    salary_raw_text: Mapped[str] = mapped_column(String(500), default="")

    posted_date: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    apply_url: Mapped[str] = mapped_column(String(2000), default="")
    company_url: Mapped[str] = mapped_column(String(2000), default="")
    fingerprint: Mapped[str] = mapped_column(String(64), default="")

    raw_source_data: Mapped[dict] = mapped_column(JSON, default=dict)

    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_date: Mapped[dt.datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    source: Mapped[JobSourceConfig] = relationship(back_populates="jobs")
    embeddings: Mapped[list["JobEmbedding"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    matches: Mapped[list["JobMatch"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list["ApplicationHistory"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# job_embeddings
# ---------------------------------------------------------------------------
class JobEmbedding(Base):
    __tablename__ = "job_embeddings"
    __table_args__ = (UniqueConstraint("job_id", "kind", name="uq_job_embedding_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    kind: Mapped[str] = mapped_column(String(30), default="full")  # full|title|requirements
    provider: Mapped[str] = mapped_column(String(30))
    model_name: Mapped[str] = mapped_column(String(100))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)  # packed float32 bytes
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)

    job: Mapped[Job] = relationship(back_populates="embeddings")


# ---------------------------------------------------------------------------
# job_matches
# ---------------------------------------------------------------------------
class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_profile_id", name="uq_job_candidate_match"),
        Index("ix_job_matches_score", "overall_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    candidate_profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id"))

    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str] = mapped_column(String(20), default="")

    technical_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    experience_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    industry_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    seniority_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    skill_match: Mapped[float | None] = mapped_column(Float, nullable=True)
    career_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    embedding_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)

    strengths: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    concerns: Mapped[list] = mapped_column(JSON, default=list)
    reasoning: Mapped[str] = mapped_column(Text, default="")

    passed_hard_filters: Mapped[bool] = mapped_column(Boolean, default=True)
    hard_filter_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    score_version: Mapped[int] = mapped_column(Integer, default=1)
    included_in_email: Mapped[bool] = mapped_column(Boolean, default=False)

    scored_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    job: Mapped[Job] = relationship(back_populates="matches")
    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="matches")
    feedback: Mapped[list["Feedback"]] = relationship(back_populates="job_match", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# user_preferences
# ---------------------------------------------------------------------------
class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    target_titles: Mapped[list] = mapped_column(JSON, default=list)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    work_arrangement: Mapped[str] = mapped_column(String(20), default="any")
    seniority_levels: Mapped[list] = mapped_column(JSON, default=list)

    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(10), default="USD")

    industries: Mapped[list] = mapped_column(JSON, default=list)
    preferred_companies: Mapped[list] = mapped_column(JSON, default=list)
    excluded_companies: Mapped[list] = mapped_column(JSON, default=list)

    required_keywords: Mapped[list] = mapped_column(JSON, default=list)
    preferred_keywords: Mapped[list] = mapped_column(JSON, default=list)
    excluded_keywords: Mapped[list] = mapped_column(JSON, default=list)

    employment_types: Mapped[list] = mapped_column(JSON, default=list)
    visa_preference: Mapped[str] = mapped_column(String(50), default="not_specified")
    countries_willing_to_work: Mapped[list] = mapped_column(JSON, default=list)

    priorities_text: Mapped[str] = mapped_column(Text, default="")

    # See DEFAULT_MIN_EMAIL_SCORE for why this is 75 and not a
    # higher-sounding number.
    min_email_score: Mapped[int] = mapped_column(Integer, default=DEFAULT_MIN_EMAIL_SCORE)
    max_email_jobs: Mapped[int] = mapped_column(Integer, default=15)
    score_weights: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship(back_populates="preferences")


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------
class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_match_id: Mapped[int] = mapped_column(ForeignKey("job_matches.id"))
    rating: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)

    job_match: Mapped[JobMatch] = relationship(back_populates="feedback")


# ---------------------------------------------------------------------------
# email_history
# ---------------------------------------------------------------------------
class EmailHistory(Base):
    __tablename__ = "email_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sent_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    recipient: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(500))
    job_count: Mapped[int] = mapped_column(Integer, default=0)
    job_match_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent|failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_body: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------------------
# scan_history
# ---------------------------------------------------------------------------
class ScanHistory(Base):
    __tablename__ = "scan_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="running")

    sources_scanned: Mapped[list] = mapped_column(JSON, default=list)
    jobs_retrieved: Mapped[int] = mapped_column(Integer, default=0)
    jobs_after_dedup: Mapped[int] = mapped_column(Integer, default=0)
    jobs_after_hard_filter: Mapped[int] = mapped_column(Integer, default=0)
    jobs_embedded: Mapped[int] = mapped_column(Integer, default=0)
    jobs_llm_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    new_jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    excellent_matches: Mapped[int] = mapped_column(Integer, default=0)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# application_history
# ---------------------------------------------------------------------------
class ApplicationHistory(Base):
    __tablename__ = "application_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    status: Mapped[str] = mapped_column(String(20), default="interested")
    applied_date: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)

    job: Mapped[Job] = relationship(back_populates="applications")


# ---------------------------------------------------------------------------
# settings (generic encrypted-capable key/value store)
# ---------------------------------------------------------------------------
class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True)
    value: Mapped[str] = mapped_column(Text, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# schema_migrations (bookkeeping for app/database/migrations.py)
# ---------------------------------------------------------------------------
class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[dt.datetime] = mapped_column(default=_utcnow)
    description: Mapped[str] = mapped_column(String(500), default="")
