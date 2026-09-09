"""Ashby job board public API source.

Ashby publishes a read-only JSON API meant for embedding a company's job
board elsewhere: https://developers.ashbyhq.com/reference/jobpostingapi

Config: {"board_name": "<company>", "company_name": "<Display Name>"}
The board name is what appears in a company's public Ashby URL, e.g. for
jobs.ashbyhq.com/acme the board name is "acme".
"""

from __future__ import annotations

from app.core.constants import SourceType
from app.jobs.html_text import html_to_text
from app.jobs.http_client import get_json
from app.jobs.normalizer import parse_iso_datetime
from app.jobs.source import JobSource, RawJobPosting


class AshbySource(JobSource):
    source_type = SourceType.ASHBY.value

    def _fetch(self) -> list[RawJobPosting]:
        board_name = (self.config.get("board_name") or "").strip()
        if not board_name:
            raise ValueError("Ashby source is missing a 'board_name' in its config.")

        company_name = self.config.get("company_name") or board_name
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true"
        data = get_json(url)

        postings = []
        for job in data.get("jobs", []):
            description = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml", ""))
            compensation = job.get("compensation") or {}
            salary_text = compensation.get("scrapeableCompensationSalarySummary") or ""
            postings.append(
                RawJobPosting(
                    external_job_id=str(job.get("id", "")),
                    company=company_name,
                    title=(job.get("title") or "").strip(),
                    description=description,
                    location_raw=job.get("location", ""),
                    employment_type_raw=job.get("employmentType", ""),
                    salary_raw_text=salary_text,
                    posted_date=parse_iso_datetime(job.get("publishedAt")),
                    apply_url=job.get("applyUrl") or job.get("jobUrl", ""),
                    company_url=f"https://jobs.ashbyhq.com/{board_name}",
                    remote_hint=bool(job.get("isRemote", False)),
                    raw_source_data=job,
                )
            )
        return postings
