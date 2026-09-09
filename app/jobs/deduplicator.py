"""New-job detection and cross-source deduplication (section 7).

Two matching strategies, tried in order:
  1. Exact (source_id, external_job_id) match - we've already stored this
     exact posting from this exact source before.
  2. Fingerprint match against ANY source's active jobs - the same role
     posted on a company's Greenhouse board AND scraped from their career
     page (or by a second source entirely) should collapse into one `Job`
     row rather than showing up twice.

Reappearance handling: a job that goes inactive (absent from a source's
latest fetch - see `mark_disappeared_jobs`) and later comes back is NOT
automatically treated as brand new (which would re-notify the user of a
job they already saw) or automatically treated as the same old job
(which would hide a genuinely new posting reusing the same title/company/
location, e.g. a role that closed and reopened months later with a
different scope). We use a simple, explainable heuristic: if it reappears
soon and the description reads the same, it's the same job; if it's been
gone a long time or the description changed substantially, treat it as
new (reset first_seen_at/notified so it can be re-evaluated and
re-notified).
"""

from __future__ import annotations

import difflib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Job, JobSourceConfig, utc_now

logger = logging.getLogger(__name__)

REAPPEARANCE_STALE_DAYS = 45
DESCRIPTION_SIMILARITY_REAPPEAR_THRESHOLD = 0.85


class DedupOutcome:
    NEW = "new"
    UPDATED = "updated"
    REACTIVATED = "reactivated"
    RESET_AS_NEW = "reset_as_new"


def upsert_job(session: Session, source: JobSourceConfig, fields: dict) -> tuple[Job, str]:
    """`fields` is normalizer.normalize_posting()'s output for one
    posting. Finds or creates the matching `Job` row. Returns
    (job, outcome) where outcome is one of the `DedupOutcome` constants -
    callers (the scan orchestrator) use this to count new vs. seen jobs
    without re-deriving the logic."""
    from app.jobs.normalizer import compute_fingerprint

    fingerprint = compute_fingerprint(fields["company"], fields["title"], fields["location_raw"])
    fields = {**fields, "fingerprint": fingerprint}

    existing = session.scalar(
        select(Job).where(Job.source_id == source.id, Job.external_job_id == fields["external_job_id"])
    )
    if existing is None:
        existing = session.scalar(select(Job).where(Job.fingerprint == fingerprint, Job.is_active.is_(True)))

    now = utc_now()

    if existing is None:
        job = Job(**fields, first_seen_at=now, last_seen_at=now, is_active=True)
        session.add(job)
        session.flush()
        return job, DedupOutcome.NEW

    was_inactive = not existing.is_active
    outcome = DedupOutcome.UPDATED

    if was_inactive:
        stale = existing.last_seen_at is not None and (now - existing.last_seen_at).days > REAPPEARANCE_STALE_DAYS
        similarity = difflib.SequenceMatcher(
            None, existing.description or "", fields.get("description") or ""
        ).ratio()
        changed_substantially = similarity < DESCRIPTION_SIMILARITY_REAPPEAR_THRESHOLD

        if stale or changed_substantially:
            existing.first_seen_at = now
            existing.notified = False
            existing.notification_date = None
            outcome = DedupOutcome.RESET_AS_NEW
            logger.info(
                "Job %r at %r reappeared after being gone (stale=%s, similarity=%.2f) - treating as new.",
                fields["title"], fields["company"], stale, similarity,
            )
        else:
            outcome = DedupOutcome.REACTIVATED
            logger.info(
                "Job %r at %r reappeared and looks unchanged - reactivating, not re-notifying.",
                fields["title"], fields["company"],
            )

    for key, value in fields.items():
        if key in ("external_job_id", "source_id") and existing.source_id != source.id:
            # This match came from the cross-source fingerprint path, not
            # the same source/external-id pair - don't overwrite the
            # original source's (source_id, external_job_id) identity with
            # this other source's values. Doing so for source_id alone
            # (leaving external_job_id untouched, as an earlier version of
            # this guard did) would silently detach the row from BOTH
            # sources' own (source_id, external_job_id) lookups - future
            # scans of either source would then create a fresh duplicate
            # row instead of matching this one.
            continue
        setattr(existing, key, value)

    existing.is_active = True
    existing.last_seen_at = now
    session.flush()
    return existing, outcome


def mark_disappeared_jobs(session: Session, source: JobSourceConfig, seen_external_ids: set[str]) -> int:
    """Jobs previously active for this source but absent from the latest
    fetch are marked inactive (never deleted - see reappearance handling
    in `upsert_job` above). Returns the count marked inactive."""
    jobs = session.scalars(select(Job).where(Job.source_id == source.id, Job.is_active.is_(True))).all()
    count = 0
    for job in jobs:
        if job.external_job_id not in seen_external_ids:
            job.is_active = False
            count += 1
    if count:
        session.flush()
    return count
