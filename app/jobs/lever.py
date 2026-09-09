"""Lever job postings public API source.

Lever publishes a read-only JSON API meant for embedding a company's
postings elsewhere: https://github.com/lever/postings-api

Config: {"company_slug": "<company>", "company_name": "<Display Name>"}
The slug is what appears in a company's public Lever URL, e.g. for
jobs.lever.co/acme the slug is "acme".
"""

from __future__ import annotations

from app.core.constants import SourceType
from app.jobs.html_text import html_to_text
from app.jobs.http_client import get_json
from app.jobs.normalizer import parse_epoch_millis
from app.jobs.source import JobSource, RawJobPosting


class LeverSource(JobSource):
    source_type = SourceType.LEVER.value

    def _fetch(self) -> list[RawJobPosting]:
        company_slug = (self.config.get("company_slug") or "").strip()
        if not company_slug:
            raise ValueError("Lever source is missing a 'company_slug' in its config.")

        company_name = self.config.get("company_name") or company_slug
        url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        data = get_json(url)

        postings = []
        for job in data:
            categories = job.get("categories") or {}
            description = job.get("descriptionPlain") or html_to_text(job.get("description", ""))
            requirements = [
                item.strip()
                for section in job.get("lists") or []
                if "requirement" in (section.get("text") or "").lower()
                for item in html_to_text(section.get("content", "")).split("\n")
                if item.strip()
            ]
            postings.append(
                RawJobPosting(
                    external_job_id=str(job.get("id", "")),
                    company=company_name,
                    title=(job.get("text") or "").strip(),
                    description=description,
                    requirements=requirements,
                    location_raw=categories.get("location", ""),
                    employment_type_raw=categories.get("commitment", ""),
                    posted_date=parse_epoch_millis(job.get("createdAt")),
                    apply_url=job.get("applyUrl") or job.get("hostedUrl", ""),
                    company_url=f"https://jobs.lever.co/{company_slug}",
                    raw_source_data=job,
                )
            )
        return postings
