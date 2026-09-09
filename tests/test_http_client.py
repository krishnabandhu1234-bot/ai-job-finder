"""Tests for the shared job-source HTTP client: retry/backoff behavior,
never retrying permanent (4xx, non-429) failures, and the robots.txt
fail-open behavior. All network calls go through an injected
httpx.MockTransport - section 27 ("do not require real APIs to run the
test suite") applies to job-source HTTP just as much as resume parsing.
"""

from __future__ import annotations

import time

import httpx
import pytest

from app.jobs import http_client


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """tenacity's wait_exponential and our own throttle/429 handling both
    call time.sleep() - patch it globally so retry tests run instantly
    instead of taking real seconds."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)


@pytest.fixture(autouse=True)
def _reset_state():
    http_client.reset_throttle_state()
    http_client._robots_cache.clear()
    yield
    http_client._transport_override = None


def _install_transport(monkeypatch, handler):
    monkeypatch.setattr(http_client, "_transport_override", httpx.MockTransport(handler))


def test_get_json_returns_parsed_body_on_success(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jobs": []})

    _install_transport(monkeypatch, handler)
    assert http_client.get_json("https://example.com/jobs") == {"jobs": []}


def test_get_json_sends_descriptive_user_agent(monkeypatch):
    seen = {}

    def handler(request):
        seen["user_agent"] = request.headers.get("user-agent", "")
        return httpx.Response(200, json={})

    _install_transport(monkeypatch, handler)
    http_client.get_json("https://example.com/jobs")

    assert "AIJobFinderBot" in seen["user_agent"]


def test_get_json_retries_on_500_then_succeeds(monkeypatch):
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    _install_transport(monkeypatch, handler)
    result = http_client.get_json("https://example.com/jobs")

    assert result == {"ok": True}
    assert attempts["count"] == 3


def test_get_json_gives_up_after_max_retries_on_persistent_500(monkeypatch):
    def handler(request):
        return httpx.Response(500)

    _install_transport(monkeypatch, handler)

    with pytest.raises(http_client.JobSourceHTTPError):
        http_client.get_json("https://example.com/jobs")


def test_get_json_does_not_retry_on_404(monkeypatch):
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)

    with pytest.raises(http_client.JobSourceHTTPError):
        http_client.get_json("https://example.com/does-not-exist")

    assert attempts["count"] == 1  # a permanent client error should not be retried


def test_get_json_respects_retry_after_on_429(monkeypatch):
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"ok": True})

    _install_transport(monkeypatch, handler)
    result = http_client.get_json("https://example.com/jobs")

    assert result == {"ok": True}
    assert attempts["count"] == 2


def test_is_allowed_by_robots_fails_open_when_robots_txt_missing(monkeypatch):
    def handler(request):
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)
    assert http_client.is_allowed_by_robots("https://example.com/careers/job/1") is True


def test_is_allowed_by_robots_respects_disallow(monkeypatch):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, text="ok")

    _install_transport(monkeypatch, handler)

    assert http_client.is_allowed_by_robots("https://example.com/careers/job/1") is True
    assert http_client.is_allowed_by_robots("https://example.com/private/secret") is False


# ---------------------------------------------------------------------------
# Adaptive per-host pacing
#
# Discovery probes hundreds of companies across a handful of ATS hosts, so
# how the client reacts to a host pushing back decides whether a run makes
# progress or spends itself being retried into the same 429.
# ---------------------------------------------------------------------------

def test_a_rate_limited_host_gets_progressively_more_room(monkeypatch):
    _install_transport(monkeypatch, lambda r: httpx.Response(429))

    with pytest.raises(Exception):
        http_client.get_json("https://busy.example.com/jobs")

    # Backed off well past the default, but never unboundedly.
    interval = http_client._host_intervals["busy.example.com"]
    assert interval > http_client._MIN_INTERVAL_SECONDS
    assert interval <= http_client._MAX_INTERVAL_SECONDS


def test_backoff_honours_an_explicit_retry_after(monkeypatch):
    _install_transport(
        monkeypatch, lambda r: httpx.Response(429, headers={"Retry-After": "12"})
    )

    with pytest.raises(Exception):
        http_client.get_json("https://busy.example.com/jobs")

    assert http_client._host_intervals["busy.example.com"] >= 12


def test_backoff_is_per_host_not_global(monkeypatch):
    """One busy ATS must not slow the app's requests to the other four -
    that would make the whole discovery run as slow as its worst host."""
    def handler(request):
        if request.url.host == "busy.example.com":
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    _install_transport(monkeypatch, handler)
    with pytest.raises(Exception):
        http_client.get_json("https://busy.example.com/jobs")
    http_client.get_json("https://calm.example.com/jobs")

    assert http_client._host_intervals["busy.example.com"] > http_client._MIN_INTERVAL_SECONDS
    assert "calm.example.com" not in http_client._host_intervals


def test_a_host_that_recovers_is_eased_back_toward_normal(monkeypatch):
    """Otherwise a single transient 429 would leave that host crawling for
    the rest of the session."""
    state = {"limited": True}

    def handler(request):
        if state["limited"]:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    _install_transport(monkeypatch, handler)
    with pytest.raises(Exception):
        http_client.get_json("https://busy.example.com/jobs")
    widened = http_client._host_intervals["busy.example.com"]

    state["limited"] = False
    http_client.get_json("https://busy.example.com/jobs")

    assert http_client._host_intervals["busy.example.com"] < widened


def test_throttle_does_not_hold_the_lock_while_waiting():
    """The lock is global, so sleeping under it would serialise every
    host against every other one and cancel out any concurrency."""
    import threading

    http_client._next_allowed_at["slow.example.com"] = time.monotonic() + 30
    held = []

    def check_lock_is_free():
        held.append(http_client._lock.acquire(timeout=2))
        if held[-1]:
            http_client._lock.release()

    real_sleep = time.sleep
    try:
        time.sleep = lambda _s: check_lock_is_free()
        http_client._throttle("slow.example.com")
    finally:
        time.sleep = real_sleep

    assert held == [True], "the throttle slept while holding the global lock"
