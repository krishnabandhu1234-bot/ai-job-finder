"""SmartRecruiters posting API source.

SmartRecruiters publishes a read-only public postings API used to embed
a company's job board elsewhere - the same category of public
integration point as Greenhouse/Lever/Ashby, not scraping:
    https://api.smartrecruiters.com/v1/companies/<slug>/postings

Config: {"company_slug": "<company>", "company_name": "<Display Name>"}
The slug appears in a company's SmartRecruiters URL, e.g. for
jobs.smartrecruiters.com/smartrecruiters the slug is "smartrecruiters".

Two API quirks this connector has to handle, both verified against the
live API while building it:

1. **The list endpoint omits the job description.** Only
   `/postings/{id}` returns the actual ad text, so getting descriptions
   means one extra request per posting. Descriptions are not optional
   here - they're the main thing the matching engine reads (skills,
   industry and semantic similarity all parse them), so a posting
   without one would score as though it were a near-empty job. The
   connector therefore does fetch details, but bounded by
   `max_detail_fetches` so one enormous board can't turn a single scan
   into thousands of requests.

2. **An unknown company slug returns HTTP 200 with zero postings**, not
   404 (unlike Workable/Greenhouse). There's no way to distinguish "no
   such company" from "company with no openings", which is exactly why
   `app/jobs/discovery.py` treats an empty board as unresolved rather
   than adding it.
"""

from __future__ import annotations

import logging

from app.core.constants import SourceType
from app.jobs.html_text import html_to_text
from app.jobs.http_client import JobSourceHTTPError, get_json
from app.jobs.normalizer import parse_iso_datetime
from app.jobs.source import JobSource, RawJobPosting

logger = logging.getLogger(__name__)

# The list endpoint pages at 100; going higher is rejected by the API.
_PAGE_SIZE = 100
# Safety rails for a single scan of one company.
DEFAULT_MAX_POSTINGS = 400
DEFAULT_MAX_DETAIL_FETCHES = 400

_API_ROOT = "https://api.smartrecruiters.com/v1/companies"

# Lines that are just a section heading repeated inside its own body -
# noise, not an actual requirement.
_SECTION_HEADING_NOISE = {
    "qualifications", "requirements", "your profile", "what you bring",
    "what we're looking for", "what we are looking for", "about you",
    "skills", "required skills", "minimum qualifications",
}


def _location_text(location: dict) -> str:
    if not isinstance(location, dict):
        return ""
    full = (location.get("fullLocation") or "").strip()
    if full:
        return full
    bits = [location.get("city"), location.get("region"), location.get("country")]
    return ", ".join(b.strip() for b in bits if b and b.strip())


def _sections_to_text(job_ad: dict) -> tuple[str, list[str]]:
    """Splits SmartRecruiters' structured ad sections into a description
    and a requirements list.

    The API helpfully separates `qualifications` from `jobDescription`,
    which maps directly onto this app's `description`/`requirements`
    split - better signal than other boards give us, since the skill
    matcher weights stated requirements specifically."""
    sections = (job_ad or {}).get("sections") or {}

    def text_of(key: str) -> str:
        section = sections.get(key)
        if not isinstance(section, dict):
            return ""
        return html_to_text(section.get("text", ""))

    description_parts = [text_of("jobDescription"), text_of("companyDescription")]
    description = "\n\n".join(part for part in description_parts if part)

    requirements = []
    for line in text_of("qualifications").split("\n"):
        line = line.strip()
        if not line:
            continue
        # Real ads usually repeat the section name as the first line of
        # its own body ("<strong>Qualifications</strong>"), which would
        # otherwise be stored as a requirement and matched against as if
        # it were a skill.
        if line.rstrip(":").casefold() in _SECTION_HEADING_NOISE:
            continue
        requirements.append(line)
    return description, requirements


class SmartRecruitersSource(JobSource):
    source_type = SourceType.SMARTRECRUITERS.value

    def _fetch(self) -> list[RawJobPosting]:
        company_slug = (self.config.get("company_slug") or "").strip()
        if not company_slug:
            raise ValueError("SmartRecruiters source is missing a 'company_slug' in its config.")

        max_postings = int(self.config.get("max_postings") or DEFAULT_MAX_POSTINGS)
        max_details = int(self.config.get("max_detail_fetches") or DEFAULT_MAX_DETAIL_FETCHES)

        summaries = self._fetch_summaries(company_slug, max_postings)
        company_name = self.config.get("company_name") or self._company_name(summaries) or company_slug

        postings = []
        for index, summary in enumerate(summaries):
            posting_id = str(summary.get("id") or "")
            description, requirements, apply_url = "", [], ""

            if posting_id and index < max_details:
                detail = self._fetch_detail(company_slug, posting_id)
                if detail is not None:
                    description, requirements = _sections_to_text(detail.get("jobAd") or {})
                    apply_url = detail.get("applyUrl") or detail.get("postingUrl") or ""

            location = summary.get("location") or {}
            postings.append(
                RawJobPosting(
                    external_job_id=posting_id,
                    company=company_name,
                    title=(summary.get("name") or "").strip(),
                    description=description,
                    requirements=requirements,
                    location_raw=_location_text(location),
                    employment_type_raw=(summary.get("typeOfEmployment") or {}).get("label", ""),
                    posted_date=parse_iso_datetime(summary.get("releasedDate")),
                    apply_url=apply_url,
                    company_url=f"https://jobs.smartrecruiters.com/{company_slug}",
                    remote_hint=bool(location.get("remote")),
                    raw_source_data=summary,
                )
            )
        return postings

    def _fetch_summaries(self, company_slug: str, max_postings: int) -> list[dict]:
        summaries: list[dict] = []
        offset = 0
        while len(summaries) < max_postings:
            url = f"{_API_ROOT}/{company_slug}/postings?limit={_PAGE_SIZE}&offset={offset}"
            data = get_json(url)
            page = data.get("content") if isinstance(data, dict) else None
            if not page:
                break
            summaries.extend(page)
            offset += len(page)
            if offset >= int(data.get("totalFound") or 0):
                break
        return summaries[:max_postings]

    def _fetch_detail(self, company_slug: str, posting_id: str) -> dict | None:
        """One posting's full ad. A single failure here must not fail the
        whole source - the posting is still worth keeping with its title
        and location, just with a weaker description."""
        try:
            return get_json(f"{_API_ROOT}/{company_slug}/postings/{posting_id}")
        except JobSourceHTTPError as exc:
            logger.info("SmartRecruiters detail fetch failed for posting %s: %s", posting_id, exc)
            return None

    @staticmethod
    def _company_name(summaries: list[dict]) -> str:
        for summary in summaries:
            name = (summary.get("company") or {}).get("name")
            if name:
                return name
        return ""
