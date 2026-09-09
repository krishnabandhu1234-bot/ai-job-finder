"""Tests for the compounding company universe.

The point of this machinery is that discovery has no ceiling: names come
in from every direction, sit in a persisted queue, and get probed a
bounded number per run so that coverage grows every run instead of
resetting. These tests pin that behaviour - especially the parts that
would silently degrade into a fixed-size list if they regressed.
"""

from __future__ import annotations

import httpx
import pytest

import app.core.pipeline as pipeline_module
from app.database.models import CompanyCandidate, Job
from app.database.repository import CompanyCandidateRepository
from app.jobs import company_universe, http_client


# ---------------------------------------------------------------------------
# The queue itself
# ---------------------------------------------------------------------------

@pytest.fixture
def repo() -> CompanyCandidateRepository:
    return CompanyCandidateRepository()


def test_names_are_deduplicated_case_and_whitespace_insensitively(db_session, repo):
    added = repo.add_many(db_session, ["Acme Corp", "acme corp", "  Acme   Corp  "])
    assert added == 1
    assert db_session.query(CompanyCandidate).count() == 1


def test_adding_a_known_name_again_does_not_reset_its_progress(db_session, repo):
    """A company that already failed three probes must not become
    pending again just because another feed happens to mention it -
    otherwise the queue would churn on the same dead names forever and
    never reach new ones."""
    repo.add_many(db_session, ["Acme"], discovered_from="himalayas")
    candidate = db_session.query(CompanyCandidate).one()
    for _ in range(repo.MAX_ATTEMPTS):
        repo.mark_attempted(db_session, candidate)
    assert candidate.status == repo.STATUS_UNRESOLVED

    assert repo.add_many(db_session, ["acme"], discovered_from="remoteok") == 0
    assert db_session.query(CompanyCandidate).one().status == repo.STATUS_UNRESOLVED


def test_never_tried_names_are_probed_before_retries(db_session, repo):
    """Untried names resolve far more often than ones that already
    missed, so they must not sit behind a backlog of retries."""
    repo.add_many(db_session, ["Tried Once"])
    tried = db_session.query(CompanyCandidate).one()
    repo.mark_attempted(db_session, tried)
    repo.add_many(db_session, ["Fresh Name"])

    batch = repo.next_batch(db_session, limit=2)

    assert [c.name for c in batch] == ["Fresh Name", "Tried Once"]


def test_exhausted_candidates_leave_the_queue(db_session, repo):
    repo.add_many(db_session, ["Dead End"])
    candidate = db_session.query(CompanyCandidate).one()
    for _ in range(repo.MAX_ATTEMPTS):
        repo.mark_attempted(db_session, candidate)

    assert repo.next_batch(db_session, limit=10) == []
    assert repo.counts(db_session) == {repo.STATUS_UNRESOLVED: 1}


def test_resolved_candidates_are_not_probed_again(db_session, repo):
    repo.add_many(db_session, ["Found It"])
    candidate = db_session.query(CompanyCandidate).one()
    repo.mark_resolved(db_session, candidate, "greenhouse")

    assert repo.next_batch(db_session, limit=10) == []
    assert candidate.resolved_source_type == "greenhouse"


def test_blank_names_are_ignored(db_session, repo):
    assert repo.add_many(db_session, ["", "   ", None]) == 0


# ---------------------------------------------------------------------------
# Harvesting names from the keyless aggregators
# ---------------------------------------------------------------------------

def _mock_transport(monkeypatch, handler) -> None:
    monkeypatch.setattr(http_client, "_transport_override", httpx.MockTransport(handler))
    http_client.reset_throttle_state()


def test_harvests_company_names_from_arbeitnow(monkeypatch):
    def handler(request):
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(200, json={"data": [{"company_name": "Alpha GmbH"}]})
        return httpx.Response(200, json={"data": []})

    _mock_transport(monkeypatch, handler)
    assert company_universe.harvest_arbeitnow(pages=3) == {"Alpha GmbH"}


def test_harvest_stops_when_a_feed_runs_out_of_pages(monkeypatch):
    """An empty page means the end of the feed. Continuing to the full
    page budget anyway would waste a request per source per run."""
    requested = []

    def handler(request):
        requested.append(request.url.params.get("page"))
        return httpx.Response(200, json={"data": []})

    _mock_transport(monkeypatch, handler)
    company_universe.harvest_arbeitnow(pages=5)

    assert requested == ["1"]


def test_himalayas_follows_the_cursor(monkeypatch):
    def handler(request):
        if request.url.params.get("cursor") == "page2":
            return httpx.Response(200, json={"jobs": [{"companyName": "Beta"}]})
        return httpx.Response(
            200, json={"jobs": [{"companyName": "Alpha"}], "nextCursor": "page2"}
        )

    _mock_transport(monkeypatch, handler)
    assert company_universe.harvest_himalayas(pages=2) == {"Alpha", "Beta"}


def test_remoteok_ignores_the_leading_metadata_entry(monkeypatch):
    """RemoteOK's feed opens with a legal notice rather than a job."""
    _mock_transport(
        monkeypatch,
        lambda r: httpx.Response(200, json=[{"legal": "..."}, {"company": "Gamma"}]),
    )
    assert company_universe.harvest_remoteok() == {"Gamma"}


def test_one_dead_feed_never_costs_the_others(monkeypatch):
    """Aggregators go down and rate-limit constantly. Losing every name
    because one of four failed would make discovery unreliable."""
    monkeypatch.setattr(
        company_universe, "HARVESTERS",
        {
            "broken": lambda: (_ for _ in ()).throw(RuntimeError("feed down")),
            "working": lambda: {"Delta"},
        },
    )

    harvested = company_universe.harvest_company_names()

    assert harvested == {"working": {"Delta"}}


# ---------------------------------------------------------------------------
# Draining the queue during a run
# ---------------------------------------------------------------------------

class _Board:
    def __init__(self, name):
        self.display_name = name
        self.source_type = "greenhouse"
        self.config = {"board_token": name.lower()}


def test_probing_adds_a_source_and_settles_the_candidate(db_session, app_context, monkeypatch):
    app_context.company_candidates_repo.add_many(db_session, ["Acme", "Nowhere Inc"])
    monkeypatch.setattr(
        "app.jobs.discovery.resolve_company_board",
        lambda name: _Board(name) if name == "Acme" else None,
    )

    added = pipeline_module._probe_candidate_queue(db_session, app_context)

    assert added == 1
    assert [s.name for s in app_context.job_sources_repo.list_all(db_session)] == ["Acme"]
    by_name = {c.name: c for c in db_session.query(CompanyCandidate).all()}
    assert by_name["Acme"].status == CompanyCandidateRepository.STATUS_RESOLVED
    assert by_name["Nowhere Inc"].attempts == 1


def test_probing_is_bounded_per_run_but_the_rest_is_not_lost(db_session, app_context, monkeypatch):
    """The per-run budget is a pacing knob, not a ceiling: whatever is
    left over must still be waiting for the next run. This is the whole
    reason coverage compounds."""
    monkeypatch.setattr(pipeline_module, "CANDIDATE_PROBES_PER_RUN", 2)
    monkeypatch.setattr("app.jobs.discovery.resolve_company_board", lambda name: None)
    repo = app_context.company_candidates_repo
    repo.add_many(db_session, [f"Company {i}" for i in range(5)])

    pipeline_module._probe_candidate_queue(db_session, app_context)

    assert len(repo.next_batch(db_session, limit=10)) == 5  # 3 untried + 2 retryable
    assert sum(c.attempts for c in db_session.query(CompanyCandidate).all()) == 2


def test_already_configured_companies_are_settled_not_reprobed(db_session, app_context, monkeypatch):
    """Otherwise every run would burn its whole probe budget on the
    companies it already watches, and never reach a new one."""
    app_context.job_sources_repo.create(
        db_session, name="Acme", source_type="greenhouse", config={"board_token": "acme"}
    )
    app_context.company_candidates_repo.add_many(db_session, ["Acme"])
    monkeypatch.setattr(
        "app.jobs.discovery.resolve_company_board",
        lambda name: pytest.fail("must not probe an already-configured company"),
    )

    assert pipeline_module._probe_candidate_queue(db_session, app_context) == 0
    assert db_session.query(CompanyCandidate).one().status == "resolved"


def test_companies_of_ingested_jobs_are_queued(db_session, app_context, monkeypatch):
    """A job that arrived via search or an aggregator names an employer
    whose own board the app may not be watching yet. Feeding those back
    in is what turns one posting into a permanently watched company."""
    source = app_context.job_sources_repo.create(
        db_session, name="Search", source_type="resume_search", config={}
    )
    db_session.add(
        Job(
            source_id=source.id, external_job_id="1", title="Engineer",
            company="Seen In A Posting",
        )
    )
    db_session.flush()

    monkeypatch.setattr(company_universe, "HARVESTERS", {})
    monkeypatch.setattr(
        "app.jobs.resume_search_source.ensure_resume_search_source",
        lambda session, context, profile, prefs: (source, []),
    )
    monkeypatch.setattr("app.jobs.discovery.resolve_company_board", lambda name: None)

    pipeline_module._discover_by_search(db_session, app_context, None, None)

    queued = {c.name for c in db_session.query(CompanyCandidate).all()}
    assert "Seen In A Posting" in queued
