"""Tests for the Workable and SmartRecruiters connectors.

All HTTP is mocked (section 27: the suite never touches the network).
The mock payloads are trimmed copies of what the real APIs actually
returned while these connectors were written, so the field mapping is
tested against real response shapes rather than invented ones.
"""

from __future__ import annotations

import datetime as dt

from app.jobs import smartrecruiters as sr_module
from app.jobs import workable as workable_module
from app.jobs.http_client import JobSourceHTTPError
from app.jobs.smartrecruiters import SmartRecruitersSource
from app.jobs.workable import WorkableSource

# --------------------------------------------------------------------------
# Workable
# --------------------------------------------------------------------------

_WORKABLE_PAYLOAD = {
    "name": "Blueground",
    "description": "Furnished apartments",
    "jobs": [
        {
            "title": "Business Development Representative",
            "shortcode": "0FD01ABC66",
            "code": "",
            "employment_type": "Full-time",
            "telecommuting": True,
            "department": "Shared Services",
            "url": "https://apply.workable.com/j/0FD01ABC66",
            "application_url": "https://apply.workable.com/j/0FD01ABC66/apply",
            "published_on": "2026-08-18",
            "created_at": "2026-08-18",
            "country": "United States",
            "city": "",
            "state": "",
            "locations": [{"country": "United States", "city": "", "region": None}],
            "description": "<p>Sell <b>things</b></p>",
        },
        {
            "title": "Guest Operations Specialist",
            "shortcode": "90AF5EDC62",
            "employment_type": "Full-time",
            "telecommuting": False,
            "published_on": "2025-05-21",
            "country": "France",
            "city": "Paris",
            "state": "Île-de-France",
            "locations": [],
            "description": "<p>Look after guests</p>",
        },
    ],
}


def test_workable_maps_fields(monkeypatch):
    monkeypatch.setattr(workable_module, "get_json", lambda url, **kw: _WORKABLE_PAYLOAD)
    source = WorkableSource(name="Blueground", config={"account_slug": "blueground"})

    result = source.fetch()

    assert result.success is True
    assert result.fetched_count == 2
    first = result.postings[0]
    assert first.external_job_id == "0FD01ABC66"
    assert first.title == "Business Development Representative"
    assert first.employment_type_raw == "Full-time"
    assert first.apply_url.endswith("/apply")
    assert "things" in first.description  # HTML converted to text
    assert first.posted_date == dt.datetime(2026, 8, 18)


def test_workable_uses_account_display_name_not_slug(monkeypatch):
    """Discovery adds sources automatically, so the label should read
    "Blueground", not "blueground"."""
    monkeypatch.setattr(workable_module, "get_json", lambda url, **kw: _WORKABLE_PAYLOAD)
    source = WorkableSource(name="x", config={"account_slug": "blueground"})

    assert source.fetch().postings[0].company == "Blueground"


def test_workable_explicit_config_name_wins_over_api_name(monkeypatch):
    monkeypatch.setattr(workable_module, "get_json", lambda url, **kw: _WORKABLE_PAYLOAD)
    source = WorkableSource(name="x", config={"account_slug": "bg", "company_name": "My Label"})

    assert source.fetch().postings[0].company == "My Label"


def test_workable_uses_explicit_remote_flag(monkeypatch):
    """Workable states remoteness directly, which is more reliable than
    guessing it from location text."""
    monkeypatch.setattr(workable_module, "get_json", lambda url, **kw: _WORKABLE_PAYLOAD)
    postings = WorkableSource(name="x", config={"account_slug": "bg"}).fetch().postings

    assert postings[0].remote_hint is True
    assert postings[1].remote_hint is False


def test_workable_builds_location_from_whichever_fields_are_populated(monkeypatch):
    monkeypatch.setattr(workable_module, "get_json", lambda url, **kw: _WORKABLE_PAYLOAD)
    postings = WorkableSource(name="x", config={"account_slug": "bg"}).fetch().postings

    # Remote US role: only `country` is set.
    assert postings[0].location_raw == "United States"
    # Office role: city/state/country all set.
    assert postings[1].location_raw == "Paris, Île-de-France, France"


def test_workable_falls_back_to_locations_list(monkeypatch):
    payload = {
        "name": "Acme",
        "jobs": [{
            "title": "Engineer", "shortcode": "A1", "city": "", "state": "", "country": "",
            "locations": [{"city": "Berlin", "region": "BE", "country": "Germany"}],
            "description": "<p>x</p>",
        }],
    }
    monkeypatch.setattr(workable_module, "get_json", lambda url, **kw: payload)

    posting = WorkableSource(name="x", config={"account_slug": "acme"}).fetch().postings[0]
    assert posting.location_raw == "Berlin, BE, Germany"


def test_workable_requires_account_slug():
    result = WorkableSource(name="x", config={}).fetch()
    assert result.success is False
    assert "account_slug" in result.error


def test_workable_http_failure_is_contained(monkeypatch):
    def boom(url, **kwargs):
        raise JobSourceHTTPError("404 Not Found")

    monkeypatch.setattr(workable_module, "get_json", boom)
    result = WorkableSource(name="x", config={"account_slug": "nope"}).fetch()

    assert result.success is False
    assert result.postings == []


# --------------------------------------------------------------------------
# SmartRecruiters
# --------------------------------------------------------------------------

_SR_LIST = {
    "offset": 0, "limit": 100, "totalFound": 1,
    "content": [{
        "id": "744000137413079",
        "name": "Data Operations Consultant ",
        "company": {"identifier": "smartrecruiters", "name": "SmartRecruiters Inc"},
        "releasedDate": "2026-07-13T09:50:21.127Z",
        "location": {"city": "Poland", "region": "Remote", "country": "pl",
                     "remote": True, "fullLocation": "Poland, Remote, Poland"},
        "typeOfEmployment": {"id": "contract", "label": "Contract"},
        "experienceLevel": {"id": "associate", "label": "Associate"},
    }],
}

_SR_DETAIL = {
    "id": "744000137413079",
    "applyUrl": "https://jobs.smartrecruiters.com/smartrecruiters/744000137413079-data-ops?oga=true",
    "postingUrl": "https://jobs.smartrecruiters.com/smartrecruiters/744000137413079-data-ops",
    "jobAd": {"sections": {
        "companyDescription": {"title": "Company Description", "text": "<p>We make hiring software.</p>"},
        "jobDescription": {"title": "Job Description", "text": "<p>Support data migrations.</p>"},
        "qualifications": {"title": "Qualifications",
                           "text": "<p><strong>Qualifications</strong></p><ul><li>ETL tools (Talend)</li>"
                                   "<li>Python: pandas, requests</li></ul>"},
        "additionalInformation": {"title": "Additional Information", "text": "<p>EEO statement.</p>"},
    }},
}


def _fake_sr(monkeypatch, list_payload=None, detail_payload=None, detail_error=False):
    calls = []

    def fake_get_json(url, **kwargs):
        calls.append(url)
        if "/postings/" in url:
            if detail_error:
                raise JobSourceHTTPError("500")
            return detail_payload if detail_payload is not None else _SR_DETAIL
        return list_payload if list_payload is not None else _SR_LIST

    monkeypatch.setattr(sr_module, "get_json", fake_get_json)
    return calls


def test_smartrecruiters_maps_fields(monkeypatch):
    _fake_sr(monkeypatch)
    source = SmartRecruitersSource(name="SR", config={"company_slug": "smartrecruiters"})

    result = source.fetch()

    assert result.success is True
    posting = result.postings[0]
    assert posting.external_job_id == "744000137413079"
    assert posting.title == "Data Operations Consultant"
    assert posting.company == "SmartRecruiters Inc"
    assert posting.location_raw == "Poland, Remote, Poland"
    assert posting.remote_hint is True
    assert posting.employment_type_raw == "Contract"
    assert posting.apply_url.startswith("https://jobs.smartrecruiters.com/")
    assert posting.posted_date == dt.datetime(2026, 7, 13, 9, 50, 21, 127000)


def test_smartrecruiters_fetches_descriptions_from_the_detail_endpoint(monkeypatch):
    """The list endpoint omits the ad text, and description is the main
    thing the matching engine reads - a posting without one would score
    as though it were nearly empty."""
    calls = _fake_sr(monkeypatch)
    posting = SmartRecruitersSource(name="SR", config={"company_slug": "sr"}).fetch().postings[0]

    assert any("/postings/744000137413079" in c for c in calls)
    assert "Support data migrations" in posting.description
    assert "We make hiring software" in posting.description


def test_smartrecruiters_maps_qualifications_to_requirements(monkeypatch):
    """SmartRecruiters separates qualifications from the description,
    which maps directly onto the field the skill matcher weights."""
    _fake_sr(monkeypatch)
    posting = SmartRecruitersSource(name="SR", config={"company_slug": "sr"}).fetch().postings[0]

    assert any("Talend" in r for r in posting.requirements)
    assert any("pandas" in r for r in posting.requirements)


def test_smartrecruiters_drops_the_repeated_section_heading(monkeypatch):
    """Real ads repeat the section name as the first line of its own
    body; stored as a requirement it would be matched against as if it
    were a skill."""
    _fake_sr(monkeypatch)
    posting = SmartRecruitersSource(name="SR", config={"company_slug": "sr"}).fetch().postings[0]

    assert "Qualifications" not in posting.requirements


def test_smartrecruiters_survives_a_failed_detail_fetch(monkeypatch):
    """One bad detail call must not lose the posting or fail the source -
    title and location are still useful."""
    _fake_sr(monkeypatch, detail_error=True)
    result = SmartRecruitersSource(name="SR", config={"company_slug": "sr"}).fetch()

    assert result.success is True
    assert result.fetched_count == 1
    assert result.postings[0].title == "Data Operations Consultant"
    assert result.postings[0].description == ""


def test_smartrecruiters_caps_detail_fetches(monkeypatch):
    """A huge board must not turn one scan into thousands of requests."""
    many = {"offset": 0, "limit": 100, "totalFound": 5, "content": [
        {"id": str(i), "name": f"Role {i}", "company": {"name": "Big"}, "location": {}}
        for i in range(5)
    ]}
    calls = _fake_sr(monkeypatch, list_payload=many)

    result = SmartRecruitersSource(
        name="SR", config={"company_slug": "big", "max_detail_fetches": 2}
    ).fetch()

    assert result.fetched_count == 5  # every posting is still returned...
    assert sum(1 for c in calls if "/postings/" in c) == 2  # ...but only 2 got details


def test_smartrecruiters_caps_total_postings(monkeypatch):
    many = {"offset": 0, "limit": 100, "totalFound": 10, "content": [
        {"id": str(i), "name": f"Role {i}", "company": {"name": "Big"}, "location": {}}
        for i in range(10)
    ]}
    _fake_sr(monkeypatch, list_payload=many)

    result = SmartRecruitersSource(
        name="SR", config={"company_slug": "big", "max_postings": 3, "max_detail_fetches": 0}
    ).fetch()

    assert result.fetched_count == 3


def test_smartrecruiters_requires_company_slug():
    result = SmartRecruitersSource(name="x", config={}).fetch()
    assert result.success is False
    assert "company_slug" in result.error


def test_smartrecruiters_empty_board_returns_no_postings(monkeypatch):
    """An unknown company answers 200-with-zero rather than 404 here, so
    "empty" is the only available signal that a slug was wrong."""
    _fake_sr(monkeypatch, list_payload={"offset": 0, "limit": 100, "totalFound": 0, "content": []})

    result = SmartRecruitersSource(name="x", config={"company_slug": "nope"}).fetch()

    assert result.success is True
    assert result.postings == []
