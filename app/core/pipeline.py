"""The full section-13 workflow, run end-to-end without any Qt
dependency so it can execute from a background APScheduler thread (the
scheduler, Phase 8) exactly the same way it would from a script or a
future CLI:

    discover new companies to watch (automatic - see below)
    -> scan (collect, normalize, dedupe, detect new)
    -> AI/ML ranking (hard filters, embeddings, LLM shortlist)
    -> send daily email (only if something meets the bar)
    -> record scan history / log results

Each stage commits independently (its own `session_scope()`), so a
failure partway through never rolls back and discards work an earlier
stage already completed - e.g. a broken SMTP password should never
also erase a scan's results.

The discovery stage exists so the user never has to supply a list of
companies, and so that nothing caps how many can eventually be watched.

It works as a compounding queue rather than a fixed list, because the
ATS platforms serve one company at a time and publish no index of their
boards (see `app/jobs/company_universe.py`). Every run:

  * runs resume-derived queries against the platforms that DO offer
    cross-company search, ingesting those postings immediately,
  * harvests company names from the keyless job aggregators, which index
    employers across every ATS including the unsearchable ones,
  * records the company of every job already in the database, and
  * asks the configured AI (if any) to name more.

All of those names land in `company_candidates`, and a bounded number
are probed against all five supported ATS platforms each run; whatever
isn't reached waits for the next run rather than being discarded. So the
set of companies actually being watched grows every single run with no
ceiling, instead of resetting to whatever one search could see.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.constants import ScanTrigger
from app.database.db import session_scope

logger = logging.getLogger(__name__)

# How many companies one automatic discovery round asks for. Deliberately
# modest: each run adds a few more on top of everything already found, so
# coverage compounds over days without any single run hammering the ATS
# APIs or running up a large LLM bill.
AUTO_DISCOVERY_BATCH = 15
# Below this many sources the app has too little to work with to produce
# meaningful matches, so discovery reaches harder on that run to get the
# user to a useful state quickly instead of trickling.
SPARSE_SOURCE_THRESHOLD = 5
SPARSE_DISCOVERY_BATCH = 40
# How many queued company names get probed against the ATS platforms per
# run. Each probe is a handful of throttled HTTP requests, so this is the
# knob that trades a run's duration against how fast the watched set
# grows. It is NOT a ceiling on coverage: unprobed names stay in
# `company_candidates` and the next run continues from there, so given
# enough runs every harvested company gets checked.
CANDIDATE_PROBES_PER_RUN = 60
# Concurrent board probes. Bounded well below the number of candidates:
# the gain comes from overlapping waits on five different ATS hosts, and
# each host stays rate-limited independently, so more workers past this
# buys latency hiding rather than throughput.
PROBE_WORKERS = 6


@dataclass
class PipelineResult:
    scan_history_id: int | None = None
    discovery_error: str | None = None
    scan_error: str | None = None
    rank_error: str | None = None
    email_error: str | None = None
    companies_discovered: int = 0
    jobs_retrieved: int = 0
    new_jobs: int = 0
    jobs_scored: int = 0
    excellent_matches: int = 0
    email_sent: bool = False
    email_job_count: int = 0


def run_auto_discovery(context) -> tuple[int, str | None]:
    """Finds and adds new companies to watch, with no user input.

    Two independent mechanisms, in order of value:

    1. **Search and harvest** (`_discover_by_search`) - resume-derived
       queries run against every company on the platforms with a public
       search API, plus a sweep of the keyless aggregators for company
       names, all funnelled into the candidate queue and probed. Needs
       no AI provider and no API key, so it works for every user, and
       its coverage compounds run over run.
    2. **AI suggestion** (`app.jobs.discovery`) - additionally asks the
       configured LLM to name relevant employers. Useful for named
       companies too small or too new to appear in any aggregator, but a
       supplement rather than the foundation.

    Returns (companies_added, error). Never raises: discovery is a
    best-effort enhancement, and a discovery problem must never stop the
    scan/rank/email work that follows from running against companies
    already configured."""
    try:
        with session_scope() as session:
            if not context.settings_repo.get_bool(session, "discovery.auto_enabled", True):
                return 0, None

            user = context.users_repo.get_or_create_default_user(
                session, context.config.email_to or "local-user@aijobfinder.local"
            )
            profile = context.candidate_profile_repo.get_current(session, user.id)
            prefs = context.preferences_repo.get_active(session, user.id)

            added = _discover_by_search(session, context, profile, prefs)
            ai_added, ai_error = _discover_by_ai(session, context, profile, prefs)
            return added + ai_added, ai_error
    except Exception as exc:
        logger.exception("Pipeline: auto-discovery stage failed")
        return 0, str(exc)


def _discover_by_search(session, context, profile, prefs) -> int:
    """Keeps the resume-driven search current, feeds every company name
    the app can find into the candidate queue, and works through that
    queue probing candidates against every supported ATS.

    This is the part with no ceiling. Search alone only reaches the
    platforms that publish a cross-company search endpoint; the queue
    reaches any company whose *name* the app can learn from anywhere,
    which is what makes coverage compound run over run instead of
    stopping at whatever one search could see."""
    from app.jobs.company_universe import harvest_company_names
    from app.jobs.job_search import search_all, search_location_filter
    from app.jobs.resume_search_source import ensure_resume_search_source

    repo = context.company_candidates_repo

    # 1. Keep the search source's queries in step with the resume.
    _source, queries = ensure_resume_search_source(session, context, profile, prefs)

    # 2. Feed the queue from role-matched search...
    if queries:
        results = search_all(queries, location=search_location_filter(prefs), pages_per_query=2)
        if results.companies:
            repo.add_many(session, results.companies.keys(), discovered_from="job_search")

    # 3. ...from the broad aggregator feeds (these index employers across
    #    every ATS, including ones with no searchable endpoint)...
    for source_name, names in harvest_company_names().items():
        repo.add_many(session, names, discovered_from=source_name)

    # 4. ...and from every company already in the database, whatever
    #    source it arrived from. A company seen once in a posting is a
    #    strong candidate for having a full board worth watching.
    repo.add_many(session, _companies_seen_in_jobs(session), discovered_from="ingested_jobs")

    # 5. Work through the queue, bounded per run.
    return _probe_candidate_queue(session, context)


def _companies_seen_in_jobs(session) -> list[str]:
    from sqlalchemy import select

    from app.database.models import Job

    return [name for (name,) in session.execute(select(Job.company).distinct()).all() if name]


def _probe_candidate_queue(session, context) -> int:
    """Probes the next batch of candidate companies against every
    supported ATS, adding a source for each that resolves.

    Bounded per run because each probe is a handful of throttled HTTP
    requests; the queue is persisted, so the next run simply continues
    rather than starting over."""
    from app.jobs.discovery import _existing_company_keys

    repo = context.company_candidates_repo
    candidates = repo.next_batch(session, CANDIDATE_PROBES_PER_RUN)
    if not candidates:
        return 0

    existing = _existing_company_keys(session, context)
    to_probe = []
    for candidate in candidates:
        if candidate.normalized_name in existing:
            # Already being watched (added by an earlier run or by hand);
            # settle the queue entry rather than re-probing it forever.
            repo.mark_resolved(session, candidate, candidate.resolved_source_type or "already_configured")
        else:
            to_probe.append(candidate)

    added = 0
    for candidate, board in _resolve_boards_concurrently(to_probe):
        if board is None:
            repo.mark_attempted(session, candidate)
            continue
        try:
            context.job_sources_repo.create(
                session, name=board.display_name, source_type=board.source_type, config=board.config
            )
            session.flush()
            repo.mark_resolved(session, candidate, board.source_type)
            added += 1
        except Exception:
            logger.exception("Could not save discovered source for %r", candidate.name)
            repo.mark_attempted(session, candidate)

    counts = repo.counts(session)
    logger.info(
        "Company queue: probed %d, added %d board(s). Queue now: %d pending, %d resolved, %d unresolved.",
        len(to_probe), added,
        counts.get(repo.STATUS_PENDING, 0),
        counts.get(repo.STATUS_RESOLVED, 0),
        counts.get(repo.STATUS_UNRESOLVED, 0),
    )
    return added


def _resolve_boards_concurrently(candidates):
    """Yields (candidate, resolved_board_or_None) for each candidate.

    Probing is almost entirely spent waiting on the network, and a miss
    costs several requests, so doing it serially is what would really cap
    how many companies a run can check. The requests go to five different
    ATS hosts and `http_client` enforces its rate limit per host under a
    lock, so running these in parallel doesn't send any single host
    requests faster than the serial version did - it just stops the app
    idling while one host thinks.

    Only the network happens here. Every database write stays on the
    calling thread, because the SQLAlchemy session isn't thread-safe."""
    from concurrent.futures import ThreadPoolExecutor

    from app.jobs.discovery import resolve_company_board

    if not candidates:
        return

    def probe(candidate):
        try:
            return resolve_company_board(candidate.name)
        except Exception:
            logger.exception("Probing %r failed unexpectedly", candidate.name)
            return None

    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        # zip over the input order rather than as_completed: the results
        # need to line up with their candidates, and ordering doesn't
        # matter since the whole batch is awaited anyway.
        yield from zip(candidates, pool.map(probe, candidates))


def _discover_by_ai(session, context, profile, prefs) -> tuple[int, str | None]:
    """Supplements search with the LLM's own knowledge of employers."""
    from app.ai.embeddings import resolve_ai_config
    from app.jobs.discovery import discover_and_add_sources

    ai_config = resolve_ai_config(session, context)
    if not ai_config.has_usable_llm():
        # Not an error worth surfacing on every scheduled run - search
        # above already ran and needs no AI provider.
        logger.info("AI company suggestion skipped: no AI provider configured.")
        return 0, None

    source_count = len(context.job_sources_repo.list_all(session))
    count = SPARSE_DISCOVERY_BATCH if source_count < SPARSE_SOURCE_THRESHOLD else AUTO_DISCOVERY_BATCH

    discovery = discover_and_add_sources(session, context, ai_config, profile, prefs, count=count)
    if discovery.error:
        logger.info("AI company suggestion could not run: %s", discovery.error)
        return 0, discovery.error

    # Names the model suggested but that didn't resolve right now go into
    # the queue rather than being thrown away: a probe can miss because a
    # board was briefly unreachable, and the queue retries.
    if discovery.unresolved:
        context.company_candidates_repo.add_many(
            session, discovery.unresolved, discovered_from="ai_suggestion"
        )
    logger.info(
        "AI company suggestion added %d board(s) (%d suggested, %d had no board).",
        len(discovery.added), len(discovery.suggested), len(discovery.unresolved),
    )
    return len(discovery.added), None


def run_full_pipeline(context, trigger: str = ScanTrigger.SCHEDULED.value) -> PipelineResult:
    from app.ai.ranker import run_ranking
    from app.email.service import send_daily_report_now
    from app.jobs.scan_orchestrator import run_scan

    result = PipelineResult()

    result.companies_discovered, result.discovery_error = run_auto_discovery(context)

    try:
        with session_scope() as session:
            scan_summary = run_scan(session, trigger=trigger, context=context)
            result.scan_history_id = scan_summary.scan_history_id
            result.jobs_retrieved = scan_summary.jobs_retrieved
            result.new_jobs = scan_summary.total_new_or_reappeared
    except Exception as exc:
        logger.exception("Pipeline: scan stage failed")
        result.scan_error = str(exc)

    rank_summary = None
    try:
        with session_scope() as session:
            rank_summary = run_ranking(session, context)
            result.jobs_scored = rank_summary.jobs_scored
            result.excellent_matches = rank_summary.exceptional + rank_summary.excellent
    except Exception as exc:
        logger.exception("Pipeline: ranking stage failed")
        result.rank_error = str(exc)

    try:
        with session_scope() as session:
            email_result = send_daily_report_now(session, context)
            result.email_sent = email_result.sent
            result.email_job_count = email_result.job_count
            if email_result.error:
                result.email_error = email_result.error
    except Exception as exc:
        logger.exception("Pipeline: email stage failed")
        result.email_error = str(exc)

    # Section 22: the scan_history row is the durable record of a run - fill
    # in the AI/email columns that only become known after the later stages
    # complete, so the History page reflects what actually happened rather
    # than always showing zeros/"No" for a scan that in fact found and
    # emailed strong matches.
    if result.scan_history_id is not None:
        try:
            with session_scope() as session:
                context.scan_history_repo.record_ai_results(
                    session, result.scan_history_id,
                    jobs_after_hard_filter=(
                        rank_summary.jobs_considered - rank_summary.hard_filtered_out
                        if rank_summary is not None else None
                    ),
                    jobs_embedded=rank_summary.embedded if rank_summary is not None else None,
                    jobs_llm_analyzed=rank_summary.llm_analyzed if rank_summary is not None else None,
                    excellent_matches=result.excellent_matches,
                    email_sent=result.email_sent,
                )
        except Exception:
            logger.exception("Pipeline: could not record AI/email results onto scan history")

    logger.info(
        "Pipeline run (%s) complete: discovered=%d retrieved=%d new=%d scored=%d excellent=%d email_sent=%s",
        trigger, result.companies_discovered, result.jobs_retrieved, result.new_jobs,
        result.jobs_scored, result.excellent_matches, result.email_sent,
    )
    return result
