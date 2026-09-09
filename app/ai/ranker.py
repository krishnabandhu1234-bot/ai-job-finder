"""The matching funnel (section 17): turns "every active job in the
database" into scored `JobMatch` rows while keeping expensive work
(embeddings, LLM calls) confined to shrinking shortlists.

    all active jobs needing (re-)scoring
    -> Layers 1-5 heuristic score (cheap, runs on everything)          [app.ai.matcher]
    -> top `embedding_top_n` by heuristic score
    -> Layer 2 semantic similarity, blended in                        [app.ai.embeddings]
    -> top `llm_top_n` by blended score
    -> Layer 6 LLM reasoning (only if configured and not local-only)   [app.ai.llm_analyzer]
    -> JobMatch rows persisted for every job that was scored at all

A job that never made the embedding/LLM shortlist still gets a stored
heuristic-only `JobMatch` row (so Job Matches / Companies pages have
something to show), it just won't have `embedding_similarity` or
LLM-refined component scores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from app.ai.embeddings import (
    calibrate_similarity,
    cosine_similarity,
    get_embedding_backend,
    pack_vector,
    resolve_ai_config,
    unpack_vector,
)
from app.ai.feedback import compute_title_affinity
from app.ai.llm_analyzer import analyze_with_llm
from app.ai.matcher import apply_embedding_similarity, apply_llm_analysis, evaluate_match
from app.core.constants import MatchCategory

logger = logging.getLogger(__name__)

# `0` means "no cap - embed every job that passed hard filters". That is
# the DEFAULT for local embeddings, which cost nothing and run offline:
# capping them buys nothing and actively hurts recall, because the
# heuristic score that decides the cut is only ~15% job-title-driven and
# can rank a genuinely great match low purely on unusual phrasing - and
# once it's cut, its description is never read semantically at all. A
# remote (paid, per-call) provider keeps a real cap instead.
EMBED_ALL = 0
DEFAULT_REMOTE_EMBEDDING_TOP_N = 300
DEFAULT_EMBEDDING_TOP_N = EMBED_ALL
DEFAULT_LLM_TOP_N = 20

# Job descriptions sent to the embedding model per call. Large enough
# that batching actually pays off, small enough to keep progress
# reporting responsive and to stay inside remote providers' per-request
# limits. See `_job_vectors`.
EMBEDDING_BATCH_SIZE = 64

ProgressCallback = Callable[[str], None]


@dataclass
class RankingSummary:
    candidate_profile_id: int
    jobs_considered: int = 0
    jobs_scored: int = 0
    hard_filtered_out: int = 0
    embedded: int = 0
    llm_analyzed: int = 0
    exceptional: int = 0
    excellent: int = 0
    strong: int = 0


def _candidate_profile_text(profile) -> str:
    parts = [
        " ".join(profile.target_roles or []),
        profile.seniority or "",
        " ".join(profile.technical_skills or []),
        " ".join(profile.programming_languages or []),
        " ".join(profile.software or []),
        " ".join(profile.domain_expertise or []),
        " ".join(profile.industries or []),
        " ".join(profile.achievements or []),
        " ".join(profile.certifications or []),
    ]
    return " ".join(p for p in parts if p)


def _job_text(job) -> str:
    return " ".join(
        [job.title or "", job.description or ""]
        + (job.requirements or [])
        + (job.preferred_qualifications or [])
    )


def _job_vectors(session, context, backend, embedding_pool, report) -> dict[int, np.ndarray]:
    """Embedding vector per job id, reusing cached vectors and computing
    the rest in batches.

    Batching matters a great deal here. Embedding models process many
    texts per call far more efficiently than one at a time (the local
    model runs a single padded forward pass instead of N tiny ones, and
    a remote provider charges one request instead of N), and since
    embeddings now run on EVERY job rather than a capped shortlist, a
    per-job loop is the difference between a scan of several hundred
    companies finishing in minutes or in an hour.

    Cached vectors are never recomputed (section 18), and a cache entry
    from a different provider/model is ignored rather than mixed with
    fresh ones - vectors from different models aren't comparable, so
    blending them would produce meaningless similarities."""
    vectors: dict[int, np.ndarray] = {}
    pending: list = []

    for job, _result in embedding_pool:
        cached = context.job_embeddings_repo.get(session, job.id, kind="full")
        if cached and cached.provider == backend.provider_name and cached.model_name == backend.model_name:
            vectors[job.id] = unpack_vector(cached.vector)
        else:
            pending.append(job)

    if not pending:
        return vectors

    if vectors:
        report(f"Reusing {len(vectors)} cached embedding(s); computing {len(pending)} new one(s)...")

    for start in range(0, len(pending), EMBEDDING_BATCH_SIZE):
        batch = pending[start:start + EMBEDDING_BATCH_SIZE]
        if len(pending) > EMBEDDING_BATCH_SIZE:
            report(
                f"Computing semantic similarity... "
                f"{min(start + len(batch), len(pending))}/{len(pending)}"
            )
        try:
            computed = backend.embed([_job_text(job) for job in batch])
        except Exception:
            # One bad batch shouldn't cost every other job its embedding;
            # those jobs simply keep their heuristic-only score.
            logger.exception("Embedding batch failed; those jobs keep heuristic-only scores.")
            continue

        for job, vector in zip(batch, computed):
            vectors[job.id] = vector
            context.job_embeddings_repo.upsert(
                session, job.id, "full", backend.provider_name, backend.model_name,
                len(vector), pack_vector(vector),
            )

    return vectors


def run_ranking(session, context, progress_callback: ProgressCallback | None = None) -> RankingSummary:
    def report(message: str) -> None:
        logger.info(message)
        if progress_callback:
            progress_callback(message)

    user = context.users_repo.get_or_create_default_user(
        session, context.config.email_to or "local-user@aijobfinder.local"
    )
    profile = context.candidate_profile_repo.get_current(session, user.id)
    prefs = context.preferences_repo.get_active(session, user.id)
    ai_config = resolve_ai_config(session, context)

    embedding_top_n = context.settings_repo.get_int(session, "ai.embedding_top_n", DEFAULT_EMBEDDING_TOP_N)
    llm_top_n = context.settings_repo.get_int(session, "ai.llm_top_n", DEFAULT_LLM_TOP_N)
    if embedding_top_n == EMBED_ALL and not ai_config.uses_local_embeddings():
        # "No cap" is only a sane default while embeddings are free. If the
        # user has switched to a paid remote provider without also setting
        # an explicit cap, fall back to a bounded one rather than silently
        # sending every job in the database to a metered API.
        embedding_top_n = DEFAULT_REMOTE_EMBEDDING_TOP_N

    summary = RankingSummary(candidate_profile_id=profile.id)

    if not (profile.target_roles or profile.technical_skills or profile.programming_languages):
        report("No candidate profile found yet - upload a resume before running matching.")
        return summary

    jobs = context.job_matches_repo.jobs_needing_scoring(session, profile.id)
    summary.jobs_considered = len(jobs)
    if not jobs:
        report("No new or changed jobs to score.")
        return summary
    report(f"Scoring {len(jobs)} job(s) against your profile...")

    rated_titles = context.feedback_repo.rated_titles_for_profile(session, profile.id)
    title_affinity = compute_title_affinity(rated_titles)

    heuristic_results: dict[int, tuple] = {}
    for job in jobs:
        result = evaluate_match(profile, job, prefs, title_affinity=title_affinity)
        if not result.passed_hard_filters:
            summary.hard_filtered_out += 1
        heuristic_results[job.id] = (job, result)

    ranked = sorted(
        [(job, r) for job, r in heuristic_results.values() if r.passed_hard_filters],
        key=lambda pair: pair[1].overall_score,
        reverse=True,
    )
    embedding_pool = ranked if embedding_top_n == EMBED_ALL else ranked[:embedding_top_n]
    shortlist_ids = {job.id for job, _ in embedding_pool}

    if shortlist_ids:
        report(f"Computing semantic similarity for {len(shortlist_ids)} job(s)...")
        try:
            backend = get_embedding_backend(ai_config)
            profile_vector = backend.embed([_candidate_profile_text(profile)])[0]
            vectors = _job_vectors(session, context, backend, embedding_pool, report)

            for job, result in embedding_pool:
                job_vector = vectors.get(job.id)
                if job_vector is None:
                    continue
                # Calibrated, not raw: raw cosine tops out around 73 even
                # for a near-perfect match and floors around 15 for
                # totally unrelated text, so blending the raw number in
                # would systematically understate good matches. See
                # `calibrate_similarity`.
                similarity = calibrate_similarity(cosine_similarity(profile_vector, job_vector))
                apply_embedding_similarity(result, similarity, prefs)
                summary.embedded += 1
        except Exception:
            logger.exception("Embedding step failed; continuing with heuristic-only scores.")

    ranked.sort(key=lambda pair: pair[1].overall_score, reverse=True)
    llm_shortlist = ranked[:llm_top_n] if ai_config.has_usable_llm() else []

    if llm_shortlist:
        report(f"Running LLM analysis on the top {len(llm_shortlist)} job(s)...")
    for index, (job, result) in enumerate(llm_shortlist, start=1):
        # "(i/N)" is machine-parseable - see the matching comment in
        # scan_orchestrator.run_scan. This is the slowest stage of a
        # ranking run (one network round trip per job), so it's the one
        # most worth a determinate progress bar rather than a spinner.
        report(f"Running LLM analysis... ({index}/{len(llm_shortlist)})")
        try:
            llm_result = analyze_with_llm(ai_config, profile, job, result)
        except Exception:
            logger.exception("LLM analysis raised unexpectedly for job %s; keeping heuristic score.", job.id)
            llm_result = None
        if llm_result is not None:
            apply_llm_analysis(result, llm_result, prefs)
            summary.llm_analyzed += 1

    for job, result in heuristic_results.values():
        context.job_matches_repo.upsert(
            session,
            job_id=job.id,
            candidate_profile_id=profile.id,
            overall_score=result.overall_score,
            category=result.category,
            technical_match=result.technical_match,
            experience_match=result.experience_match,
            industry_match=result.industry_match,
            seniority_match=result.seniority_match,
            location_match=result.location_match,
            skill_match=result.skill_match,
            career_fit=result.career_fit,
            confidence=result.confidence,
            embedding_similarity=result.embedding_similarity,
            strengths=result.strengths,
            gaps=result.gaps,
            concerns=result.concerns,
            reasoning=result.reasoning,
            passed_hard_filters=result.passed_hard_filters,
            hard_filter_reason=result.hard_filter_reason,
        )
        summary.jobs_scored += 1
        if result.category == MatchCategory.EXCEPTIONAL.value:
            summary.exceptional += 1
        elif result.category == MatchCategory.EXCELLENT.value:
            summary.excellent += 1
        elif result.category == MatchCategory.STRONG.value:
            summary.strong += 1

    session.flush()
    report(
        f"Matching complete: {summary.jobs_scored} scored, {summary.embedded} embedded, "
        f"{summary.llm_analyzed} LLM-analyzed, {summary.exceptional} exceptional, "
        f"{summary.excellent} excellent, {summary.strong} strong matches."
    )
    return summary

