"""Runs one full job-ingestion scan (section 13, the collection half):

    for each enabled source:
        fetch -> normalize -> dedupe / new-job detection -> mark disappeared
    record ScanHistory

AI ranking, email generation, and sending are separate later stages
(Phase 4+/7) - this module's job ends at "the database now reflects
what's currently posted, and we know which jobs are new."

A failing source never stops the scan - see JobSource.fetch(), which
already turns exceptions into a failed SourceFetchResult; this module
just records that and moves on to the next source (section 4: "gracefully
handle sources that cannot be accessed").
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import ScanStatus, ScanTrigger, SourceType
from app.database.models import JobSourceConfig, ScanHistory, utc_now
from app.jobs.ashby import AshbySource
from app.jobs.career_page_source import CompanyCareerPageSource
from app.jobs.deduplicator import DedupOutcome, mark_disappeared_jobs, upsert_job
from app.jobs.demo_source import DemoSource
from app.jobs.greenhouse import GreenhouseSource
from app.jobs.lever import LeverSource
from app.jobs.normalizer import normalize_posting
from app.jobs.resume_search_source import ResumeSearchSource
from app.jobs.smartrecruiters import SmartRecruitersSource
from app.jobs.source import JobSource
from app.jobs.workable import WorkableSource

logger = logging.getLogger(__name__)

_SOURCE_CLASSES: dict[str, type[JobSource]] = {
    SourceType.GREENHOUSE.value: GreenhouseSource,
    SourceType.LEVER.value: LeverSource,
    SourceType.ASHBY.value: AshbySource,
    SourceType.WORKABLE.value: WorkableSource,
    SourceType.SMARTRECRUITERS.value: SmartRecruitersSource,
    SourceType.RESUME_SEARCH.value: ResumeSearchSource,
    SourceType.COMPANY_CAREER_PAGE.value: CompanyCareerPageSource,
    SourceType.DEMO.value: DemoSource,
}

ProgressCallback = Callable[[str], None]


def build_source(config_row: JobSourceConfig, ai_config=None, browser_config=None) -> JobSource | None:
    """`ai_config` and `browser_config` are only used by
    `CompanyCareerPageSource` - it reads an unfamiliar page far more
    reliably with an LLM than the no-AI heuristic manages alone, and can
    fall back to the user's own browser as a last resort (see that
    module). Every other connector ignores both; they're optional and
    default to None precisely so callers with no such context available
    (most of the test suite) don't need to change."""
    source_cls = _SOURCE_CLASSES.get(config_row.source_type)
    if source_cls is None:
        logger.warning(
            "No connector implemented for source type %r (source %r) - skipping.",
            config_row.source_type, config_row.name,
        )
        return None
    if source_cls is CompanyCareerPageSource:
        return source_cls(
            name=config_row.name, config=config_row.config or {},
            ai_config=ai_config, browser_config=browser_config,
        )
    return source_cls(name=config_row.name, config=config_row.config or {})


@dataclass
class ScanSummary:
    scan_history_id: int
    sources_scanned: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)
    jobs_retrieved: int = 0
    new_jobs: int = 0
    reset_as_new_jobs: int = 0
    reactivated_jobs: int = 0
    updated_jobs: int = 0
    disappeared_jobs: int = 0

    @property
    def total_new_or_reappeared(self) -> int:
        """What the app should treat as "new since last time" for the
        purposes of the daily email (Phase 7): brand-new postings plus
        ones that disappeared and came back different enough to be
        re-evaluated - NOT ones that were silently reactivated unchanged
        (those were already seen/notified)."""
        return self.new_jobs + self.reset_as_new_jobs


def run_scan(
    session: Session,
    trigger: str = ScanTrigger.MANUAL.value,
    progress_callback: ProgressCallback | None = None,
    context=None,
) -> ScanSummary:
    def report(message: str) -> None:
        logger.info(message)
        if progress_callback:
            progress_callback(message)

    scan = ScanHistory(started_at=utc_now(), trigger=trigger, status=ScanStatus.RUNNING.value)
    session.add(scan)
    session.flush()

    summary = ScanSummary(scan_history_id=scan.id)

    # Resolved once per scan, not per source: it's the same lookup
    # `resolve_ai_config` always does, and only the career-page source
    # (if any is configured) actually uses it - see `build_source`.
    # `context` is optional so every existing caller/test keeps working
    # unchanged; without it, career-page sources just run heuristic-only.
    ai_config = None
    browser_config = None
    if context is not None:
        from app.ai.embeddings import resolve_ai_config
        from app.jobs.career_page_source import resolve_browser_agent_config
        ai_config = resolve_ai_config(session, context)
        browser_config = resolve_browser_agent_config(session, context)

    enabled_sources = session.scalars(
        select(JobSourceConfig).where(JobSourceConfig.enabled.is_(True))
    ).all()

    if not enabled_sources:
        report("No job sources are enabled - nothing to scan.")

    total_sources = len(enabled_sources)
    for index, source_row in enumerate(enabled_sources, start=1):
        # The "(i/N)" suffix is deliberately machine-parseable: the
        # Dashboard's progress bar reads it out of this same message
        # rather than needing a second signal/callback threaded through
        # every layer between here and the UI.
        report(f"Scanning {source_row.name}... ({index}/{total_sources})")
        source = build_source(source_row, ai_config=ai_config, browser_config=browser_config)
        now = utc_now()

        if source is None:
            source_row.last_error = f"No connector implemented for source type {source_row.source_type!r}."
            source_row.last_scanned_at = now
            summary.sources_failed.append(source_row.name)
            continue

        result = source.fetch()
        source_row.last_scanned_at = now

        if not result.success:
            source_row.last_error = result.error
            summary.sources_failed.append(source_row.name)
            report(f"{source_row.name} failed: {result.error}")
            continue

        source_row.last_error = None
        source_row.last_success_at = now
        summary.sources_scanned.append(source_row.name)
        summary.jobs_retrieved += result.fetched_count
        report(f"{source_row.name}: retrieved {result.fetched_count} postings.")

        seen_external_ids: set[str] = set()
        for raw_posting in result.postings:
            seen_external_ids.add(raw_posting.external_job_id)
            fields = normalize_posting(raw_posting, source_row.id)
            _job, outcome = upsert_job(session, source_row, fields)

            if outcome == DedupOutcome.NEW:
                summary.new_jobs += 1
            elif outcome == DedupOutcome.RESET_AS_NEW:
                summary.reset_as_new_jobs += 1
            elif outcome == DedupOutcome.REACTIVATED:
                summary.reactivated_jobs += 1
            else:
                summary.updated_jobs += 1

        disappeared = mark_disappeared_jobs(session, source_row, seen_external_ids)
        summary.disappeared_jobs += disappeared
        if disappeared:
            report(f"{source_row.name}: {disappeared} previously-seen job(s) no longer listed.")

    session.flush()

    scan.completed_at = utc_now()
    scan.sources_scanned = summary.sources_scanned
    scan.jobs_retrieved = summary.jobs_retrieved
    scan.new_jobs_found = summary.total_new_or_reappeared
    if not enabled_sources:
        scan.status = ScanStatus.SUCCESS.value
    elif summary.sources_failed and not summary.sources_scanned:
        scan.status = ScanStatus.FAILED.value
    elif summary.sources_failed:
        scan.status = ScanStatus.PARTIAL_FAILURE.value
    else:
        scan.status = ScanStatus.SUCCESS.value
    if summary.sources_failed:
        scan.error_summary = f"Failed sources: {', '.join(summary.sources_failed)}"
    session.flush()

    report(
        f"Scan complete: {summary.jobs_retrieved} retrieved, "
        f"{summary.total_new_or_reappeared} new, {summary.disappeared_jobs} disappeared."
    )
    return summary
