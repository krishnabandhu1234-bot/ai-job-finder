"""A job source that searches for roles matching the user's resume,
across every company on the platforms that offer a public search API.

Every other connector answers "what is THIS company hiring for?" and so
requires already knowing the company. This one answers "who is hiring
someone like me?", which is the question the user actually has - and it
is what lets the app surface employers nobody named, including small
startups that no language model would reliably recall.

The queries themselves live in the source's `config`, refreshed from the
candidate profile by `ensure_resume_search_source()` below whenever a
scan runs. Keeping them in config (rather than having `_fetch()` reach
into the database) preserves the `JobSource` contract - a connector is
handed its configuration and does network work, nothing more - and has
the useful side effect that the Job Sources page can show exactly what
the app is searching for on the user's behalf.
"""

from __future__ import annotations

import logging

from app.core.constants import SourceType
from app.jobs.job_search import (
    DEFAULT_PAGES_PER_QUERY,
    build_search_queries,
    search_all,
    search_location_filter,
)
from app.jobs.source import JobSource, RawJobPosting

logger = logging.getLogger(__name__)

SOURCE_NAME = "Job search (matches your resume)"


class ResumeSearchSource(JobSource):
    source_type = SourceType.RESUME_SEARCH.value

    def _fetch(self) -> list[RawJobPosting]:
        queries = [q for q in (self.config.get("queries") or []) if str(q).strip()]
        if not queries:
            # Nothing to search for yet - the profile has no target roles
            # or skills. Not an error; the user just hasn't uploaded a
            # resume or filled in a title.
            logger.info("Resume search has no queries yet - skipping.")
            return []

        results = search_all(
            queries,
            location=self.config.get("location") or "",
            pages_per_query=int(self.config.get("pages_per_query") or DEFAULT_PAGES_PER_QUERY),
        )
        for error in results.errors:
            # One provider failing shouldn't fail the source - the others'
            # postings are still worth having - but it should be visible.
            logger.warning("Job search: %s", error)
        return results.postings


def ensure_resume_search_source(session, context, profile, prefs) -> tuple[object, list[str]]:
    """Creates or refreshes the resume-driven search source.

    Returns (source_row, queries). Called before each scan so the search
    always reflects the CURRENT resume and preferences - if the user
    edits their target titles, the next scan searches for the new ones
    without them having to touch anything else."""
    queries = build_search_queries(profile, prefs)
    location = search_location_filter(prefs)
    config = {
        "queries": queries,
        "location": location,
        "pages_per_query": DEFAULT_PAGES_PER_QUERY,
    }

    existing = next(
        (
            s for s in context.job_sources_repo.list_all(session)
            if s.source_type == SourceType.RESUME_SEARCH.value
        ),
        None,
    )
    if existing is None:
        existing = context.job_sources_repo.create(
            session, name=SOURCE_NAME, source_type=SourceType.RESUME_SEARCH.value, config=config
        )
        logger.info("Created resume-driven job search source with queries: %s", queries)
    else:
        existing.config = config
        logger.debug("Refreshed resume search queries: %s", queries)
    session.flush()
    return existing, queries
