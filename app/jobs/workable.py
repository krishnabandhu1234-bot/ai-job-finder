"""Workable job board public API source.

Workable publishes a read-only JSON endpoint that backs the embeddable
job-board widget companies put on their own careers pages - the same
category of public integration point as Greenhouse/Lever/Ashby, not
scraping:
    https://apply.workable.com/api/v1/widget/accounts/<slug>?details=true

Config: {"account_slug": "<company>", "company_name": "<Display Name>"}
The slug is what appears in a company's Workable URL, e.g. for
apply.workable.com/blueground the slug is "blueground".

Verified against live boards while building this connector: an unknown
slug returns HTTP 404, and a real account with no current openings
returns HTTP 200 with an empty `jobs` list - the two are distinguishable,
which is what lets `app/jobs/discovery.py` treat "resolved but empty" as
"not a usable board".
"""

from __future__ import annotations

import datetime as dt

from app.core.constants import SourceType
from app.jobs.html_text import html_to_text
from app.jobs.http_client import get_json
from app.jobs.source import JobSource, RawJobPosting


def _parse_date(value: str | None) -> dt.datetime | None:
    """Workable dates are plain "YYYY-MM-DD" (no time component), unlike
    the ISO-8601 timestamps Greenhouse/Ashby return."""
    if not value:
        return None
    try:
        return dt.datetime.strptime(value.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def _location_text(job: dict) -> str:
    """Builds a human-readable location from whichever of Workable's
    several location fields are populated. It exposes both flat
    city/state/country fields and a richer `locations` list, and real
    postings often fill only some of them (a remote US role commonly has
    country only)."""
    parts = [job.get("city"), job.get("state"), job.get("country")]
    flat = ", ".join(p.strip() for p in parts if p and p.strip())
    if flat:
        return flat
    for entry in job.get("locations") or []:
        if not isinstance(entry, dict):
            continue
        bits = [entry.get("city"), entry.get("region"), entry.get("country")]
        joined = ", ".join(b.strip() for b in bits if b and b.strip())
        if joined:
            return joined
    return ""


class WorkableSource(JobSource):
    source_type = SourceType.WORKABLE.value

    def _fetch(self) -> list[RawJobPosting]:
        account_slug = (self.config.get("account_slug") or "").strip()
        if not account_slug:
            raise ValueError("Workable source is missing an 'account_slug' in its config.")

        url = f"https://apply.workable.com/api/v1/widget/accounts/{account_slug}?details=true"
        data = get_json(url)

        # Prefer the account's own name from the API over the slug, so
        # sources added automatically by discovery show "Blueground"
        # rather than "blueground".
        company_name = self.config.get("company_name") or data.get("name") or account_slug

        postings = []
        for job in data.get("jobs", []):
            postings.append(
                RawJobPosting(
                    external_job_id=str(job.get("shortcode") or job.get("code") or ""),
                    company=company_name,
                    title=(job.get("title") or "").strip(),
                    description=html_to_text(job.get("description", "")),
                    location_raw=_location_text(job),
                    employment_type_raw=job.get("employment_type", ""),
                    posted_date=_parse_date(job.get("published_on") or job.get("created_at")),
                    apply_url=job.get("application_url") or job.get("url") or job.get("shortlink", ""),
                    company_url=f"https://apply.workable.com/{account_slug}",
                    # Workable states remoteness explicitly, which is more
                    # reliable than inferring it from location text.
                    remote_hint=bool(job.get("telecommuting")),
                    raw_source_data=job,
                )
            )
        return postings
