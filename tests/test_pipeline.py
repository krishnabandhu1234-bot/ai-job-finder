"""Tests for the full scan -> rank -> email pipeline (section 13) and the
scan-history bookkeeping (section 22) it performs afterwards."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import app.ai.ranker as ranker_module
import app.core.pipeline as pipeline_module
import app.email.service as email_service_module
import app.jobs.scan_orchestrator as scan_orchestrator_module
from app.database.models import ScanHistory, utc_now


@dataclass
class _FakeScanSummary:
    scan_history_id: int
    jobs_retrieved: int = 3
    new_jobs: int = 2
    reset_as_new_jobs: int = 0
    updated_jobs: int = 0
    disappeared_jobs: int = 0
    sources_scanned: list = field(default_factory=lambda: ["Demo"])
    sources_failed: list = field(default_factory=list)

    @property
    def total_new_or_reappeared(self) -> int:
        return self.new_jobs + self.reset_as_new_jobs


@dataclass
class _FakeRankSummary:
    candidate_profile_id: int = 1
    jobs_considered: int = 10
    jobs_scored: int = 10
    hard_filtered_out: int = 2
    embedded: int = 8
    llm_analyzed: int = 3
    exceptional: int = 1
    excellent: int = 2
    strong: int = 4


@dataclass
class _FakeEmailResult:
    sent: bool = True
    skipped_reason: str | None = None
    error: str | None = None
    job_count: int = 3
    report: object = None


def _seed_scan_history(session) -> int:
    row = ScanHistory(started_at=utc_now(), trigger="scheduled", status="running")
    session.add(row)
    session.flush()
    return row.id


def _stub_pipeline_stages(monkeypatch, scan_id):
    monkeypatch.setattr(
        scan_orchestrator_module, "run_scan",
        lambda session, trigger, context=None: _FakeScanSummary(scan_id),
    )
    monkeypatch.setattr(ranker_module, "run_ranking", lambda session, context, progress_callback=None: _FakeRankSummary())
    monkeypatch.setattr(
        email_service_module, "send_daily_report_now", lambda session, context: _FakeEmailResult()
    )


# --------------------------------------------------------------------------
# Automatic company discovery
#
# The user never supplies a company list - every run looks for new
# employers matching their resume by itself.
# --------------------------------------------------------------------------

def test_pipeline_discovers_companies_automatically(db_session, app_context, monkeypatch):
    scan_id = _seed_scan_history(db_session)
    _stub_pipeline_stages(monkeypatch, scan_id)
    calls = []
    monkeypatch.setattr(
        pipeline_module, "run_auto_discovery", lambda context: calls.append(context) or (7, None)
    )

    db_session.commit()
    result = pipeline_module.run_full_pipeline(app_context, trigger="scheduled")
    db_session.commit()

    assert len(calls) == 1  # ran without being asked
    assert result.companies_discovered == 7


def test_discovery_failure_never_stops_the_rest_of_the_run(db_session, app_context, monkeypatch):
    """Discovery is a best-effort enhancement. A discovery problem must
    not stop scanning/ranking/emailing against companies already
    configured."""
    scan_id = _seed_scan_history(db_session)
    _stub_pipeline_stages(monkeypatch, scan_id)
    monkeypatch.setattr(
        pipeline_module, "run_auto_discovery", lambda context: (0, "provider is down")
    )

    db_session.commit()
    result = pipeline_module.run_full_pipeline(app_context, trigger="scheduled")
    db_session.commit()

    assert result.discovery_error == "provider is down"
    assert result.scan_error is None
    assert result.jobs_scored == 10
    assert result.email_sent is True


def test_auto_discovery_is_skipped_without_an_ai_provider(db_session, app_context):
    """Not an error worth surfacing on every scheduled run - the user
    simply hasn't set up an AI provider yet."""
    added, error = pipeline_module.run_auto_discovery(app_context)
    assert added == 0
    assert error is None


def test_auto_discovery_can_be_turned_off(db_session, app_context, monkeypatch):
    app_context.settings_repo.set(db_session, "discovery.auto_enabled", "false")
    db_session.commit()
    monkeypatch.setattr(
        "app.jobs.discovery.discover_and_add_sources",
        lambda *a, **kw: pytest.fail("must not run when disabled"),
    )

    added, error = pipeline_module.run_auto_discovery(app_context)

    assert added == 0 and error is None


def test_auto_discovery_reaches_harder_when_sources_are_sparse(db_session, app_context, monkeypatch):
    """A user with nothing configured needs to get to a useful state
    quickly, not trickle a few companies a day."""
    requested = {}

    class _FakeResult:
        error = None
        added = []
        suggested = []
        unresolved = []

    def _fake_discover(session, context, ai_config, profile, prefs=None, count=0, **kw):
        requested["count"] = count
        return _FakeResult()

    monkeypatch.setattr("app.jobs.discovery.discover_and_add_sources", _fake_discover)
    monkeypatch.setattr(
        "app.ai.embeddings.resolve_ai_config",
        lambda session, ctx: _UsableAIConfig(),
    )
    db_session.commit()

    pipeline_module.run_auto_discovery(app_context)

    assert requested["count"] == pipeline_module.SPARSE_DISCOVERY_BATCH


@dataclass
class _UsableAIConfig:
    """Minimal stand-in for AIRuntimeConfig that reports a working LLM."""
    def has_usable_llm(self) -> bool:
        return True


def test_pipeline_records_ai_and_email_results_on_scan_history(db_session, app_context, monkeypatch):
    scan_id = _seed_scan_history(db_session)
    monkeypatch.setattr(
        scan_orchestrator_module, "run_scan",
        lambda session, trigger, context=None: _FakeScanSummary(scan_id),
    )
    monkeypatch.setattr(ranker_module, "run_ranking", lambda session, context, progress_callback=None: _FakeRankSummary())
    monkeypatch.setattr(
        email_service_module, "send_daily_report_now", lambda session, context: _FakeEmailResult(sent=True, job_count=3)
    )

    db_session.commit()  # release db_session's open transaction so it can see the pipeline's own commits
    result = pipeline_module.run_full_pipeline(app_context, trigger="scheduled")
    db_session.commit()

    assert result.scan_error is None
    assert result.rank_error is None
    assert result.email_error is None
    assert result.jobs_scored == 10
    assert result.excellent_matches == 3  # exceptional + excellent
    assert result.email_sent is True

    with_session = app_context.scan_history_repo.get(db_session, scan_id)
    assert with_session.jobs_embedded == 8
    assert with_session.jobs_llm_analyzed == 3
    assert with_session.excellent_matches == 3
    assert with_session.email_sent is True
    assert with_session.jobs_after_hard_filter == 8  # considered - hard_filtered_out


def test_pipeline_survives_email_stage_failure(db_session, app_context, monkeypatch):
    scan_id = _seed_scan_history(db_session)
    monkeypatch.setattr(
        scan_orchestrator_module, "run_scan",
        lambda session, trigger, context=None: _FakeScanSummary(scan_id),
    )
    monkeypatch.setattr(ranker_module, "run_ranking", lambda session, context, progress_callback=None: _FakeRankSummary())

    def _raise(session, context):
        raise RuntimeError("SMTP exploded")

    monkeypatch.setattr(email_service_module, "send_daily_report_now", _raise)

    db_session.commit()
    result = pipeline_module.run_full_pipeline(app_context, trigger="scheduled")
    db_session.commit()

    assert result.email_error == "SMTP exploded"
    # Scan and ranking results are still recorded even though email failed.
    row = app_context.scan_history_repo.get(db_session, scan_id)
    assert row.jobs_embedded == 8
    assert row.email_sent is False


def test_pipeline_survives_scan_stage_failure_and_still_ranks(db_session, app_context, monkeypatch):
    def _raise(session, trigger, context=None):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(scan_orchestrator_module, "run_scan", _raise)
    monkeypatch.setattr(ranker_module, "run_ranking", lambda session, context, progress_callback=None: _FakeRankSummary())
    monkeypatch.setattr(
        email_service_module, "send_daily_report_now", lambda session, context: _FakeEmailResult(sent=False, job_count=0)
    )

    result = pipeline_module.run_full_pipeline(app_context, trigger="scheduled")

    assert result.scan_error == "network unreachable"
    assert result.scan_history_id is None
    # Ranking still ran against whatever jobs already existed.
    assert result.jobs_scored == 10
