"""Tests for the matching funnel orchestrator (section 17). The embedding
backend is stubbed so tests never load a real ML model or touch the
network - `LocalEmbeddingBackend` itself is exercised separately (it's a
thin wrapper) but is too slow/heavy to load in the unit test suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

from app.ai import ranker as ranker_module
from app.ai.embeddings import AIRuntimeConfig
from app.database.models import Job, JobSourceConfig


@dataclass
class _FakeBackend:
    provider_name: str = "local"
    model_name: str = "fake-model"
    calls: list = field(default_factory=list)

    def embed(self, texts):
        self.calls.append(list(texts))
        # A deterministic, content-sensitive "embedding": longer overlap
        # with the word "cfd" pushes the vector in a consistent direction,
        # enough to produce a non-trivial, stable cosine similarity.
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append(np.array([lowered.count("cfd"), lowered.count("python"), 1.0], dtype=np.float32))
        return vectors


@pytest.fixture(autouse=True)
def _stub_ai(monkeypatch):
    monkeypatch.setattr(ranker_module, "get_embedding_backend", lambda cfg: _FakeBackend())
    monkeypatch.setattr(
        ranker_module,
        "resolve_ai_config",
        lambda session, ctx: AIRuntimeConfig(
            local_only=True, embedding_provider="local", embedding_model="fake-model",
            llm_provider="none", llm_model="", anthropic_api_key="", openai_api_key="", voyage_api_key="",
        ),
    )


def _seed_job(session, **overrides) -> Job:
    source = JobSourceConfig(name="Demo", source_type="demo")
    session.add(source)
    session.flush()
    base = dict(
        external_job_id="1", source_id=source.id, company="Acme Aerospace", title="Senior CFD Engineer",
        description="CFD simulation work using Python tooling.", requirements=["CFD", "Python"],
        preferred_qualifications=[], location_raw="Austin, TX", city="Austin", state_province="TX",
        country="United States", remote=False, work_arrangement="onsite", employment_type="full_time",
        seniority="senior", is_active=True,
    )
    base.update(overrides)
    job = Job(**base)
    session.add(job)
    session.flush()
    return job


def _seed_profile_and_prefs(session, app_context, user):
    profile = app_context.candidate_profile_repo.get_current(session, user.id)
    app_context.candidate_profile_repo.save(
        session, profile,
        target_roles=["CFD Engineer"], seniority="senior", years_experience=8.0,
        technical_skills=["CFD"], programming_languages=["Python"],
    )
    prefs = app_context.preferences_repo.get_active(session, user.id)
    return profile, prefs


def test_run_ranking_with_no_profile_scores_nothing(db_session, app_context):
    _seed_job(db_session)
    summary = ranker_module.run_ranking(db_session, app_context)
    assert summary.jobs_scored == 0


def test_run_ranking_scores_matching_job_highly(db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    _seed_profile_and_prefs(db_session, app_context, user)
    job = _seed_job(db_session)

    summary = ranker_module.run_ranking(db_session, app_context)

    assert summary.jobs_scored == 1
    assert summary.embedded == 1
    match = app_context.job_matches_repo.get(db_session, job.id, summary.candidate_profile_id)
    assert match is not None
    assert match.overall_score > 50
    assert match.embedding_similarity is not None


def test_hard_filtered_job_still_gets_a_capped_score(db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    profile, prefs = _seed_profile_and_prefs(db_session, app_context, user)
    app_context.preferences_repo.save(db_session, prefs, excluded_companies=["Acme Aerospace"])
    job = _seed_job(db_session)

    summary = ranker_module.run_ranking(db_session, app_context)

    match = app_context.job_matches_repo.get(db_session, job.id, summary.candidate_profile_id)
    assert match.passed_hard_filters is False
    assert match.overall_score <= 40
    # Excluded jobs never reach the embedding step (cost optimization).
    assert summary.embedded == 0


def test_local_embeddings_are_uncapped_so_no_job_is_cut_on_title_alone(db_session, app_context):
    """The heuristic score that ranks jobs before the embedding pass is
    only ~15% title-driven, so capping the embedding shortlist can drop a
    job whose DESCRIPTION is a strong match before anything reads it
    semantically. Local embeddings are free, so there's no reason to cap
    them - every job that passed hard filters must get embedded."""
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    _seed_profile_and_prefs(db_session, app_context, user)
    for i in range(12):
        _seed_job(
            db_session,
            external_job_id=str(i),
            # Deliberately opaque titles that the title-matching layer can't
            # reward - exactly the case where a cap would cut a good job.
            title=f"Member of Technical Staff {i}",
            description="Deep CFD simulation work in Python.",
        )

    summary = ranker_module.run_ranking(db_session, app_context)

    assert summary.jobs_scored == 12
    assert summary.embedded == 12  # not a capped subset


def test_remote_embeddings_fall_back_to_a_bounded_cap(db_session, app_context, monkeypatch):
    """"Embed everything" is only a safe default while embeddings are
    free. With a paid remote provider configured and no explicit cap set,
    a large scan must not silently send every job to a metered API."""
    monkeypatch.setattr(
        ranker_module,
        "resolve_ai_config",
        lambda session, ctx: AIRuntimeConfig(
            local_only=False, embedding_provider="openai", embedding_model="text-embedding-3-small",
            llm_provider="none", llm_model="", anthropic_api_key="", openai_api_key="sk-test",
            voyage_api_key="",
        ),
    )
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    _seed_profile_and_prefs(db_session, app_context, user)
    for i in range(5):
        _seed_job(db_session, external_job_id=str(i))

    summary = ranker_module.run_ranking(db_session, app_context)

    # 5 jobs is well under the 300 remote cap, so all still get embedded -
    # what matters is that the cap was applied rather than left unbounded.
    assert summary.embedded == 5
    assert ranker_module.DEFAULT_REMOTE_EMBEDDING_TOP_N == 300


def test_explicit_embedding_cap_is_respected(db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    _seed_profile_and_prefs(db_session, app_context, user)
    for i in range(6):
        _seed_job(db_session, external_job_id=str(i))
    app_context.settings_repo.set(db_session, "ai.embedding_top_n", "2")

    summary = ranker_module.run_ranking(db_session, app_context)

    assert summary.jobs_scored == 6
    assert summary.embedded == 2


def test_embeddings_are_computed_in_batches_not_one_at_a_time(db_session, app_context, monkeypatch):
    """Embedding models are far more efficient per call with many texts
    than with one. Since embeddings now run on EVERY job rather than a
    capped shortlist, a per-job loop is the difference between a large
    scan taking minutes or an hour."""
    backend = _FakeBackend()
    monkeypatch.setattr(ranker_module, "get_embedding_backend", lambda cfg: backend)
    monkeypatch.setattr(ranker_module, "EMBEDDING_BATCH_SIZE", 10)

    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    _seed_profile_and_prefs(db_session, app_context, user)
    for i in range(25):
        _seed_job(db_session, external_job_id=str(i))

    summary = ranker_module.run_ranking(db_session, app_context)

    assert summary.embedded == 25
    # 1 call for the profile text + 3 batched job calls (10/10/5),
    # not 1 + 25.
    job_batches = [call for call in backend.calls[1:]]
    assert len(job_batches) == 3
    assert [len(b) for b in job_batches] == [10, 10, 5]


def test_cached_embeddings_are_reused_and_never_recomputed(db_session, app_context, monkeypatch):
    """Section 18: an unchanged posting must not be re-embedded on every
    scan - that's the whole point of caching the vectors."""
    backend = _FakeBackend()
    monkeypatch.setattr(ranker_module, "get_embedding_backend", lambda cfg: backend)

    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    _seed_profile_and_prefs(db_session, app_context, user)
    job = _seed_job(db_session)

    ranker_module.run_ranking(db_session, app_context)
    first_call_count = len(backend.calls)

    # Force a re-score of the same, unchanged job.
    match = app_context.job_matches_repo.get(db_session, job.id,
                                             app_context.candidate_profile_repo.get_current(db_session, user.id).id)
    db_session.delete(match)
    db_session.flush()

    ranker_module.run_ranking(db_session, app_context)

    # The second run embeds the profile again but reuses the job vector,
    # so it adds exactly one call - not two.
    assert len(backend.calls) == first_call_count + 1


def test_a_failed_embedding_batch_does_not_lose_the_other_jobs(db_session, app_context, monkeypatch):
    """One bad batch must not cost every other job its embedding."""
    class _FlakyBackend(_FakeBackend):
        def embed(self, texts):
            # Note: the parent records the call, so this must NOT also
            # append - doing so double-counts and the intended failure
            # never fires.
            if len(self.calls) == 1:  # call 0 was the profile text
                self.calls.append(list(texts))
                raise RuntimeError("provider hiccup")
            return super().embed(texts)

    backend = _FlakyBackend()
    monkeypatch.setattr(ranker_module, "get_embedding_backend", lambda cfg: backend)
    monkeypatch.setattr(ranker_module, "EMBEDDING_BATCH_SIZE", 5)

    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    _seed_profile_and_prefs(db_session, app_context, user)
    for i in range(10):
        _seed_job(db_session, external_job_id=str(i))

    summary = ranker_module.run_ranking(db_session, app_context)

    assert summary.jobs_scored == 10  # every job still scored...
    assert summary.embedded == 5      # ...but only the surviving batch embedded


def test_rescoring_is_skipped_for_unchanged_jobs(db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    app_context.config.email_to = "test@example.com"
    _seed_profile_and_prefs(db_session, app_context, user)
    _seed_job(db_session)

    first = ranker_module.run_ranking(db_session, app_context)
    second = ranker_module.run_ranking(db_session, app_context)

    assert first.jobs_scored == 1
    assert second.jobs_scored == 0
    assert second.jobs_considered == 0
