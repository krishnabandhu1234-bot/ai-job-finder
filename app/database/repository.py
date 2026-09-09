"""Repository layer: all direct DB/ORM access should go through here.

UI code and services should not import `app.database.models` and build
queries themselves except in the repositories below - this keeps the
schema change surface small and testable, and it's where encryption of
secret settings happens (callers never see ciphertext).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.core.security import SecretBox
from app.database.models import (
    ApplicationHistory,
    CandidateProfile,
    CompanyCandidate,
    EmailHistory,
    Feedback,
    Job,
    JobEmbedding,
    JobMatch,
    JobSourceConfig,
    Resume,
    ScanHistory,
    Setting,
    User,
    UserPreferences,
    utc_now,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings (generic key/value, optionally encrypted)
# ---------------------------------------------------------------------------
class SettingsRepository:
    def __init__(self, secret_box: SecretBox):
        self._secret_box = secret_box

    def get(self, session: Session, key: str, default: str = "") -> str:
        row = session.scalar(select(Setting).where(Setting.key == key))
        if row is None:
            return default
        if row.is_secret and row.value:
            try:
                return self._secret_box.decrypt(row.value)
            except ValueError:
                # A single corrupted/undecryptable secret must never take down
                # the whole app (e.g. at startup, while every settings page is
                # being built). Degrade to "not set" for this one value and
                # let the user re-enter it; the error is already logged by
                # SecretBox.decrypt().
                logger.error("Could not decrypt stored setting %r; treating as unset.", key)
                return default
        return row.value

    def exists(self, session: Session, key: str) -> bool:
        return session.scalar(select(Setting.id).where(Setting.key == key)) is not None

    def delete(self, session: Session, key: str) -> None:
        row = session.scalar(select(Setting).where(Setting.key == key))
        if row is not None:
            session.delete(row)
            session.flush()

    def get_bool(self, session: Session, key: str, default: bool = False) -> bool:
        raw = self.get(session, key, "true" if default else "false")
        return raw.strip().lower() in ("true", "1", "yes", "on")

    def get_int(self, session: Session, key: str, default: int = 0) -> int:
        raw = self.get(session, key, str(default))
        try:
            return int(raw)
        except ValueError:
            return default

    def set(self, session: Session, key: str, value: str, secret: bool = False) -> None:
        stored_value = self._secret_box.encrypt(value) if secret and value else value
        row = session.scalar(select(Setting).where(Setting.key == key))
        if row is None:
            row = Setting(key=key, value=stored_value, is_secret=secret)
            session.add(row)
        else:
            row.value = stored_value
            row.is_secret = secret
        session.flush()

    def all_keys(self, session: Session) -> list[str]:
        return list(session.scalars(select(Setting.key)))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserRepository:
    def get_or_create_default_user(self, session: Session, email: str, name: str = "") -> User:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name)
            session.add(user)
            session.flush()
        return user


# ---------------------------------------------------------------------------
# User preferences (job search profile)
# ---------------------------------------------------------------------------
class PreferencesRepository:
    def get_active(self, session: Session, user_id: int) -> UserPreferences:
        prefs = session.scalar(
            select(UserPreferences)
            .where(UserPreferences.user_id == user_id, UserPreferences.is_active.is_(True))
            .order_by(UserPreferences.id.desc())
        )
        if prefs is None:
            prefs = UserPreferences(user_id=user_id)
            session.add(prefs)
            session.flush()
        return prefs

    def save(self, session: Session, prefs: UserPreferences, **fields) -> UserPreferences:
        for key, value in fields.items():
            if not hasattr(prefs, key):
                raise AttributeError(f"UserPreferences has no field {key!r}")
            setattr(prefs, key, value)
        session.flush()
        return prefs


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------
class ResumeRepository:
    def create(
        self,
        session: Session,
        user_id: int,
        filename: str,
        file_path: str,
        file_type: str,
        raw_text: str = "",
        parse_error: str | None = None,
    ) -> Resume:
        resume = Resume(
            user_id=user_id,
            filename=filename,
            file_path=file_path,
            file_type=file_type,
            raw_text=raw_text,
            parse_error=parse_error,
        )
        session.add(resume)
        session.flush()
        return resume

    def list_for_user(self, session: Session, user_id: int) -> list[Resume]:
        return list(
            session.scalars(
                select(Resume)
                .where(Resume.user_id == user_id, Resume.is_active.is_(True))
                .order_by(Resume.uploaded_at.desc())
            )
        )

    def get(self, session: Session, resume_id: int) -> Resume | None:
        return session.get(Resume, resume_id)

    def deactivate(self, session: Session, resume_id: int) -> None:
        resume = session.get(Resume, resume_id)
        if resume is not None:
            resume.is_active = False
            session.flush()


# ---------------------------------------------------------------------------
# Candidate profile
# ---------------------------------------------------------------------------
class CandidateProfileRepository:
    def get_current(self, session: Session, user_id: int) -> CandidateProfile:
        profile = session.scalar(
            select(CandidateProfile)
            .where(CandidateProfile.user_id == user_id, CandidateProfile.is_current.is_(True))
            .order_by(CandidateProfile.id.desc())
        )
        if profile is None:
            profile = CandidateProfile(user_id=user_id)
            session.add(profile)
            session.flush()
        return profile

    def save(self, session: Session, profile: CandidateProfile, **fields) -> CandidateProfile:
        for key, value in fields.items():
            if not hasattr(profile, key):
                raise AttributeError(f"CandidateProfile has no field {key!r}")
            setattr(profile, key, value)
        session.flush()
        return profile


# ---------------------------------------------------------------------------
# Job sources
# ---------------------------------------------------------------------------
class JobSourceRepository:
    def list_all(self, session: Session) -> list[JobSourceConfig]:
        return list(session.scalars(select(JobSourceConfig).order_by(JobSourceConfig.id)))

    def create(
        self, session: Session, name: str, source_type: str, config: dict, enabled: bool = True
    ) -> JobSourceConfig:
        source = JobSourceConfig(name=name, source_type=source_type, config=config, enabled=enabled)
        session.add(source)
        session.flush()
        return source

    def get(self, session: Session, source_id: int) -> JobSourceConfig | None:
        return session.get(JobSourceConfig, source_id)

    def set_enabled(self, session: Session, source_id: int, enabled: bool) -> None:
        source = session.get(JobSourceConfig, source_id)
        if source is not None:
            source.enabled = enabled
            session.flush()

    def delete(self, session: Session, source_id: int) -> None:
        source = session.get(JobSourceConfig, source_id)
        if source is not None:
            session.delete(source)
            session.flush()


# ---------------------------------------------------------------------------
# Company candidates (the discovery queue)
# ---------------------------------------------------------------------------
class CompanyCandidateRepository:
    """The persisted queue of company names waiting to be probed against
    the ATS platforms - see `models.CompanyCandidate` for why it exists."""

    STATUS_PENDING = "pending"
    STATUS_RESOLVED = "resolved"
    STATUS_UNRESOLVED = "unresolved"

    # How many times a name that didn't resolve is retried before being
    # left alone. Boards are occasionally rate-limited or briefly down,
    # so one failure shouldn't be final - but most names simply aren't on
    # a supported platform, and retrying those forever would consume the
    # whole per-run budget.
    MAX_ATTEMPTS = 3

    @staticmethod
    def normalize(name: str) -> str:
        return " ".join(str(name or "").split()).casefold()

    def add_many(self, session: Session, names, discovered_from: str = "") -> int:
        """Records names not already known. Returns how many were new.

        Existing rows are left untouched, including their status: a
        company already resolved (or already exhausted its retries)
        shouldn't be reset just because another feed mentioned it."""
        cleaned = {}
        for raw in names:
            normalized = self.normalize(raw)
            if normalized and normalized not in cleaned:
                cleaned[normalized] = " ".join(str(raw).split())
        if not cleaned:
            return 0

        known = set(
            session.scalars(
                select(CompanyCandidate.normalized_name).where(
                    CompanyCandidate.normalized_name.in_(list(cleaned))
                )
            )
        )
        added = 0
        for normalized, display in cleaned.items():
            if normalized in known:
                continue
            session.add(
                CompanyCandidate(
                    name=display, normalized_name=normalized,
                    status=self.STATUS_PENDING, discovered_from=discovered_from,
                )
            )
            added += 1
        if added:
            session.flush()
        return added

    def next_batch(self, session: Session, limit: int) -> list[CompanyCandidate]:
        """The next names to probe: never-tried ones first (they're the
        most likely to resolve), then previously-failed ones that haven't
        exhausted their retries."""
        return list(
            session.scalars(
                select(CompanyCandidate)
                .where(
                    CompanyCandidate.status == self.STATUS_PENDING,
                    CompanyCandidate.attempts < self.MAX_ATTEMPTS,
                )
                .order_by(CompanyCandidate.attempts.asc(), CompanyCandidate.id.asc())
                .limit(limit)
            )
        )

    def mark_resolved(self, session: Session, candidate: CompanyCandidate, source_type: str) -> None:
        candidate.status = self.STATUS_RESOLVED
        candidate.resolved_source_type = source_type
        candidate.attempts += 1
        candidate.last_attempt_at = utc_now()
        session.flush()

    def mark_attempted(self, session: Session, candidate: CompanyCandidate) -> None:
        """Records a probe that didn't find a board. Once a candidate has
        used up its retries it stops being offered by `next_batch`."""
        candidate.attempts += 1
        candidate.last_attempt_at = utc_now()
        if candidate.attempts >= self.MAX_ATTEMPTS:
            candidate.status = self.STATUS_UNRESOLVED
        session.flush()

    def counts(self, session: Session) -> dict[str, int]:
        rows = session.execute(
            select(CompanyCandidate.status, func.count(CompanyCandidate.id))
            .group_by(CompanyCandidate.status)
        ).all()
        return {status: count for status, count in rows}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@dataclass
class DashboardStats:
    jobs_scanned_today: int = 0
    new_jobs_today: int = 0
    excellent_matches: int = 0
    strong_matches: int = 0
    email_sent_today: bool = False
    last_scan_at: dt.datetime | None = None
    last_scan_status: str = ""
    next_scan_at: dt.datetime | None = None
    top_matches: list[dict] = field(default_factory=list)


class DashboardRepository:
    def get_stats(self, session: Session) -> DashboardStats:
        today_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)

        last_scan = session.scalar(select(ScanHistory).order_by(ScanHistory.started_at.desc()))

        jobs_scanned_today = session.scalar(
            select(func.coalesce(func.sum(ScanHistory.jobs_retrieved), 0)).where(
                ScanHistory.started_at >= today_start
            )
        ) or 0

        new_jobs_today = session.scalar(
            select(func.count(Job.id)).where(Job.first_seen_at >= today_start)
        ) or 0

        excellent_matches = session.scalar(
            select(func.count(JobMatch.id)).where(JobMatch.overall_score >= 90)
        ) or 0

        strong_matches = session.scalar(
            select(func.count(JobMatch.id)).where(
                JobMatch.overall_score >= 85, JobMatch.overall_score < 90
            )
        ) or 0

        email_today = session.scalar(
            select(func.count(EmailHistory.id)).where(
                EmailHistory.sent_at >= today_start, EmailHistory.status == "sent"
            )
        ) or 0

        top_matches_rows = session.execute(
            select(JobMatch, Job)
            .join(Job, JobMatch.job_id == Job.id)
            .order_by(JobMatch.overall_score.desc())
            .limit(5)
        ).all()

        top_matches = [
            {
                "score": match.overall_score,
                "title": job.title,
                "company": job.company,
                "location": job.location_raw,
            }
            for match, job in top_matches_rows
        ]

        return DashboardStats(
            jobs_scanned_today=int(jobs_scanned_today),
            new_jobs_today=int(new_jobs_today),
            excellent_matches=int(excellent_matches),
            strong_matches=int(strong_matches),
            email_sent_today=email_today > 0,
            last_scan_at=last_scan.started_at if last_scan else None,
            last_scan_status=last_scan.status if last_scan else "",
            next_scan_at=None,  # populated once app.core.scheduler (Phase 8) is wired in
            top_matches=top_matches,
        )


# ---------------------------------------------------------------------------
# Companies (aggregated from ingested jobs)
# ---------------------------------------------------------------------------
@dataclass
class CompanyStats:
    company: str
    job_count: int
    remote_count: int
    salary_known_count: int
    avg_salary_midpoint: float | None
    salary_currency: str
    latest_posted_date: dt.datetime | None


class CompanyRepository:
    def get_company_stats(self, session: Session) -> list[CompanyStats]:
        """Real aggregation over whatever's been ingested so far - never
        fabricated (section 32/33): a company with zero scanned jobs
        simply doesn't appear here."""
        rows = session.execute(
            select(
                Job.company,
                func.count(Job.id).label("job_count"),
                func.sum(func.cast(Job.remote, Integer)).label("remote_count"),
                func.max(Job.posted_date).label("latest_posted_date"),
            )
            .where(Job.is_active.is_(True))
            .group_by(Job.company)
            .order_by(func.count(Job.id).desc())
        ).all()

        results = []
        for company, job_count, remote_count, latest_posted_date in rows:
            salary_jobs = session.scalars(
                select(Job).where(
                    Job.company == company, Job.is_active.is_(True), Job.salary_min.is_not(None)
                )
            ).all()
            midpoints = [
                (j.salary_min + (j.salary_max or j.salary_min)) / 2 for j in salary_jobs
            ]
            avg_midpoint = sum(midpoints) / len(midpoints) if midpoints else None
            currency = salary_jobs[0].salary_currency if salary_jobs else ""

            results.append(
                CompanyStats(
                    company=company,
                    job_count=job_count,
                    remote_count=remote_count or 0,
                    salary_known_count=len(midpoints),
                    avg_salary_midpoint=avg_midpoint,
                    salary_currency=currency,
                    latest_posted_date=latest_posted_date,
                )
            )
        return results


# ---------------------------------------------------------------------------
# Job embeddings (Layer 2 cache - section 18/34: never recompute an
# unchanged job's embedding)
# ---------------------------------------------------------------------------
class JobEmbeddingRepository:
    def get(self, session: Session, job_id: int, kind: str = "full") -> JobEmbedding | None:
        return session.scalar(
            select(JobEmbedding).where(JobEmbedding.job_id == job_id, JobEmbedding.kind == kind)
        )

    def upsert(
        self,
        session: Session,
        job_id: int,
        kind: str,
        provider: str,
        model_name: str,
        dimensions: int,
        vector: bytes,
    ) -> JobEmbedding:
        row = self.get(session, job_id, kind)
        if row is None:
            row = JobEmbedding(
                job_id=job_id, kind=kind, provider=provider, model_name=model_name,
                dimensions=dimensions, vector=vector,
            )
            session.add(row)
        else:
            # A stale embedding (different provider/model than what's
            # currently configured) is replaced rather than reused - mixing
            # vector spaces would make cosine similarity meaningless.
            row.provider = provider
            row.model_name = model_name
            row.dimensions = dimensions
            row.vector = vector
        session.flush()
        return row


# ---------------------------------------------------------------------------
# Job matches
# ---------------------------------------------------------------------------
class JobMatchRepository:
    def get(self, session: Session, job_id: int, candidate_profile_id: int) -> JobMatch | None:
        return session.scalar(
            select(JobMatch).where(
                JobMatch.job_id == job_id, JobMatch.candidate_profile_id == candidate_profile_id
            )
        )

    def upsert(self, session: Session, job_id: int, candidate_profile_id: int, **fields) -> JobMatch:
        row = self.get(session, job_id, candidate_profile_id)
        if row is None:
            row = JobMatch(job_id=job_id, candidate_profile_id=candidate_profile_id, **fields)
            session.add(row)
        else:
            for key, value in fields.items():
                setattr(row, key, value)
            row.scored_at = utc_now()
        session.flush()
        return row

    def jobs_needing_scoring(self, session: Session, candidate_profile_id: int, limit: int = 5000) -> list[Job]:
        """Active jobs with no match yet for this profile, or whose data
        changed since they were last scored - never re-scores unchanged
        jobs (section 34: "Do not re-analyze unchanged jobs unnecessarily")."""
        existing = (
            select(JobMatch.job_id, JobMatch.updated_at)
            .where(JobMatch.candidate_profile_id == candidate_profile_id)
            .subquery()
        )
        rows = session.execute(
            select(Job)
            .outerjoin(existing, Job.id == existing.c.job_id)
            .where(
                Job.is_active.is_(True),
                (existing.c.job_id.is_(None)) | (Job.updated_at > existing.c.updated_at),
            )
            .order_by(Job.first_seen_at.desc())
            .limit(limit)
        ).scalars().all()
        return list(rows)

    def top_matches(
        self,
        session: Session,
        candidate_profile_id: int,
        min_score: float = 0.0,
        limit: int = 200,
    ) -> list[JobMatch]:
        return list(
            session.scalars(
                select(JobMatch)
                .where(
                    JobMatch.candidate_profile_id == candidate_profile_id,
                    JobMatch.overall_score >= min_score,
                )
                .order_by(JobMatch.overall_score.desc())
                .limit(limit)
            )
        )

    def unnotified_above(
        self, session: Session, candidate_profile_id: int, min_score: float, limit: int = 50
    ) -> list[JobMatch]:
        """Matches for jobs that haven't been emailed yet - the basis for
        the daily email's "new since last time" guarantee (section 11)."""
        return list(
            session.scalars(
                select(JobMatch)
                .join(Job, JobMatch.job_id == Job.id)
                .where(
                    JobMatch.candidate_profile_id == candidate_profile_id,
                    JobMatch.overall_score >= min_score,
                    JobMatch.passed_hard_filters.is_(True),
                    Job.notified.is_(False),
                    Job.is_active.is_(True),
                )
                .order_by(JobMatch.overall_score.desc())
                .limit(limit)
            )
        )


# ---------------------------------------------------------------------------
# Feedback (section 16)
# ---------------------------------------------------------------------------
class FeedbackRepository:
    def create(self, session: Session, job_match_id: int, rating: str, note: str = "") -> Feedback:
        row = Feedback(job_match_id=job_match_id, rating=rating, note=note)
        session.add(row)
        session.flush()
        return row

    def list_for_match(self, session: Session, job_match_id: int) -> list[Feedback]:
        return list(
            session.scalars(
                select(Feedback).where(Feedback.job_match_id == job_match_id).order_by(Feedback.created_at.desc())
            )
        )

    def rated_titles_for_profile(self, session: Session, candidate_profile_id: int) -> list[tuple[str, str]]:
        """(rating, job_title) pairs for every piece of feedback the user
        has given on matches for this profile, oldest first - the raw
        input to `app.ai.feedback.compute_title_affinity`."""
        rows = session.execute(
            select(Feedback.rating, Job.title)
            .join(JobMatch, Feedback.job_match_id == JobMatch.id)
            .join(Job, JobMatch.job_id == Job.id)
            .where(JobMatch.candidate_profile_id == candidate_profile_id)
            .order_by(Feedback.created_at.asc())
        ).all()
        return [(rating, title) for rating, title in rows]


# ---------------------------------------------------------------------------
# Application tracking (section 31)
# ---------------------------------------------------------------------------
class ApplicationHistoryRepository:
    def get_for_job(self, session: Session, job_id: int) -> ApplicationHistory | None:
        return session.scalar(select(ApplicationHistory).where(ApplicationHistory.job_id == job_id))

    def set_status(
        self, session: Session, job_id: int, status: str, notes: str = "", applied_date=None
    ) -> ApplicationHistory:
        row = self.get_for_job(session, job_id)
        if row is None:
            row = ApplicationHistory(job_id=job_id, status=status, notes=notes, applied_date=applied_date)
            session.add(row)
        else:
            row.status = status
            if notes:
                row.notes = notes
            if applied_date is not None:
                row.applied_date = applied_date
        session.flush()
        return row


# ---------------------------------------------------------------------------
# Scan history (section 22 - the AI/email columns are filled in AFTER the
# scan itself completes, once ranking/email have run against the jobs it
# found; see app.core.pipeline and the Dashboard's scan->rank chain)
# ---------------------------------------------------------------------------
class ScanHistoryRepository:
    def get(self, session: Session, scan_history_id: int) -> ScanHistory | None:
        return session.get(ScanHistory, scan_history_id)

    def record_ai_results(
        self,
        session: Session,
        scan_history_id: int,
        jobs_after_hard_filter: int | None = None,
        jobs_embedded: int | None = None,
        jobs_llm_analyzed: int | None = None,
        excellent_matches: int | None = None,
        email_sent: bool | None = None,
    ) -> None:
        row = self.get(session, scan_history_id)
        if row is None:
            return
        if jobs_after_hard_filter is not None:
            row.jobs_after_hard_filter = jobs_after_hard_filter
        if jobs_embedded is not None:
            row.jobs_embedded = jobs_embedded
        if jobs_llm_analyzed is not None:
            row.jobs_llm_analyzed = jobs_llm_analyzed
        if excellent_matches is not None:
            row.excellent_matches = excellent_matches
        if email_sent is not None:
            row.email_sent = email_sent
        session.flush()
