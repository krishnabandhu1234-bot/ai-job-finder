"""The JobSource interface (section 4):

    JobSource
    ├── CompanyCareerPagesSource   (future)
    ├── GreenhouseSource
    ├── LeverSource
    ├── AshbySource
    ├── WorkdaySource              (future)
    ├── PublicJobAPI               (future)
    └── DemoSource

Every concrete source implements `_fetch()` and returns a list of
`RawJobPosting` - a minimally-processed, source-shaped record. Turning
that into the app's canonical `Job` DB schema (parsed salary/location,
fingerprint, ...) is `app/jobs/normalizer.py`'s job, kept separate so
adding a new source never means duplicating that logic.

`JobSource.fetch()` (not `_fetch()`) is what callers use - it NEVER
raises. A source that times out, 404s, or returns malformed data produces
a failed `SourceFetchResult` with an error message, so one broken source
never stops a scan of the others (section 4: "gracefully handle sources
that cannot be accessed").
"""

from __future__ import annotations

import datetime as dt
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RawJobPosting:
    """Source-shaped posting data, before normalization. Every field here
    maps toward a `Job` DB column (see app/jobs/normalizer.py) but is kept
    close to what the source actually returned - e.g. `location_raw` is
    whatever free-text string the source gave us, not yet split into
    city/state/country."""

    external_job_id: str
    company: str
    title: str
    description: str = ""
    requirements: list[str] = field(default_factory=list)
    preferred_qualifications: list[str] = field(default_factory=list)
    location_raw: str = ""
    employment_type_raw: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_raw_text: str = ""
    posted_date: dt.datetime | None = None
    apply_url: str = ""
    company_url: str = ""
    remote_hint: bool = False  # source explicitly flagged this as remote (e.g. Ashby's isRemote)
    raw_source_data: dict = field(default_factory=dict)


@dataclass
class SourceFetchResult:
    source_name: str
    success: bool
    postings: list[RawJobPosting] = field(default_factory=list)
    error: str | None = None

    @property
    def fetched_count(self) -> int:
        return len(self.postings)


class JobSource(ABC):
    source_type: str = "other"  # overridden by subclasses; matches app.core.constants.SourceType

    def __init__(self, name: str, config: dict | None = None):
        self.name = name
        self.config = config or {}

    @abstractmethod
    def _fetch(self) -> list[RawJobPosting]:
        """Do the actual network call(s) and return postings. May raise -
        `fetch()` below is the only method callers should use."""

    def fetch(self) -> SourceFetchResult:
        try:
            postings = self._fetch()
        except Exception as exc:  # a source must never take a scan down with it
            logger.error("Job source %r (%s) failed: %s", self.name, self.source_type, exc)
            return SourceFetchResult(source_name=self.name, success=False, error=str(exc))
        return SourceFetchResult(source_name=self.name, success=True, postings=postings)
