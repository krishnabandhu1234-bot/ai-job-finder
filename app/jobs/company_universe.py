"""Building an ever-growing universe of companies to watch.

The hard constraint this works around: Greenhouse, Lever, Ashby and
SmartRecruiters serve one company at a time. There is no index of their
boards and no cross-company search (all verified against the live APIs -
`/v1/boards`, `/v1/postings`, `posting-api/search` are 404/401). So the
app can only read a board it can already *name*, and the real question
is never "how do I search every company" but "how do I keep learning
company names?"

The answer here is a compounding queue rather than a fixed list. Every
company name the app encounters from any direction gets recorded:

  * job aggregators with open, keyless APIs (Himalayas, RemoteOK,
    Arbeitnow, Jobicy) - these index employers across every ATS,
    including ones with no searchable endpoint of their own,
  * the cross-company search providers (`app/jobs/job_search.py`),
  * every job already ingested, whatever source it came from, and
  * the LLM's suggestions, where one is configured.

Names then sit in `company_candidates` and are probed against all five
supported ATS platforms a bounded number per run. Because the queue is
persisted, each run continues where the last stopped, so the set of
companies actually being watched grows every single run instead of
resetting - which is what removes the ceiling. A first harvest yields
several hundred names; deeper pagination over days yields thousands.

Everything here is keyless and goes through the shared rate-limited
client. Nothing scrapes a site that doesn't publish this deliberately.
"""

from __future__ import annotations

import logging

from app.jobs.http_client import JobSourceHTTPError, get_json

logger = logging.getLogger(__name__)

# Per-source page budget for one harvest. Modest on purpose: a scan
# already does real work, and the queue persists, so shallow-but-often
# beats one enormous crawl.
DEFAULT_PAGES_PER_SOURCE = 3
_PAGE_SIZE = 100


def _clean(name) -> str:
    return " ".join(str(name or "").split())


def harvest_himalayas(pages: int = DEFAULT_PAGES_PER_SOURCE) -> set[str]:
    """Himalayas indexes remote roles across many ATS platforms and
    exposes a keyless, cursor-paginated API."""
    names: set[str] = set()
    cursor = None
    for _ in range(max(1, pages)):
        params = {"limit": _PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        try:
            data = get_json("https://himalayas.app/jobs/api", params=params)
        except JobSourceHTTPError as exc:
            logger.info("Himalayas harvest stopped: %s", exc)
            break
        if not isinstance(data, dict):
            break
        jobs = data.get("jobs") or []
        if not jobs:
            break
        for job in jobs:
            if isinstance(job, dict):
                name = _clean(job.get("companyName"))
                if name:
                    names.add(name)
        cursor = data.get("nextCursor")
        if not cursor:
            break
    return names


def harvest_remoteok() -> set[str]:
    names: set[str] = set()
    try:
        data = get_json("https://remoteok.com/api")
    except JobSourceHTTPError as exc:
        logger.info("RemoteOK harvest stopped: %s", exc)
        return names
    if isinstance(data, list):
        for job in data:
            # The first element is a legal/metadata notice, not a job.
            if isinstance(job, dict) and job.get("company"):
                names.add(_clean(job["company"]))
    return names


def harvest_arbeitnow(pages: int = DEFAULT_PAGES_PER_SOURCE) -> set[str]:
    """Arbeitnow is Europe-heavy, which usefully offsets the US/remote
    bias of the other feeds."""
    names: set[str] = set()
    for page in range(1, max(1, pages) + 1):
        try:
            data = get_json("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        except JobSourceHTTPError as exc:
            logger.info("Arbeitnow harvest stopped: %s", exc)
            break
        if not isinstance(data, dict):
            break
        jobs = data.get("data") or []
        if not jobs:
            break
        for job in jobs:
            if isinstance(job, dict):
                name = _clean(job.get("company_name"))
                if name:
                    names.add(name)
    return names


# Broad tags rather than the user's own terms: this is about learning
# which companies exist at all, not about matching this user's roles
# (`job_search.py` already does the matching). A company found here that
# happens to be hiring for the user's field will surface through its
# board once added.
_JOBICY_TAGS = ("engineering", "data", "devops", "python", "product", "design", "marketing")


def harvest_jobicy(tags: tuple[str, ...] = _JOBICY_TAGS) -> set[str]:
    names: set[str] = set()
    for tag in tags:
        try:
            data = get_json(
                "https://jobicy.com/api/v2/remote-jobs", params={"tag": tag, "count": 50}
            )
        except JobSourceHTTPError as exc:
            logger.info("Jobicy harvest stopped on tag %r: %s", tag, exc)
            continue
        if not isinstance(data, dict):
            continue
        for job in data.get("jobs") or []:
            if isinstance(job, dict):
                name = _clean(job.get("companyName"))
                if name:
                    names.add(name)
    return names


HARVESTERS = {
    "himalayas": lambda: harvest_himalayas(),
    "remoteok": harvest_remoteok,
    "arbeitnow": lambda: harvest_arbeitnow(),
    "jobicy": lambda: harvest_jobicy(),
}


def harvest_company_names(progress_callback=None) -> dict[str, set[str]]:
    """Collects company names from every keyless aggregator.

    Returns {source_name: names}. Never raises - one feed being down or
    rate-limiting must not cost the names the others returned."""
    harvested: dict[str, set[str]] = {}
    for source_name, run in HARVESTERS.items():
        if progress_callback:
            progress_callback(f"Looking for companies on {source_name}...")
        try:
            names = run()
        except Exception:
            logger.exception("Company harvest from %s failed", source_name)
            continue
        if names:
            harvested[source_name] = names
            logger.info("Harvested %d company name(s) from %s.", len(names), source_name)
    return harvested
