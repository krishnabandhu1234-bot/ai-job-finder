"""Searching for jobs across every company on a platform at once.

This is what makes the app able to FIND employers rather than be told
about them. The connectors in `greenhouse.py`/`lever.py`/`workable.py`
etc. each read one named company's board - useful, but they require
already knowing the company. The providers here take a QUERY built from
the candidate's resume ("machine learning engineer") and return live
postings from across a whole platform, most of them at companies neither
the user nor a language model would ever have thought to name.

Two consequences, both of which the rest of the app makes use of:

  * the postings come back immediately, so a brand-new user gets real
    matches on their very first scan, and
  * every result names its employer, so companies can be *discovered*
    from live hiring activity - which is a far better signal than a
    model's recollection, since a company only appears here if it is
    genuinely hiring right now.

Only platforms with a public, documented search endpoint are used, hit
through the shared rate-limited client with the app's descriptive
User-Agent. Nothing here scrapes a search engine or a site that doesn't
offer this deliberately.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from app.jobs.html_text import html_to_text
from app.jobs.http_client import JobSourceHTTPError, get_json
from app.jobs.normalizer import parse_iso_datetime
from app.jobs.source import RawJobPosting

logger = logging.getLogger(__name__)

# Per-provider bounds for one search run. Kept modest because a scan
# issues several queries (one per target role), and each page is a
# separate throttled request.
DEFAULT_PAGES_PER_QUERY = 3
MAX_PAGES_PER_QUERY = 10

_WORKABLE_SEARCH_URL = "https://jobs.workable.com/api/v1/jobs"
_JOBICY_SEARCH_URL = "https://jobicy.com/api/v2/remote-jobs"

# Workable marks a remote posting by including this pseudo-location in
# the job's `locations` list (its `remote=true` query parameter returns
# nothing, so this is the reliable signal).
_TELECOMMUTE = "telecommute"


@dataclass
class SearchResults:
    postings: list[RawJobPosting] = field(default_factory=list)
    # company name -> a website/board URL, when the platform gave one.
    # Used to then add that company's full board as a source.
    companies: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "SearchResults") -> None:
        self.postings.extend(other.postings)
        for name, url in other.companies.items():
            self.companies.setdefault(name, url)
        self.errors.extend(other.errors)


def _dedupe_postings(postings: list[RawJobPosting]) -> list[RawJobPosting]:
    """Several queries ("ML engineer", "software engineer") legitimately
    return the same posting; keep the first of each."""
    seen: set[tuple[str, str]] = set()
    unique = []
    for posting in postings:
        key = (posting.company.strip().casefold(), posting.title.strip().casefold())
        if posting.external_job_id:
            key = ("id", posting.external_job_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(posting)
    return unique


# --------------------------------------------------------------------------
# Workable global search - the widest net available without an API key.
# --------------------------------------------------------------------------

def _workable_location_text(job: dict) -> str:
    location = job.get("location") or {}
    if isinstance(location, dict):
        parts = [location.get("city"), location.get("subregion"), location.get("countryName")]
        text = ", ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
        if text:
            return text
    entries = [e for e in (job.get("locations") or []) if isinstance(e, str)]
    named = [e for e in entries if e.casefold() != _TELECOMMUTE]
    return ", ".join(named)


def _workable_is_remote(job: dict) -> bool:
    return any(
        isinstance(entry, str) and entry.casefold() == _TELECOMMUTE
        for entry in (job.get("locations") or [])
    )


def _workable_posting(job: dict) -> RawJobPosting | None:
    company = (job.get("company") or {})
    company_name = (company.get("title") or "").strip()
    title = (job.get("title") or "").strip()
    if not company_name or not title:
        return None

    requirements = [
        line.strip()
        for line in html_to_text(job.get("requirementsSection") or "").split("\n")
        if line.strip()
    ]
    description = html_to_text(job.get("description") or "")
    if not description and requirements:
        # Some postings put everything in the requirements section; a job
        # with no description at all would score as though it were empty.
        description = "\n".join(requirements)

    return RawJobPosting(
        external_job_id=str(job.get("id") or ""),
        company=company_name,
        title=title,
        description=description,
        requirements=requirements,
        location_raw=_workable_location_text(job),
        employment_type_raw=job.get("employmentType") or "",
        posted_date=parse_iso_datetime(job.get("created")),
        apply_url=job.get("url") or "",
        company_url=company.get("website") or company.get("url") or "",
        remote_hint=_workable_is_remote(job),
        raw_source_data=job,
    )


def search_workable(query: str, location: str = "", pages: int = DEFAULT_PAGES_PER_QUERY) -> SearchResults:
    """Searches every company on Workable at once.

    `location` is a free-text country/city filter the API applies itself
    (verified: "United States" narrows a 1,200-result query to ~990 US
    postings). Left empty, the search is worldwide."""
    results = SearchResults()
    page_token = None

    for _page in range(max(1, min(pages, MAX_PAGES_PER_QUERY))):
        params = {"query": query}
        if location:
            params["location"] = location
        if page_token:
            params["pageToken"] = page_token

        try:
            data = get_json(_WORKABLE_SEARCH_URL, params=params)
        except JobSourceHTTPError as exc:
            results.errors.append(f"Workable search failed for {query!r}: {exc}")
            break
        if not isinstance(data, dict):
            break

        jobs = data.get("jobs") or []
        if not jobs:
            break

        for job in jobs:
            if not isinstance(job, dict):
                continue
            posting = _workable_posting(job)
            if posting is None:
                continue
            results.postings.append(posting)
            company = job.get("company") or {}
            name = (company.get("title") or "").strip()
            if name:
                results.companies.setdefault(name, company.get("website") or "")

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results


# --------------------------------------------------------------------------
# Jobicy - smaller, remote-only, but clean data and a different pool of
# employers than Workable, so it widens coverage rather than duplicating.
# --------------------------------------------------------------------------

def _jobicy_posting(job: dict) -> RawJobPosting | None:
    company_name = (job.get("companyName") or "").strip()
    title = (job.get("jobTitle") or "").strip()
    if not company_name or not title:
        return None

    posted = None
    raw_date = job.get("pubDate")
    if raw_date:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                posted = dt.datetime.strptime(str(raw_date)[:19], fmt)
                break
            except ValueError:
                continue

    description = html_to_text(job.get("jobDescription") or "") or (job.get("jobExcerpt") or "")
    return RawJobPosting(
        external_job_id=str(job.get("id") or ""),
        company=company_name,
        title=title,
        description=description,
        location_raw=job.get("jobGeo") or "",
        employment_type_raw=_first_str(job.get("jobType")),
        posted_date=posted,
        apply_url=job.get("url") or "",
        remote_hint=True,  # Jobicy is a remote-only board
        raw_source_data=job,
    )


def _first_str(value) -> str:
    """Jobicy returns some fields as either a string or a list."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def search_jobicy(query: str, pages: int = 1) -> SearchResults:
    """Searches Jobicy's remote-job board. `pages` is accepted for a
    consistent provider signature; Jobicy returns a single sized page."""
    results = SearchResults()
    try:
        data = get_json(_JOBICY_SEARCH_URL, params={"tag": query, "count": 50})
    except JobSourceHTTPError as exc:
        results.errors.append(f"Jobicy search failed for {query!r}: {exc}")
        return results
    if not isinstance(data, dict):
        return results

    for job in data.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        posting = _jobicy_posting(job)
        if posting is None:
            continue
        results.postings.append(posting)
        results.companies.setdefault(posting.company, "")
    return results


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

# (name, callable(query, location, pages) -> SearchResults)
PROVIDERS: list[tuple[str, object]] = [
    ("workable_search", lambda q, loc, pages: search_workable(q, loc, pages)),
    # Jobicy ignores the location filter (everything on it is remote).
    ("jobicy_search", lambda q, loc, pages: search_jobicy(q)),
]


def build_search_queries(profile, prefs=None, limit: int = 4) -> list[str]:
    """Turns the candidate's resume into the phrases to search for.

    Target job titles are what a posting's own title is most likely to
    say, so they come first and carry the search. A couple of headline
    skills are appended as fallbacks for people whose title is unusual
    or whose field names roles inconsistently."""
    queries: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = " ".join(str(value or "").split())
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            queries.append(text)

    for title in (getattr(prefs, "target_titles", None) or []):
        add(title)
    for role in (getattr(profile, "target_roles", None) or []):
        add(role)
    if len(queries) < limit:
        for skill in (getattr(profile, "technical_skills", None) or []):
            add(skill)

    return queries[:limit]


def search_location_filter(prefs) -> str:
    """A single free-text location for the search APIs.

    Only used when the user named somewhere specific; "Remote"/
    "Worldwide" deliberately produce no filter, since filtering a
    worldwide search by the literal word "Remote" would exclude most of
    what they actually want."""
    if prefs is None:
        return ""
    candidates = list(getattr(prefs, "countries_willing_to_work", None) or [])
    candidates += list(getattr(prefs, "locations", None) or [])
    for value in candidates:
        text = " ".join(str(value or "").split())
        if text and text.casefold() not in {"remote", "worldwide", "anywhere", "any"}:
            return text
    return ""


def search_all(
    queries: list[str],
    location: str = "",
    pages_per_query: int = DEFAULT_PAGES_PER_QUERY,
    progress_callback=None,
) -> SearchResults:
    """Runs every query against every provider and merges the results.

    Never raises: one provider being down or rate-limiting must not cost
    the user the results from the others."""
    combined = SearchResults()

    for query in queries:
        for provider_name, run in PROVIDERS:
            if progress_callback:
                progress_callback(f"Searching {provider_name.split('_')[0]} for \"{query}\"...")
            try:
                combined.merge(run(query, location, pages_per_query))
            except Exception as exc:
                logger.exception("Job search provider %s failed for %r", provider_name, query)
                combined.errors.append(f"{provider_name}: {exc}")

    combined.postings = _dedupe_postings(combined.postings)
    logger.info(
        "Job search across %d quer(ies) found %d posting(s) at %d distinct compan(ies).",
        len(queries), len(combined.postings), len(combined.companies),
    )
    return combined
