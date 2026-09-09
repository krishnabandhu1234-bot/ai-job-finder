"""Tests for the concrete JobSource connectors. All HTTP calls are
mocked - the test suite never touches the real network (section 27)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.jobs import ashby, demo_source, greenhouse, lever
from app.jobs.ashby import AshbySource
from app.jobs.demo_source import DemoSource
from app.jobs.greenhouse import GreenhouseSource
from app.jobs.http_client import JobSourceHTTPError
from app.jobs.lever import LeverSource
from app.jobs.source import SourceFetchResult


# --- Greenhouse ------------------------------------------------------------

def test_greenhouse_source_maps_fields(monkeypatch):
    def fake_get_json(url, **kwargs):
        assert "acme" in url
        return {
            "jobs": [
                {
                    "id": 111,
                    "title": "Thermal Engineer",
                    "location": {"name": "Austin, TX"},
                    "content": "<p>Great <b>role</b></p>",
                    "updated_at": "2024-03-01T12:00:00Z",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/111",
                }
            ]
        }

    monkeypatch.setattr(greenhouse, "get_json", fake_get_json)
    source = GreenhouseSource(name="Acme (Greenhouse)", config={"board_token": "acme", "company_name": "Acme Corp"})

    result = source.fetch()

    assert result.success is True
    assert result.fetched_count == 1
    posting = result.postings[0]
    assert posting.external_job_id == "111"
    assert posting.company == "Acme Corp"
    assert posting.title == "Thermal Engineer"
    assert "Great role" in posting.description
    assert posting.location_raw == "Austin, TX"
    assert posting.posted_date == dt.datetime(2024, 3, 1, 12, 0)


def test_greenhouse_source_missing_config_fails_gracefully():
    source = GreenhouseSource(name="Bad Source", config={})
    result = source.fetch()
    assert result.success is False
    assert "board_token" in result.error


def test_greenhouse_source_http_failure_does_not_raise(monkeypatch):
    def fake_get_json(url, **kwargs):
        raise JobSourceHTTPError("boom")

    monkeypatch.setattr(greenhouse, "get_json", fake_get_json)
    source = GreenhouseSource(name="Acme", config={"board_token": "acme"})

    result = source.fetch()

    assert result.success is False
    assert "boom" in result.error
    assert result.postings == []


# --- Lever -------------------------------------------------------------

def test_lever_source_maps_fields(monkeypatch):
    def fake_get_json(url, **kwargs):
        assert "beta" in url
        return [
            {
                "id": "abc123",
                "text": "Simulation Architect",
                "categories": {"location": "Remote - United States", "commitment": "Full-time"},
                "descriptionPlain": "Build simulation platforms.",
                "createdAt": 1709294400000,  # 2024-03-01T12:00:00Z
                "hostedUrl": "https://jobs.lever.co/beta/abc123",
                "lists": [{"text": "Requirements", "content": "<ul><li>5+ years</li></ul>"}],
            }
        ]

    monkeypatch.setattr(lever, "get_json", fake_get_json)
    source = LeverSource(name="Beta (Lever)", config={"company_slug": "beta", "company_name": "Beta Dynamics"})

    result = source.fetch()

    assert result.success is True
    posting = result.postings[0]
    assert posting.company == "Beta Dynamics"
    assert posting.title == "Simulation Architect"
    assert posting.employment_type_raw == "Full-time"
    assert posting.requirements == ["5+ years"]
    assert posting.posted_date == dt.datetime(2024, 3, 1, 12, 0)


def test_lever_source_missing_config_fails_gracefully():
    result = LeverSource(name="Bad", config={}).fetch()
    assert result.success is False
    assert "company_slug" in result.error


# --- Ashby -------------------------------------------------------------

def test_ashby_source_maps_fields(monkeypatch):
    def fake_get_json(url, **kwargs):
        assert "gamma" in url
        return {
            "jobs": [
                {
                    "id": "xyz789",
                    "title": "AI Solutions Architect",
                    "location": "New York, NY",
                    "employmentType": "FullTime",
                    "isRemote": False,
                    "descriptionPlain": "Design AI systems.",
                    "publishedAt": "2024-03-02T09:00:00Z",
                    "applyUrl": "https://jobs.ashbyhq.com/gamma/xyz789",
                    "compensation": {"scrapeableCompensationSalarySummary": "$160K - $200K"},
                }
            ]
        }

    monkeypatch.setattr(ashby, "get_json", fake_get_json)
    source = AshbySource(name="Gamma (Ashby)", config={"board_name": "gamma", "company_name": "Gamma Inc"})

    result = source.fetch()

    assert result.success is True
    posting = result.postings[0]
    assert posting.company == "Gamma Inc"
    assert posting.salary_raw_text == "$160K - $200K"
    assert posting.remote_hint is False
    assert posting.posted_date == dt.datetime(2024, 3, 2, 9, 0)


def test_ashby_source_missing_config_fails_gracefully():
    result = AshbySource(name="Bad", config={}).fetch()
    assert result.success is False
    assert "board_name" in result.error


# --- Demo source -------------------------------------------------------

def test_demo_source_returns_only_fictional_companies():
    result = DemoSource(name="Demo", config={}).fetch()

    assert result.success is True
    assert result.fetched_count > 0
    for posting in result.postings:
        assert "example" in posting.company.lower() or "(example)" in posting.company.lower()
        assert posting.apply_url.startswith("https://example.com/")


def test_demo_source_is_stable_across_repeated_calls():
    """Regression test: an earlier version mutated a shared module-level
    dict on each call (`item.pop("days_ago")`), which would raise a
    KeyError on the second fetch. Demo Mode should be safe to re-scan."""
    source = DemoSource(name="Demo", config={})
    first = source.fetch()
    second = source.fetch()
    assert first.success and second.success
    assert first.fetched_count == second.fetched_count
