"""Greenhouse job board public API source.

Greenhouse publishes a read-only JSON API specifically meant for
embedding a company's job board elsewhere - this is exactly that
integration point, not scraping:
https://developers.greenhouse.io/job-board.html

Config: {"board_token": "<company>", "company_name": "<Display Name>"}
The board token is the slug in a company's public Greenhouse URL, e.g.
for boards.greenhouse.io/acme the token is "acme".
"""

from __future__ import annotations

from app.core.constants import SourceType
from app.jobs.html_text import html_to_text
from app.jobs.http_client import get_json
from app.jobs.normalizer import parse_iso_datetime
from app.jobs.source import JobSource, RawJobPosting


class GreenhouseSource(JobSource):
    source_type = SourceType.GREENHOUSE.value

    def _fetch(self) -> list[RawJobPosting]:
        board_token = (self.config.get("board_token") or "").strip()
        if not board_token:
            raise ValueError("Greenhouse source is missing a 'board_token' in its config.")

        company_name = self.config.get("company_name") or board_token
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        data = get_json(url)

        postings = []
        for job in data.get("jobs", []):
            location = (job.get("location") or {}).get("name", "")
            postings.append(
                RawJobPosting(
                    external_job_id=str(job.get("id", "")),
                    company=company_name,
                    title=(job.get("title") or "").strip(),
                    description=html_to_text(job.get("content", "")),
                    location_raw=location,
                    posted_date=parse_iso_datetime(job.get("updated_at")),
                    apply_url=job.get("absolute_url", ""),
                    company_url=f"https://boards.greenhouse.io/{board_token}",
                    raw_source_data=job,
                )
            )
        return postings
