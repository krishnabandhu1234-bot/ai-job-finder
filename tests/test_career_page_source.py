"""Tests for CompanyCareerPageSource (app/jobs/career_page_source.py) -
the "any company career page URL" job source.

All HTTP goes through the mocked transport (section 27: no real network
in the suite). The headless-render fallback and the LLM extraction call
are both isolated, swappable functions specifically so they can be
exercised here without a real browser or a real AI provider.
"""

from __future__ import annotations

import httpx
import pytest

from app.jobs import career_page_source as cps_module
from app.jobs import http_client
from app.jobs.career_page_source import (
    BrowserAgentConfig,
    CompanyCareerPageSource,
    _extract_candidate_links,
    _looks_like_job_link,
    _parse_ai_jobs,
    _stable_id,
    fetch_job_descriptions,
    resolve_browser_agent_config,
)


# ---------------------------------------------------------------------------
# The no-AI structural heuristic
# ---------------------------------------------------------------------------

def test_looks_like_job_link_matches_common_url_patterns():
    for href in [
        "/careers/senior-engineer",
        "/jobs/123",
        "https://example.com/job/backend-dev",
        "/positions/data-scientist",
        "/openings/pm-role",
        "/careers-req-4821",
    ]:
        assert _looks_like_job_link(href), href


def test_looks_like_job_link_rejects_navigation_links():
    for href in ["/about", "/contact", "#top", "mailto:hr@example.com", "javascript:void(0)", ""]:
        assert not _looks_like_job_link(href), href


def test_extract_candidate_links_finds_job_postings_and_ignores_nav():
    html = """
    <html><body>
      <nav><a href="/about">About</a><a href="/contact">Contact</a></nav>
      <ul>
        <li><a href="/careers/senior-backend-engineer">Senior Backend Engineer</a></li>
        <li><a href="/careers/product-designer">Product Designer</a></li>
      </ul>
    </body></html>
    """
    candidates = _extract_candidate_links(html, "https://acme.example.com")

    assert {c["title"] for c in candidates} == {"Senior Backend Engineer", "Product Designer"}
    assert all(c["url"].startswith("https://acme.example.com/careers/") for c in candidates)


def test_extract_candidate_links_deduplicates_and_resolves_relative_urls():
    html = """
    <a href="/jobs/1">Engineer</a>
    <a href="/jobs/1">Engineer</a>
    <a href="jobs/2">Designer</a>
    """
    candidates = _extract_candidate_links(html, "https://acme.example.com/careers")

    urls = {c["url"] for c in candidates}
    assert urls == {"https://acme.example.com/jobs/1", "https://acme.example.com/jobs/2"}


def test_extract_candidate_links_skips_links_with_no_or_huge_text():
    html = """
    <a href="/jobs/1"></a>
    <a href="/jobs/2">""" + ("x" * 300) + """</a>
    <a href="/jobs/3">Real Job Title</a>
    """
    candidates = _extract_candidate_links(html, "https://acme.example.com")

    assert [c["title"] for c in candidates] == ["Real Job Title"]


# ---------------------------------------------------------------------------
# AI-assisted extraction (parsing only - the LLM call itself is mocked)
# ---------------------------------------------------------------------------

def test_parse_ai_jobs_reads_a_clean_response():
    raw = '{"jobs": [{"title": "Backend Engineer", "url": "https://acme.example.com/j/1", "location": "Remote"}]}'
    jobs = _parse_ai_jobs(raw)
    assert jobs == [{"title": "Backend Engineer", "url": "https://acme.example.com/j/1", "location": "Remote"}]


def test_parse_ai_jobs_handles_markdown_fenced_response():
    raw = '```json\n{"jobs": [{"title": "PM", "url": "", "location": ""}]}\n```'
    jobs = _parse_ai_jobs(raw)
    assert jobs == [{"title": "PM", "url": "", "location": ""}]


def test_parse_ai_jobs_returns_empty_list_for_a_page_with_no_openings():
    assert _parse_ai_jobs('{"jobs": []}') == []


def test_parse_ai_jobs_returns_none_for_garbage():
    assert _parse_ai_jobs("not json at all") is None


def test_parse_ai_jobs_drops_entries_with_no_title():
    raw = '{"jobs": [{"title": "", "url": "x"}, {"title": "Real Role", "url": "y"}]}'
    jobs = _parse_ai_jobs(raw)
    assert [j["title"] for j in jobs] == ["Real Role"]


def test_stable_id_is_deterministic_and_distinct():
    a = _stable_id("https://acme.example.com/jobs/1")
    b = _stable_id("https://acme.example.com/jobs/1")
    c = _stable_id("https://acme.example.com/jobs/2")
    assert a == b
    assert a != c


# ---------------------------------------------------------------------------
# The headless-render fallback - isolated, never touches a real browser
# ---------------------------------------------------------------------------

def test_render_with_playwright_returns_none_when_not_installed(monkeypatch):
    """playwright is an optional dependency (see requirements.txt) - its
    absence must degrade this one fallback step, never crash the
    source."""
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "playwright.sync_api" or name.startswith("playwright"):
            raise ImportError("no module named playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    assert cps_module.render_with_playwright("https://acme.example.com/careers") is None


# ---------------------------------------------------------------------------
# The full source: heuristic-only path (no AI configured)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_http(monkeypatch):
    http_client.reset_throttle_state()
    http_client._robots_cache.clear()
    yield


def _install_transport(monkeypatch, handler):
    monkeypatch.setattr(http_client, "_transport_override", httpx.MockTransport(handler))


def test_source_extracts_postings_from_static_html_with_no_ai(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            text=(
                '<html><body><ul>'
                '<li><a href="/careers/engineer">Software Engineer</a></li>'
                '<li><a href="/careers/designer">Product Designer</a></li>'
                '</ul></body></html>'
            ),
        )

    _install_transport(monkeypatch, handler)
    source = CompanyCareerPageSource(
        name="Acme Careers", config={"url": "https://acme.example.com/careers", "company_name": "Acme"}
    )

    result = source.fetch()

    assert result.success
    titles = {p.title for p in result.postings}
    assert titles == {"Software Engineer", "Product Designer"}
    assert all(p.company == "Acme" for p in result.postings)


def test_source_respects_robots_disallow(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /careers\n")
        return httpx.Response(200, text="<html></html>")

    _install_transport(monkeypatch, handler)
    source = CompanyCareerPageSource(name="Acme", config={"url": "https://acme.example.com/careers"})

    result = source.fetch()

    assert not result.success
    assert "robots.txt" in result.error


def test_source_requires_a_url_in_config():
    source = CompanyCareerPageSource(name="Acme", config={})
    result = source.fetch()
    assert not result.success
    assert "url" in result.error


def test_source_falls_back_to_headless_render_when_static_html_has_too_few_links(monkeypatch):
    """A page whose job list is drawn in by client-side JS looks, to a
    plain GET, like it has no jobs at all - that's exactly when the
    (mocked, here) headless-render fallback should kick in."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        # The "static" page has no job links - a JS-only SPA shell.
        return httpx.Response(200, text="<html><body><div id='app'></div></body></html>")

    _install_transport(monkeypatch, handler)

    rendered_html = (
        '<html><body><a href="/jobs/1">Rendered Engineer Role</a></body></html>'
    )
    monkeypatch.setattr(cps_module, "render_with_playwright", lambda url, **kw: rendered_html)

    source = CompanyCareerPageSource(name="Acme", config={"url": "https://acme.example.com/careers"})
    result = source.fetch()

    assert result.success
    assert [p.title for p in result.postings] == ["Rendered Engineer Role"]


def test_source_does_not_bother_rendering_when_static_html_already_has_postings(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            text=(
                '<a href="/jobs/1">Engineer One</a>'
                '<a href="/jobs/2">Engineer Two</a>'
                '<a href="/jobs/3">Engineer Three</a>'
            ),
        )

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(
        cps_module, "render_with_playwright",
        lambda url, **kw: pytest.fail("should not render when the static page already has postings"),
    )

    source = CompanyCareerPageSource(name="Acme", config={"url": "https://acme.example.com/careers"})
    result = source.fetch()

    assert result.success
    assert result.fetched_count == 3


# ---------------------------------------------------------------------------
# The full source: AI-assisted path
# ---------------------------------------------------------------------------

class _FakeUsableAIConfig:
    def has_usable_llm(self) -> bool:
        return True


class _FakeUnusableAIConfig:
    def has_usable_llm(self) -> bool:
        return False


def test_source_prefers_ai_extraction_when_a_provider_is_configured(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text='<a href="/careers/eng">Some Link Text</a>')

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(
        cps_module, "ai_extract_postings",
        lambda ai_config, company_name, url, html: [
            {"title": "AI-Read Senior Engineer", "url": "https://acme.example.com/j/99", "location": "Remote"}
        ],
    )

    source = CompanyCareerPageSource(
        name="Acme", config={"url": "https://acme.example.com/careers", "company_name": "Acme"},
        ai_config=_FakeUsableAIConfig(),
    )
    result = source.fetch()

    assert result.success
    assert [p.title for p in result.postings] == ["AI-Read Senior Engineer"]
    assert result.postings[0].location_raw == "Remote"


def test_source_falls_back_to_heuristic_when_ai_extraction_fails(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text='<a href="/careers/eng">Heuristic Engineer</a>')

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(
        cps_module, "ai_extract_postings",
        lambda ai_config, company_name, url, html: None,  # provider call failed
    )

    source = CompanyCareerPageSource(
        name="Acme", config={"url": "https://acme.example.com/careers"}, ai_config=_FakeUsableAIConfig()
    )
    result = source.fetch()

    assert result.success
    assert [p.title for p in result.postings] == ["Heuristic Engineer"]


def test_ai_extract_postings_returns_none_without_a_usable_provider():
    assert cps_module.ai_extract_postings(None, "Acme", "https://x", "<html></html>") is None
    assert (
        cps_module.ai_extract_postings(_FakeUnusableAIConfig(), "Acme", "https://x", "<html></html>")
        is None
    )


# ---------------------------------------------------------------------------
# Description backfill - each posting gets its own page's text
# ---------------------------------------------------------------------------

def test_fetch_job_descriptions_pulls_text_per_url(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"<p>Description for {request.url.path}</p>")

    _install_transport(monkeypatch, handler)

    descriptions = fetch_job_descriptions(
        ["https://acme.example.com/jobs/1", "https://acme.example.com/jobs/2"]
    )

    assert "Description for /jobs/1" in descriptions["https://acme.example.com/jobs/1"]
    assert "Description for /jobs/2" in descriptions["https://acme.example.com/jobs/2"]


def test_fetch_job_descriptions_one_failure_does_not_cost_the_others(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jobs/broken":
            return httpx.Response(500)
        return httpx.Response(200, text="<p>Fine</p>")

    _install_transport(monkeypatch, handler)

    descriptions = fetch_job_descriptions(
        ["https://acme.example.com/jobs/broken", "https://acme.example.com/jobs/ok"]
    )

    assert "https://acme.example.com/jobs/broken" not in descriptions
    assert "Fine" in descriptions["https://acme.example.com/jobs/ok"]


def test_fetch_job_descriptions_respects_the_cap(monkeypatch):
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, text="ok")

    _install_transport(monkeypatch, handler)
    urls = [f"https://acme.example.com/jobs/{i}" for i in range(10)]

    fetch_job_descriptions(urls, cap=3)

    assert len(requested) == 3


# ---------------------------------------------------------------------------
# Browser-agent config (the user's own browser, opt-in)
# ---------------------------------------------------------------------------

def test_browser_agent_config_is_unusable_when_disabled():
    assert not BrowserAgentConfig(enabled=False, cdp_url="http://localhost:9222").usable()


def test_browser_agent_config_is_unusable_without_a_cdp_url():
    assert not BrowserAgentConfig(enabled=True, cdp_url="").usable()
    assert not BrowserAgentConfig(enabled=True, cdp_url="   ").usable()


def test_browser_agent_config_usable_when_enabled_with_an_address():
    assert BrowserAgentConfig(enabled=True, cdp_url="http://localhost:9222").usable()


def test_resolve_browser_agent_config_defaults_to_disabled(db_session, app_context):
    config = resolve_browser_agent_config(db_session, app_context)
    assert config.enabled is False
    assert config.cdp_url == cps_module.DEFAULT_CDP_URL


def test_resolve_browser_agent_config_reads_saved_settings(db_session, app_context):
    app_context.settings_repo.set(db_session, cps_module.SETTING_BROWSER_AGENT_ENABLED, "true")
    app_context.settings_repo.set(
        db_session, cps_module.SETTING_BROWSER_AGENT_CDP_URL, "http://localhost:9333"
    )
    db_session.commit()

    config = resolve_browser_agent_config(db_session, app_context)

    assert config.enabled is True
    assert config.cdp_url == "http://localhost:9333"


def test_render_with_users_browser_returns_none_when_not_installed(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("no module named playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    assert cps_module.render_with_users_browser("https://acme.example.com/careers", "http://localhost:9222") is None


# ---------------------------------------------------------------------------
# The full source: the user's-browser tier and description backfill
# ---------------------------------------------------------------------------

def test_source_does_not_try_the_users_browser_when_it_is_not_enabled(monkeypatch):
    """The default, off, config - nothing should even attempt to attach,
    regardless of how little the earlier tiers found."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html><body>no jobs here</body></html>")

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(cps_module, "render_with_playwright", lambda url, **kw: None)
    monkeypatch.setattr(
        cps_module, "render_with_users_browser",
        lambda *a, **kw: pytest.fail("must not attach to the user's browser when disabled"),
    )

    source = CompanyCareerPageSource(
        name="Acme", config={"url": "https://acme.example.com/careers"},
        browser_config=BrowserAgentConfig(enabled=False),
    )
    result = source.fetch()

    assert result.success
    assert result.fetched_count == 0


def test_source_falls_back_to_the_users_browser_as_a_last_resort(monkeypatch):
    """Both the static fetch AND the invisible-browser render come up
    empty (e.g. the site blocks anonymous headless clients) - only then
    does the user's own, opted-in browser get tried."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html><body>blocked / empty shell</body></html>")

    _install_transport(monkeypatch, handler)
    monkeypatch.setattr(cps_module, "render_with_playwright", lambda url, **kw: None)

    calls = []

    def _fake_users_browser(url, cdp_url, **kw):
        calls.append((url, cdp_url))
        return '<a href="/jobs/1">Found Via Your Browser</a>'

    monkeypatch.setattr(cps_module, "render_with_users_browser", _fake_users_browser)

    source = CompanyCareerPageSource(
        name="Acme", config={"url": "https://acme.example.com/careers"},
        browser_config=BrowserAgentConfig(enabled=True, cdp_url="http://localhost:9222"),
    )
    result = source.fetch()

    assert result.success
    assert [p.title for p in result.postings] == ["Found Via Your Browser"]
    assert calls == [("https://acme.example.com/careers", "http://localhost:9222")]


def test_source_backfills_real_descriptions_for_heuristic_postings(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/careers":
            return httpx.Response(200, text='<a href="/jobs/1">Engineer</a>')
        if request.url.path == "/jobs/1":
            return httpx.Response(200, text="<p>We need someone who knows Python.</p>")
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)
    source = CompanyCareerPageSource(name="Acme", config={"url": "https://acme.example.com/careers"})

    result = source.fetch()

    assert result.success
    assert "knows Python" in result.postings[0].description
