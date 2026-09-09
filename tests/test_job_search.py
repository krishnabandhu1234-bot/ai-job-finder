"""Tests for query-driven job search (`app/jobs/job_search.py`) - the
mechanism that lets the app FIND employers rather than be told about
them.

All HTTP is mocked. The mock payloads are trimmed copies of what the
real APIs actually returned while this was written, so field mapping is
tested against real response shapes rather than invented ones.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.jobs import job_search
from app.jobs.job_search import (
    SearchResults,
    build_search_queries,
    search_all,
    search_jobicy,
    search_location_filter,
    search_workable,
)
from app.jobs.http_client import JobSourceHTTPError


# Trimmed from a real jobs.workable.com/api/v1/jobs response.
_WORKABLE_PAGE = {
    "totalSize": 1233,
    "nextPageToken": None,
    "jobs": [
        {
            "id": "d2e33be6",
            "title": "Machine Learning Engineer",
            "description": "<p>Build ML systems.</p>",
            "requirementsSection": "<ul><li>5+ years Python</li><li>PyTorch</li></ul>",
            "employmentType": "Full-time",
            "created": "2025-12-09T17:51:33.870Z",
            "url": "https://jobs.workable.com/view/abc/ml-engineer",
            "location": {"city": "", "subregion": None, "countryName": "United States"},
            "locations": ["TELECOMMUTE", "United States"],
            "company": {"title": "Tiger Analytics Inc.", "website": "https://tigeranalytics.com/"},
        },
        {
            "id": "f860e65d",
            "title": "ML Engineer - Reinforcement Learning",
            "description": "<p>Self-driving.</p>",
            "requirementsSection": "",
            "employmentType": "Full-time",
            "created": "2026-01-05T09:00:00.000Z",
            "url": "https://jobs.workable.com/view/def/rl",
            "location": {"city": "Fremont", "subregion": "California", "countryName": "United States"},
            "locations": ["Fremont"],
            "company": {"title": "pony.ai", "website": "http://www.pony.ai"},
        },
    ],
}

_JOBICY_PAGE = {
    "jobCount": 2,
    "jobs": [
        {
            "id": 111,
            "jobTitle": "Senior Machine Learning Engineer",
            "companyName": "SeatGeek",
            "jobGeo": "USA",
            "jobType": ["full-time"],
            "jobDescription": "<p>Ranking models.</p>",
            "jobExcerpt": "Ranking models",
            "url": "https://jobicy.com/jobs/111",
            "pubDate": "2026-02-01 10:00:00",
        },
        {
            "id": 222,
            "jobTitle": "ML Platform Engineer",
            "companyName": "Roboflow",
            "jobGeo": "Anywhere",
            "jobType": "contract",
            "jobDescription": "",
            "jobExcerpt": "Vision infra",
            "url": "https://jobicy.com/jobs/222",
            "pubDate": "bad-date",
        },
    ],
}


# --------------------------------------------------------------------------
# Workable global search
# --------------------------------------------------------------------------

def test_workable_search_maps_fields(monkeypatch):
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: _WORKABLE_PAGE)

    results = search_workable("machine learning engineer")

    assert len(results.postings) == 2
    first = results.postings[0]
    assert first.company == "Tiger Analytics Inc."
    assert first.title == "Machine Learning Engineer"
    assert "Build ML systems" in first.description
    assert any("Python" in r for r in first.requirements)
    assert first.employment_type_raw == "Full-time"
    assert first.apply_url.endswith("/ml-engineer")
    assert first.posted_date == dt.datetime(2025, 12, 9, 17, 51, 33, 870000)


def test_workable_search_discovers_companies(monkeypatch):
    """The whole point: employers the user never named."""
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: _WORKABLE_PAGE)

    results = search_workable("machine learning engineer")

    assert set(results.companies) == {"Tiger Analytics Inc.", "pony.ai"}
    assert results.companies["pony.ai"] == "http://www.pony.ai"


def test_workable_detects_remote_from_the_telecommute_marker(monkeypatch):
    """Workable's `remote=true` query parameter returns nothing (verified
    against the live API), so remoteness has to come from the special
    TELECOMMUTE entry in `locations`."""
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: _WORKABLE_PAGE)

    postings = search_workable("x").postings

    assert postings[0].remote_hint is True   # has TELECOMMUTE
    assert postings[1].remote_hint is False  # office role


def test_workable_location_prefers_the_structured_fields(monkeypatch):
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: _WORKABLE_PAGE)
    postings = search_workable("x").postings

    assert postings[0].location_raw == "United States"
    assert postings[1].location_raw == "Fremont, California, United States"


def test_workable_passes_the_query_and_location_through(monkeypatch):
    captured = {}

    def _fake(url, **kwargs):
        captured.update(kwargs.get("params") or {})
        return {"jobs": []}

    monkeypatch.setattr(job_search, "get_json", _fake)
    search_workable("data engineer", location="Germany")

    assert captured["query"] == "data engineer"
    assert captured["location"] == "Germany"


def test_workable_follows_pagination(monkeypatch):
    pages = [
        {"jobs": _WORKABLE_PAGE["jobs"][:1], "nextPageToken": "tok"},
        {"jobs": _WORKABLE_PAGE["jobs"][1:], "nextPageToken": None},
    ]
    calls = []

    def _fake(url, **kwargs):
        calls.append((kwargs.get("params") or {}).get("pageToken"))
        return pages[len(calls) - 1]

    monkeypatch.setattr(job_search, "get_json", _fake)
    results = search_workable("x", pages=5)

    assert len(results.postings) == 2
    assert calls == [None, "tok"]  # second request carried the token


def test_workable_stops_at_the_page_limit(monkeypatch):
    calls = []

    def _fake(url, **kwargs):
        calls.append(1)
        return {"jobs": _WORKABLE_PAGE["jobs"], "nextPageToken": "always-more"}

    monkeypatch.setattr(job_search, "get_json", _fake)
    search_workable("x", pages=3)

    assert len(calls) == 3  # bounded, despite the API always offering more


def test_workable_search_failure_is_captured_not_raised(monkeypatch):
    def _boom(url, **kwargs):
        raise JobSourceHTTPError("429 rate limited")

    monkeypatch.setattr(job_search, "get_json", _boom)
    results = search_workable("x")

    assert results.postings == []
    assert results.errors and "429" in results.errors[0]


def test_workable_skips_entries_missing_a_company_or_title(monkeypatch):
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: {
        "jobs": [
            {"id": "1", "title": "Engineer", "company": {}},          # no company name
            {"id": "2", "title": "", "company": {"title": "Acme"}},   # no title
            {"id": "3", "title": "Good", "company": {"title": "Acme"}},
        ]
    })

    results = search_workable("x")

    assert [p.title for p in results.postings] == ["Good"]


# --------------------------------------------------------------------------
# Jobicy
# --------------------------------------------------------------------------

def test_jobicy_search_maps_fields(monkeypatch):
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: _JOBICY_PAGE)

    results = search_jobicy("machine learning")

    assert [p.company for p in results.postings] == ["SeatGeek", "Roboflow"]
    assert results.postings[0].posted_date == dt.datetime(2026, 2, 1, 10, 0, 0)
    assert results.postings[0].remote_hint is True  # Jobicy is remote-only


def test_jobicy_handles_string_or_list_job_type(monkeypatch):
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: _JOBICY_PAGE)
    postings = search_jobicy("x").postings

    assert postings[0].employment_type_raw == "full-time"  # from a list
    assert postings[1].employment_type_raw == "contract"   # from a string


def test_jobicy_tolerates_an_unparseable_date(monkeypatch):
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: _JOBICY_PAGE)
    assert search_jobicy("x").postings[1].posted_date is None


def test_jobicy_falls_back_to_the_excerpt_when_there_is_no_description(monkeypatch):
    monkeypatch.setattr(job_search, "get_json", lambda url, **kw: _JOBICY_PAGE)
    assert search_jobicy("x").postings[1].description == "Vision infra"


# --------------------------------------------------------------------------
# Query building
# --------------------------------------------------------------------------

class _Profile:
    target_roles = ["ML Engineer", "Data Scientist"]
    technical_skills = ["Kubernetes", "Spark"]


class _Prefs:
    target_titles = ["Machine Learning Engineer"]
    countries_willing_to_work = ["United States"]
    locations = ["Austin, TX"]


def test_queries_lead_with_the_users_own_target_titles():
    """A posting's title is what the search actually matches, and the
    user's chosen titles are the best guess at that."""
    queries = build_search_queries(_Profile(), _Prefs())
    assert queries[0] == "Machine Learning Engineer"


def test_queries_fall_back_to_resume_roles_and_skills():
    class _NoPrefs:
        target_titles = []
        countries_willing_to_work = []
        locations = []

    queries = build_search_queries(_Profile(), _NoPrefs(), limit=4)
    assert "ML Engineer" in queries
    assert "Kubernetes" in queries  # skills fill the remaining slots


def test_queries_are_deduplicated_case_insensitively():
    class _Dupes:
        target_roles = ["ML Engineer", "ml engineer", "ML  Engineer"]
        technical_skills = []

    queries = build_search_queries(_Dupes(), None)
    assert len(queries) == 1


def test_queries_are_capped():
    class _Many:
        target_roles = [f"Role {i}" for i in range(20)]
        technical_skills = []

    assert len(build_search_queries(_Many(), None, limit=3)) == 3


def test_no_queries_without_a_profile():
    class _Empty:
        target_roles = []
        technical_skills = []

    assert build_search_queries(_Empty(), None) == []


# --------------------------------------------------------------------------
# Location filter
# --------------------------------------------------------------------------

def test_location_filter_uses_a_named_country():
    assert search_location_filter(_Prefs()) == "United States"


def test_remote_is_not_used_as_a_location_filter():
    """Filtering a worldwide search by the literal word "Remote" would
    exclude most of what a remote-seeking user actually wants."""
    class _RemotePrefs:
        countries_willing_to_work = ["Remote"]
        locations = ["Worldwide", "Anywhere"]

    assert search_location_filter(_RemotePrefs()) == ""


def test_location_filter_handles_no_prefs():
    assert search_location_filter(None) == ""


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def test_search_all_merges_providers_and_deduplicates(monkeypatch):
    def _fake_workable(q, loc, pages):
        r = SearchResults()
        r.postings.append(_posting("Acme", "Engineer", "dup-id"))
        r.companies["Acme"] = ""
        return r

    def _fake_jobicy(q, loc, pages):
        r = SearchResults()
        r.postings.append(_posting("Acme", "Engineer", "dup-id"))  # same posting
        r.postings.append(_posting("Globex", "Scientist", "other"))
        r.companies["Globex"] = ""
        return r

    monkeypatch.setattr(job_search, "PROVIDERS", [("workable", _fake_workable), ("jobicy", _fake_jobicy)])

    results = search_all(["a", "b"])

    titles = sorted(p.title for p in results.postings)
    assert titles == ["Engineer", "Scientist"]  # duplicate collapsed
    assert set(results.companies) == {"Acme", "Globex"}


def test_one_provider_failing_does_not_lose_the_others(monkeypatch):
    def _broken(q, loc, pages):
        raise RuntimeError("provider exploded")

    def _working(q, loc, pages):
        r = SearchResults()
        r.postings.append(_posting("Acme", "Engineer", "1"))
        return r

    monkeypatch.setattr(job_search, "PROVIDERS", [("broken", _broken), ("working", _working)])

    results = search_all(["a"])

    assert len(results.postings) == 1
    assert any("provider exploded" in e for e in results.errors)


def _posting(company: str, title: str, job_id: str):
    from app.jobs.source import RawJobPosting

    return RawJobPosting(external_job_id=job_id, company=company, title=title)
