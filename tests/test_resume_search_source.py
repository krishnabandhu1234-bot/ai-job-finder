"""Tests for the resume-driven search source
(`app/jobs/resume_search_source.py`) - the source that searches for
roles matching the user's resume across every company on a platform,
rather than reading one named company's board.
"""

from __future__ import annotations

import pytest

from app.core.constants import SourceType
from app.jobs import resume_search_source as module
from app.jobs.job_search import SearchResults
from app.jobs.resume_search_source import ResumeSearchSource, ensure_resume_search_source
from app.jobs.scan_orchestrator import build_source
from app.jobs.source import RawJobPosting


def _posting(company="Acme", title="ML Engineer", job_id="1"):
    return RawJobPosting(external_job_id=job_id, company=company, title=title)


# --------------------------------------------------------------------------
# The source itself
# --------------------------------------------------------------------------

def test_source_searches_its_configured_queries(monkeypatch):
    captured = {}

    def _fake_search_all(queries, location="", pages_per_query=3, progress_callback=None):
        captured["queries"] = queries
        captured["location"] = location
        results = SearchResults()
        results.postings.append(_posting())
        return results

    monkeypatch.setattr(module, "search_all", _fake_search_all)
    source = ResumeSearchSource(
        name="search", config={"queries": ["ML Engineer", "Backend Engineer"], "location": "Germany"}
    )

    result = source.fetch()

    assert result.success is True
    assert result.fetched_count == 1
    assert captured["queries"] == ["ML Engineer", "Backend Engineer"]
    assert captured["location"] == "Germany"


def test_source_is_a_noop_without_queries(monkeypatch):
    """No target roles yet (no resume uploaded) isn't an error - there's
    simply nothing to search for."""
    monkeypatch.setattr(
        module, "search_all", lambda *a, **kw: pytest.fail("must not search with no queries")
    )

    result = ResumeSearchSource(name="search", config={"queries": []}).fetch()

    assert result.success is True
    assert result.postings == []


def test_source_ignores_blank_queries(monkeypatch):
    monkeypatch.setattr(
        module, "search_all", lambda *a, **kw: pytest.fail("must not search with only blanks")
    )
    result = ResumeSearchSource(name="search", config={"queries": ["", "   "]}).fetch()
    assert result.postings == []


def test_a_provider_error_does_not_fail_the_source(monkeypatch):
    """One search provider being down shouldn't cost the user the
    postings the others returned."""
    def _fake_search_all(queries, **kwargs):
        results = SearchResults()
        results.postings.append(_posting())
        results.errors.append("jobicy_search: 500 server error")
        return results

    monkeypatch.setattr(module, "search_all", _fake_search_all)

    result = ResumeSearchSource(name="search", config={"queries": ["x"]}).fetch()

    assert result.success is True
    assert result.fetched_count == 1


def test_the_orchestrator_can_build_this_source_type(db_session, app_context):
    """It has to be wired into `build_source`, or scans would silently
    skip it with "no connector implemented"."""
    row = app_context.job_sources_repo.create(
        db_session, name="search", source_type=SourceType.RESUME_SEARCH.value,
        config={"queries": ["ML Engineer"]},
    )
    db_session.flush()

    assert isinstance(build_source(row), ResumeSearchSource)


# --------------------------------------------------------------------------
# Keeping the search in step with the resume
# --------------------------------------------------------------------------

class _Profile:
    target_roles = ["ML Engineer"]
    technical_skills = ["Kubernetes"]


class _Prefs:
    target_titles = ["Machine Learning Engineer"]
    countries_willing_to_work = ["United States"]
    locations = []


def test_ensure_creates_the_source_with_resume_derived_queries(db_session, app_context):
    source, queries = ensure_resume_search_source(db_session, app_context, _Profile(), _Prefs())

    assert source.source_type == SourceType.RESUME_SEARCH.value
    assert queries[0] == "Machine Learning Engineer"
    assert source.config["location"] == "United States"


def test_ensure_is_idempotent(db_session, app_context):
    """Called before every scan - it must refresh the one source, not
    create a new one each time."""
    ensure_resume_search_source(db_session, app_context, _Profile(), _Prefs())
    ensure_resume_search_source(db_session, app_context, _Profile(), _Prefs())

    search_sources = [
        s for s in app_context.job_sources_repo.list_all(db_session)
        if s.source_type == SourceType.RESUME_SEARCH.value
    ]
    assert len(search_sources) == 1


def test_ensure_refreshes_queries_when_the_profile_changes(db_session, app_context):
    """Editing your target titles must change what the app searches for,
    without you touching anything else."""
    ensure_resume_search_source(db_session, app_context, _Profile(), _Prefs())

    class _NewPrefs:
        target_titles = ["Data Engineer"]
        countries_willing_to_work = ["Germany"]
        locations = []

    source, queries = ensure_resume_search_source(db_session, app_context, _Profile(), _NewPrefs())

    assert queries[0] == "Data Engineer"
    assert source.config["location"] == "Germany"
