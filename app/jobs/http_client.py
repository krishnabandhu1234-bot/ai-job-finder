"""Shared, rate-limited HTTP client for job source connectors.

Every outbound request from this app for job data goes through here so
there's exactly one place that enforces:
  - a descriptive User-Agent (so a company can identify and, if they ever
    want to, contact/block this traffic - never spoof a browser UA),
  - a minimum interval between requests to the same host, which widens
    automatically for any host that answers 429 and eases back once it
    stops (see `_MIN_INTERVAL_SECONDS` / `_widen_interval`),
  - bounded retries with backoff for transient failures (timeouts, 5xx,
    429) and NO retries for permanent failures (404, 401, ...), and
  - a hard timeout, so one slow/unresponsive source can't hang a scan.

This module only talks to the public JSON APIs that Greenhouse/Lever/
Ashby publish specifically for embedding job boards elsewhere - it does
not scrape HTML, bypass auth, or work around robots.txt/CAPTCHAs. A
future CompanyCareerPagesSource that fetches HTML directly should check
robots.txt (see `is_allowed_by_robots`) before every request.
"""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

USER_AGENT = (
    "AIJobFinderBot/0.1 (+personal job-search assistant; "
    "single user, low volume; respects robots.txt and rate limits)"
)

DEFAULT_TIMEOUT_SECONDS = 15.0
_MIN_INTERVAL_SECONDS = 1.0
# A host that starts returning 429 gets progressively more room, up to
# this. Discovery probes many companies across a handful of ATS hosts, so
# without this one busy host (apply.workable.com in practice) spends the
# whole run being retried into the same 429.
_MAX_INTERVAL_SECONDS = 30.0
_BACKOFF_FACTOR = 2.0
# Recovery is deliberately far slower than backoff: getting rate limited
# again is much more expensive than a few extra seconds of politeness.
_RECOVERY_FACTOR = 0.9

_lock = threading.Lock()
# The earliest monotonic time the next request to a host may start. This
# is a *reservation* rather than a record of the last request, so several
# threads can queue against the same host without any of them needing to
# hold the lock while they wait.
_next_allowed_at: dict[str, float] = {}
_host_intervals: dict[str, float] = {}
_robots_cache: dict[str, RobotFileParser] = {}


def reset_throttle_state() -> None:
    """Forgets all pacing. For tests; never needed in production."""
    with _lock:
        _next_allowed_at.clear()
        _host_intervals.clear()


class JobSourceHTTPError(Exception):
    """Raised when a request to a job source ultimately fails (after any
    retries). Callers (JobSource subclasses) should let this propagate -
    the base JobSource.fetch() wrapper turns it into a failed
    SourceFetchResult rather than crashing the scan."""


def _throttle(host: str) -> None:
    """Waits until this host's next slot, then claims it.

    The slot is reserved under the lock but the waiting happens outside
    it. That matters as soon as anything runs requests concurrently:
    sleeping while holding a global lock would let one slow or
    rate-limited host stall requests to every *other* host too, which is
    exactly the traffic that should have been proceeding in parallel."""
    with _lock:
        interval = _host_intervals.get(host, _MIN_INTERVAL_SECONDS)
        now = time.monotonic()
        start_at = max(now, _next_allowed_at.get(host, 0.0))
        _next_allowed_at[host] = start_at + interval

    wait = start_at - now
    if wait > 0:
        time.sleep(wait)


def _widen_interval(host: str, retry_after: float | None) -> float:
    """Gives a host that just rate-limited us more room, and returns the
    new interval."""
    with _lock:
        current = _host_intervals.get(host, _MIN_INTERVAL_SECONDS)
        widened = max(current * _BACKOFF_FACTOR, retry_after or 0.0)
        interval = min(widened, _MAX_INTERVAL_SECONDS)
        _host_intervals[host] = interval
        # Push the next slot out too, so the retry doesn't go straight
        # back at a host that just asked us to slow down.
        _next_allowed_at[host] = max(_next_allowed_at.get(host, 0.0), time.monotonic() + interval)
    return interval


def _narrow_interval(host: str) -> None:
    """Eases a previously rate-limited host back toward normal pacing."""
    with _lock:
        current = _host_intervals.get(host)
        if current is not None and current > _MIN_INTERVAL_SECONDS:
            _host_intervals[host] = max(_MIN_INTERVAL_SECONDS, current * _RECOVERY_FACTOR)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


# Test-only seam: set to an httpx.MockTransport in tests so retry/throttle
# behavior can be exercised deterministically without real network calls.
# Left as None (real network) in production.
_transport_override: httpx.BaseTransport | None = None


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_is_retryable),
)
def _request(method: str, url: str, timeout: float, **kwargs) -> httpx.Response:
    host = urlparse(url).netloc
    _throttle(host)
    with httpx.Client(
        timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True,
        transport=_transport_override,
    ) as client:
        response = client.request(method, url, **kwargs)
        if response.status_code == 429:
            header = response.headers.get("Retry-After", "")
            interval = _widen_interval(host, float(header) if header.isdigit() else None)
            # Raising rather than sleeping here lets the throttle above do
            # the waiting on the retry, which keeps all the pacing in one
            # place and stops this thread blocking on a host it isn't
            # even going to talk to until later.
            logger.warning(
                "Rate limited by %s - spacing its requests %.1fs apart from now on", host, interval
            )
        elif response.is_success:
            _narrow_interval(host)
        response.raise_for_status()
        return response


def get_json(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS, **kwargs):
    try:
        response = _request("GET", url, timeout, **kwargs)
        return response.json()
    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
        raise JobSourceHTTPError(f"Failed to fetch {url}: {exc}") from exc


def get_text(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS, **kwargs) -> str:
    try:
        response = _request("GET", url, timeout, **kwargs)
        return response.text
    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
        raise JobSourceHTTPError(f"Failed to fetch {url}: {exc}") from exc


def is_allowed_by_robots(url: str, timeout: float = 5.0) -> bool:
    """Checks robots.txt for `url` against our User-Agent. Fails OPEN
    (returns True) if robots.txt can't be fetched/parsed at all - most
    sites have no robots.txt, and treating "unreachable" the same as
    "disallowed" would make the app unable to use sites that simply don't
    publish one. Used by any future HTML-scraping source (company career
    pages); the Greenhouse/Lever/Ashby JSON API sources are deliberately
    public integration endpoints and are exempt from this check the same
    way a browser widget embedding a job board would be."""
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    parser = _robots_cache.get(root)
    if parser is None:
        parser = RobotFileParser()
        parser.set_url(f"{root}/robots.txt")
        try:
            text = get_text(f"{root}/robots.txt", timeout=timeout)
            parser.parse(text.splitlines())
        except JobSourceHTTPError:
            logger.info("No robots.txt found at %s (or it could not be fetched) - allowing.", root)
            parser.parse([])  # empty ruleset = allow everything
        _robots_cache[root] = parser
    return parser.can_fetch(USER_AGENT, url)
