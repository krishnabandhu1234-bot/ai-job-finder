"""Tests for automatic company discovery (`app/jobs/discovery.py`).

No test here touches the network or a real LLM: the LLM call and the
three ATS probe functions are the two seams, and both are stubbed.
"""

from __future__ import annotations

import json

import pytest

from app.ai.embeddings import AIRuntimeConfig
from app.jobs import discovery as discovery_module
from app.jobs.discovery import (
    CompanySuggestion,
    ResolvedBoard,
    _parse_suggestions,
    candidate_slugs,
    discover_and_add_sources,
    resolve_company_board,
    suggest_companies,
)
from app.jobs.http_client import JobSourceHTTPError


def _ai_config(**overrides) -> AIRuntimeConfig:
    base = dict(
        local_only=False, embedding_provider="local", embedding_model="all-MiniLM-L6-v2",
        llm_provider="anthropic", llm_model="claude-sonnet-5",
        anthropic_api_key="sk-test", openai_api_key="", voyage_api_key="",
    )
    base.update(overrides)
    return AIRuntimeConfig(**base)


def _seed_profile(session, app_context, **overrides):
    user = app_context.users_repo.get_or_create_default_user(session, "test@example.com")
    profile = app_context.candidate_profile_repo.get_current(session, user.id)
    fields = dict(
        target_roles=["CFD Engineer"], seniority="senior", years_experience=8.0,
        technical_skills=["CFD"], programming_languages=["Python"],
    )
    fields.update(overrides)
    app_context.candidate_profile_repo.save(session, profile, **fields)
    return profile


# --------------------------------------------------------------------------
# Slug generation
# --------------------------------------------------------------------------

def test_candidate_slugs_covers_common_ats_spellings():
    slugs = candidate_slugs("Acme Robotics")
    assert "acmerobotics" in slugs
    assert "acme-robotics" in slugs
    assert "acme" in slugs  # many boards use just the distinctive first word


def test_candidate_slugs_strips_legal_suffixes_and_punctuation():
    assert candidate_slugs("Acme, Inc.")[0] == "acme"
    assert candidate_slugs("O'Reilly Media")[0] == "oreillymedia"


def test_candidate_slugs_single_word_company_is_one_guess():
    assert candidate_slugs("Stripe") == ["stripe"]


def test_candidate_slugs_handles_junk_input():
    assert candidate_slugs("") == []
    assert candidate_slugs("   ") == []
    assert candidate_slugs("!!!") == []


# --------------------------------------------------------------------------
# LLM suggestion parsing
# --------------------------------------------------------------------------

def test_parse_suggestions_reads_valid_json():
    raw = '{"companies": [{"name": "Acme", "reason": "does CFD work"}, {"name": "Globex"}]}'
    suggestions = _parse_suggestions(raw)
    assert [s.name for s in suggestions] == ["Acme", "Globex"]
    assert suggestions[0].reason == "does CFD work"


def test_parse_suggestions_strips_markdown_fence():
    raw = '```json\n{"companies": [{"name": "Acme"}]}\n```'
    assert [s.name for s in _parse_suggestions(raw)] == ["Acme"]


def test_parse_suggestions_deduplicates_case_insensitively():
    raw = '{"companies": [{"name": "Acme"}, {"name": "ACME"}, {"name": "Globex"}]}'
    assert [s.name for s in _parse_suggestions(raw)] == ["Acme", "Globex"]


def test_parse_suggestions_survives_garbage():
    assert _parse_suggestions("not json") == []
    assert _parse_suggestions("[]") == []
    assert _parse_suggestions('{"companies": ["just a string"]}') == []


def test_suggest_companies_returns_nothing_without_a_configured_llm():
    config = _ai_config(llm_provider="none")

    class _Profile:
        target_roles = ["CFD Engineer"]

    assert suggest_companies(config, _Profile()) == []


def test_large_requests_are_split_into_several_smaller_calls(db_session, app_context, monkeypatch):
    """Asking a model for 100 companies in one response produces a worse
    list than several smaller asks - the tail drifts to famous-name
    filler and the reply can be truncated into invalid JSON."""
    calls = []

    def _fake_call_llm(cfg, system_prompt, user_prompt, **kwargs):
        calls.append(user_prompt)
        start = len(calls) * 100
        names = [{"name": f"Company{start + i}"} for i in range(discovery_module.SUGGESTION_BATCH_SIZE)]
        return json.dumps({"companies": names})

    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", _fake_call_llm)
    profile = _seed_profile(db_session, app_context)

    result = suggest_companies(_ai_config(), profile, count=100)

    assert len(calls) > 1  # split, not one giant call
    assert len(result) == 100
    assert len({s.name for s in result}) == 100  # no duplicates across batches


def test_each_batch_is_told_what_earlier_batches_returned(db_session, app_context, monkeypatch):
    """This is what actually forces variety - without it the model just
    returns the same obvious names every round."""
    calls = []

    def _fake_call_llm(cfg, system_prompt, user_prompt, **kwargs):
        calls.append(user_prompt)
        n = len(calls)
        return json.dumps({"companies": [{"name": f"Batch{n}Co{i}"} for i in range(25)]})

    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", _fake_call_llm)
    profile = _seed_profile(db_session, app_context)

    suggest_companies(_ai_config(), profile, count=60)

    assert len(calls) >= 2
    # The second call must know about the first round's names.
    assert "Batch1Co0" in calls[1]


def test_one_failed_batch_does_not_abandon_the_whole_run(db_session, app_context, monkeypatch):
    calls = []

    def _fake_call_llm(cfg, system_prompt, user_prompt, **kwargs):
        calls.append(user_prompt)
        if len(calls) == 1:
            return None  # provider hiccup on the first round
        return json.dumps({"companies": [{"name": f"Late{i}"} for i in range(25)]})

    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", _fake_call_llm)
    profile = _seed_profile(db_session, app_context)

    result = suggest_companies(_ai_config(), profile, count=50)

    assert len(result) > 0  # later rounds still counted


def test_small_requests_stay_a_single_call(db_session, app_context, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.ai.llm_analyzer.call_llm",
        lambda cfg, s, u, **kw: calls.append(u) or json.dumps({"companies": [{"name": "Acme"}]}),
    )
    profile = _seed_profile(db_session, app_context)

    suggest_companies(_ai_config(), profile, count=5)

    assert len(calls) == 1


def test_suggestion_count_is_capped(db_session, app_context, monkeypatch):
    """A runaway count would turn into thousands of outbound probes."""
    monkeypatch.setattr(
        "app.ai.llm_analyzer.call_llm",
        lambda cfg, s, u, **kw: json.dumps(
            {"companies": [{"name": f"C{i}"} for i in range(50)]}
        ),
    )
    profile = _seed_profile(db_session, app_context)

    result = suggest_companies(_ai_config(), profile, count=10_000)

    assert len(result) <= discovery_module.MAX_SUGGESTIONS


def test_suggest_companies_prompt_includes_profile_and_exclusions(db_session, app_context, monkeypatch):
    captured = {}

    def _fake_call_llm(cfg, system_prompt, user_prompt, **kwargs):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return '{"companies": [{"name": "Acme"}]}'

    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", _fake_call_llm)
    profile = _seed_profile(db_session, app_context, industries=["Aerospace"])

    result = suggest_companies(_ai_config(), profile, count=10, exclude=["Globex"])

    assert [s.name for s in result] == ["Acme"]
    assert "CFD Engineer" in captured["user"]
    assert "Aerospace" in captured["user"]
    assert "Globex" in captured["user"]  # already-monitored companies aren't re-suggested
    assert "Return exactly 10 companies" in captured["user"]
    # Profile text is fenced as data, matching the app's prompt-injection posture.
    assert "BEGIN CANDIDATE PROFILE" in captured["user"]


# --------------------------------------------------------------------------
# Board resolution (ATS probing)
# --------------------------------------------------------------------------

def test_resolve_company_board_finds_a_greenhouse_board(monkeypatch):
    def _fake_get_json(url, **kwargs):
        if "greenhouse" in url and "/acme/" in url:
            return {"jobs": [{"id": 1}, {"id": 2}]}
        raise JobSourceHTTPError("404")

    monkeypatch.setattr(discovery_module, "get_json", _fake_get_json)

    board = resolve_company_board("Acme")

    assert board is not None
    assert board.source_type == "greenhouse"
    assert board.config == {"board_token": "acme", "company_name": "Acme"}
    assert board.job_count == 2


def test_resolve_company_board_falls_through_to_lever(monkeypatch):
    def _fake_get_json(url, **kwargs):
        if "api.lever.co" in url:
            return [{"id": "a"}]
        raise JobSourceHTTPError("404")

    monkeypatch.setattr(discovery_module, "get_json", _fake_get_json)

    board = resolve_company_board("Acme")

    assert board is not None and board.source_type == "lever"
    assert board.config["company_slug"] == "acme"


def test_resolve_company_board_tries_alternate_slug_spellings(monkeypatch):
    """A hyphenated slug is a common real-world spelling - a single guess
    would miss the board entirely."""
    def _fake_get_json(url, **kwargs):
        if "acme-robotics" in url and "greenhouse" in url:
            return {"jobs": [{"id": 1}]}
        raise JobSourceHTTPError("404")

    monkeypatch.setattr(discovery_module, "get_json", _fake_get_json)

    board = resolve_company_board("Acme Robotics")

    assert board is not None
    assert board.config["board_token"] == "acme-robotics"


def test_resolve_company_board_finds_a_workable_board(monkeypatch):
    """Workable and SmartRecruiters widen discovery well beyond the
    venture-backed-tech companies the first three platforms cover."""
    def _fake_get_json(url, **kwargs):
        if "workable.com" in url:
            return {"name": "Blueground", "jobs": [{"shortcode": "A"}, {"shortcode": "B"}]}
        raise JobSourceHTTPError("404")

    monkeypatch.setattr(discovery_module, "get_json", _fake_get_json)

    board = resolve_company_board("Blueground")

    assert board is not None and board.source_type == "workable"
    assert board.config["account_slug"] == "blueground"
    # The API's own display name beats the slug for the source label.
    assert board.config["company_name"] == "Blueground"


def test_resolve_company_board_finds_a_smartrecruiters_board(monkeypatch):
    def _fake_get_json(url, **kwargs):
        if "smartrecruiters.com" in url:
            return {"totalFound": 42, "content": [{"id": "1"}]}
        raise JobSourceHTTPError("404")

    monkeypatch.setattr(discovery_module, "get_json", _fake_get_json)

    board = resolve_company_board("Acme")

    assert board is not None and board.source_type == "smartrecruiters"
    assert board.config["company_slug"] == "acme"
    assert board.job_count == 42


def test_smartrecruiters_zero_total_is_treated_as_not_found(monkeypatch):
    """SmartRecruiters answers an unknown company with HTTP 200 and zero
    postings rather than 404, so "empty" is the only signal that a slug
    guess was wrong - accepting it would add a dead source."""
    monkeypatch.setattr(
        discovery_module, "get_json",
        lambda url, **kw: {"totalFound": 0, "content": []} if "smartrecruiters" in url
        else (_ for _ in ()).throw(JobSourceHTTPError("404")),
    )

    assert resolve_company_board("Nonexistent") is None


def test_resolve_company_board_rejects_an_empty_board(monkeypatch):
    """A slug that resolves but has zero postings is indistinguishable
    from a wrong guess - adding it would create a permanently empty
    source."""
    monkeypatch.setattr(discovery_module, "get_json", lambda url, **kw: {"jobs": []})
    assert resolve_company_board("Acme") is None


def test_resolve_company_board_returns_none_when_nothing_matches(monkeypatch):
    def _always_404(url, **kwargs):
        raise JobSourceHTTPError("404")

    monkeypatch.setattr(discovery_module, "get_json", _always_404)
    assert resolve_company_board("Nonexistent Company") is None


def test_resolve_company_board_survives_unexpected_probe_errors(monkeypatch):
    """A malformed response must not take down a whole discovery run."""
    def _explode(url, **kwargs):
        raise ValueError("unexpected payload shape")

    monkeypatch.setattr(discovery_module, "get_json", _explode)
    assert resolve_company_board("Acme") is None


# --------------------------------------------------------------------------
# Full discovery flow
# --------------------------------------------------------------------------

def test_discovery_requires_an_llm(db_session, app_context):
    profile = _seed_profile(db_session, app_context)
    result = discover_and_add_sources(
        db_session, app_context, _ai_config(llm_provider="none"), profile
    )
    assert result.added == []
    assert "LLM provider" in result.error


def test_discovery_works_with_a_local_llm(db_session, app_context, monkeypatch):
    """Company discovery shouldn't require paying for a hosted API - a
    model on the user's own machine is a real, working LLM provider."""
    monkeypatch.setattr(
        discovery_module, "suggest_companies", lambda *a, **kw: [CompanySuggestion("Acme")]
    )
    monkeypatch.setattr(
        discovery_module, "resolve_company_board",
        lambda name: ResolvedBoard(name, "greenhouse", {"board_token": "acme", "company_name": name}, 3),
    )
    profile = _seed_profile(db_session, app_context)
    local_config = _ai_config(
        llm_provider="local", llm_model="llama3.1", local_llm_base_url="http://localhost:11434/v1",
        anthropic_api_key="", openai_api_key="",
    )

    result = discover_and_add_sources(db_session, app_context, local_config, profile)

    assert [b.company_name for b in result.added] == ["Acme"]


def test_discovery_requires_a_resume(db_session, app_context):
    user = app_context.users_repo.get_or_create_default_user(db_session, "test@example.com")
    empty_profile = app_context.candidate_profile_repo.get_current(db_session, user.id)
    result = discover_and_add_sources(db_session, app_context, _ai_config(), empty_profile)
    assert result.added == []
    assert "Upload a resume" in result.error


def test_discovery_adds_only_companies_with_real_boards(db_session, app_context, monkeypatch):
    monkeypatch.setattr(
        discovery_module, "suggest_companies",
        lambda *a, **kw: [CompanySuggestion("Acme"), CompanySuggestion("Ghost Corp")],
    )
    monkeypatch.setattr(
        discovery_module, "resolve_company_board",
        lambda name: (
            ResolvedBoard(name, "greenhouse", {"board_token": "acme", "company_name": name}, 3)
            if name == "Acme" else None
        ),
    )
    profile = _seed_profile(db_session, app_context)

    result = discover_and_add_sources(db_session, app_context, _ai_config(), profile)

    assert [b.company_name for b in result.added] == ["Acme"]
    assert result.unresolved == ["Ghost Corp"]

    sources = app_context.job_sources_repo.list_all(db_session)
    assert len(sources) == 1
    assert sources[0].source_type == "greenhouse"
    assert sources[0].config["board_token"] == "acme"


def test_discovery_does_not_duplicate_already_configured_companies(db_session, app_context, monkeypatch):
    app_context.job_sources_repo.create(
        db_session, name="Acme (Greenhouse)", source_type="greenhouse",
        config={"board_token": "acme", "company_name": "Acme"},
    )
    db_session.flush()

    monkeypatch.setattr(
        discovery_module, "suggest_companies", lambda *a, **kw: [CompanySuggestion("Acme")]
    )
    probe_calls = []
    monkeypatch.setattr(
        discovery_module, "resolve_company_board",
        lambda name: probe_calls.append(name) or None,
    )
    profile = _seed_profile(db_session, app_context)

    result = discover_and_add_sources(db_session, app_context, _ai_config(), profile)

    assert result.skipped_existing == 1
    assert result.added == []
    assert probe_calls == []  # never even probed - no wasted HTTP request
    assert len(app_context.job_sources_repo.list_all(db_session)) == 1


def test_discovery_reports_progress(db_session, app_context, monkeypatch):
    monkeypatch.setattr(
        discovery_module, "suggest_companies", lambda *a, **kw: [CompanySuggestion("Acme")]
    )
    monkeypatch.setattr(
        discovery_module, "resolve_company_board",
        lambda name: ResolvedBoard(name, "lever", {"company_slug": "acme"}, 1),
    )
    profile = _seed_profile(db_session, app_context)
    messages = []

    discover_and_add_sources(
        db_session, app_context, _ai_config(), profile, progress_callback=messages.append
    )

    assert any("Asking the AI" in m for m in messages)
    assert any("Acme" in m for m in messages)
    assert any("Discovery complete" in m for m in messages)


def test_discovery_surfaces_an_empty_llm_response(db_session, app_context, monkeypatch):
    monkeypatch.setattr(discovery_module, "suggest_companies", lambda *a, **kw: [])
    profile = _seed_profile(db_session, app_context)

    result = discover_and_add_sources(db_session, app_context, _ai_config(), profile)

    assert result.added == []
    assert "didn't return any company suggestions" in result.error
