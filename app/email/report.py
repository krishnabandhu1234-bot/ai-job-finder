"""Assembles the daily report (section 11) from real `JobMatch`/`Job`
rows - never fabricated content (section 32). Shared by the scheduler
(actually sends it), the "Send Test Email" button, and "Preview Daily
Email" (renders without sending or marking anything as notified).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.database.models import Job, JobMatch, utc_now
from app.email.templates import ReportItem, format_salary, render_html_body, render_subject, render_text_body

logger = logging.getLogger(__name__)


@dataclass
class DailyReport:
    subject: str
    html_body: str
    text_body: str
    job_match_ids: list[int]
    items: list[ReportItem]


def _to_item(match: JobMatch, job: Job) -> ReportItem:
    return ReportItem(
        match_id=match.id,
        job_id=job.id,
        title=job.title,
        company=job.company,
        location=job.location_raw,
        remote=job.remote,
        overall_score=match.overall_score,
        category=match.category,
        salary_text=format_salary(job.salary_min, job.salary_max, job.salary_currency),
        posted_date=job.posted_date,
        apply_url=job.apply_url,
        strengths=match.strengths or [],
        gaps=match.gaps or [],
        reasoning=match.reasoning or "",
    )


# How many extra matches to pull before collapsing duplicate roles. A
# company posting one role across a dozen offices is common, so fetching
# exactly `max_jobs` would leave the email short after collapsing.
_OVERFETCH_FACTOR = 6


def _role_key(job: Job) -> tuple[str, str]:
    return ((job.company or "").strip().lower(), (job.title or "").strip().lower())


def _collapse_duplicate_roles(items: list[ReportItem]) -> list[ReportItem]:
    """Folds the same role at the same company (posted once per office)
    into a single entry.

    These are genuinely distinct `Job` rows - different locations,
    different apply URLs - and the deduplicator is right to keep them
    separate in the database. But a reader given a 15-job email doesn't
    want five slots spent on one role, so they're collapsed for
    presentation only, keeping the best-scoring posting as the primary
    and recording the rest so the sender still marks every one of them
    notified (otherwise the copies simply reappear tomorrow).

    Assumes `items` is already ordered best-first, so the first posting
    seen for a role is the one worth linking to."""
    collapsed: dict[tuple[str, str], ReportItem] = {}
    for item in items:
        key = ((item.company or "").strip().lower(), (item.title or "").strip().lower())
        primary = collapsed.get(key)
        if primary is None:
            collapsed[key] = item
            continue
        primary.duplicate_job_ids.append(item.job_id)
        primary.duplicate_match_ids.append(item.match_id)
        if item.location and item.location not in primary.other_locations and item.location != primary.location:
            primary.other_locations.append(item.location)
    return list(collapsed.values())


def build_daily_report(
    session: Session,
    context,
    candidate_profile_id: int,
    min_score: float,
    max_jobs: int,
    generated_at: dt.datetime | None = None,
) -> DailyReport:
    generated_at = generated_at or utc_now()
    matches = context.job_matches_repo.unnotified_above(
        session, candidate_profile_id, min_score=min_score, limit=max_jobs * _OVERFETCH_FACTOR
    )
    items = []
    for match in matches:
        job = session.get(Job, match.job_id)
        if job is not None:
            items.append(_to_item(match, job))

    items = _collapse_duplicate_roles(items)[:max_jobs]

    # "If there's an update in the app, tell the user" - the daily email
    # is the one channel they're already reading, so a pending new
    # version rides along here rather than waiting to be noticed in
    # Settings. Never fatal: an update-check problem must not stop the
    # actual job report from going out.
    update_notice = ""
    try:
        from app.core.updates import check_for_update

        update_info = check_for_update(session, context)
        if update_info.update_available:
            update_notice = update_info.summary_line()
    except Exception:  # pragma: no cover - defensive; check_for_update already swallows
        logger.exception("Could not determine update status for the daily email")

    return DailyReport(
        subject=render_subject(len(items), generated_at),
        html_body=render_html_body(items, generated_at, update_notice),
        text_body=render_text_body(items, generated_at, update_notice),
        # Every collapsed posting, not just the primary - the sender uses
        # this to mark them all notified so the folded-in copies don't
        # resurface as "new" in tomorrow's email.
        job_match_ids=[mid for i in items for mid in i.all_match_ids],
        items=items,
    )


def build_preview_report(
    session: Session, context, candidate_profile_id: int, min_score: float, max_jobs: int
) -> DailyReport:
    """Same content as `build_daily_report` but conceptually read-only -
    the caller must not mark anything notified from this. Kept as a
    distinct name so call sites are self-documenting even though the
    underlying query is identical (a preview must show real upcoming
    email content, not a fake sample - section 29)."""
    return build_daily_report(session, context, candidate_profile_id, min_score, max_jobs)
