"""Tests for opt-in AI resume reading (`app/resume/llm_extractor.py`).

Two things matter most here and are tested hardest:
  1. the privacy gate - this is the only feature that sends resume text
     off the machine, so it must refuse to run unless genuinely enabled;
  2. the merge - the offline parser's concrete findings must never be
     lost just because the model didn't repeat them.
"""

from __future__ import annotations

import pytest

from app.ai.embeddings import AIRuntimeConfig
from app.resume import llm_extractor
from app.resume.llm_extractor import (
    LLMResumeError,
    extract_with_llm,
    is_available,
    merge_llm_into_fields,
    parse_llm_fields,
    unavailable_reason,
)


def _ai_config(**overrides) -> AIRuntimeConfig:
    base = dict(
        local_only=False, embedding_provider="local", embedding_model="all-MiniLM-L6-v2",
        llm_provider="anthropic", llm_model="claude-sonnet-5",
        anthropic_api_key="sk-test", openai_api_key="", voyage_api_key="",
    )
    base.update(overrides)
    return AIRuntimeConfig(**base)


_VALID = """{
  "target_roles": ["Machine Learning Engineer", "Software Engineer"],
  "seniority": "senior",
  "years_experience": 8.5,
  "industries": ["Aerospace"],
  "technical_skills": ["distributed systems"],
  "programming_languages": ["Python"],
  "software": ["PyTorch"],
  "domain_expertise": ["computer vision"],
  "certifications": [],
  "companies": ["Acme"],
  "education": ["BSc - MIT"],
  "leadership": ["Led a team of 6"],
  "achievements": ["Cut latency 40%"],
  "locations": ["Austin, TX"]
}"""


# --------------------------------------------------------------------------
# Privacy gate
# --------------------------------------------------------------------------

def test_local_only_mode_disables_ai_resume_reading():
    """Local-only mode promises nothing leaves the machine. This feature
    would break that promise, so the toggle must win over everything -
    even a fully configured API key."""
    config = _ai_config(local_only=True)

    assert is_available(config) is False
    assert "Local-only mode" in unavailable_reason(config)
    with pytest.raises(LLMResumeError, match="Local-only"):
        extract_with_llm(config, "Jane Doe, engineer")


def test_unavailable_without_an_llm_provider():
    config = _ai_config(llm_provider="none")

    assert is_available(config) is False
    assert "No LLM provider" in unavailable_reason(config)


def test_available_when_properly_configured():
    assert is_available(_ai_config()) is True
    assert unavailable_reason(_ai_config()) == ""


def test_local_llm_stays_available_under_local_only_mode():
    """A model running on the user's own machine never sends anything
    anywhere, so it satisfies local_only's promise rather than breaking
    it - the opposite of the paid-provider case above."""
    config = _ai_config(
        local_only=True, llm_provider="local", llm_model="llama3.1",
        local_llm_base_url="http://localhost:11434/v1",
        anthropic_api_key="", openai_api_key="",
    )
    assert is_available(config) is True
    assert unavailable_reason(config) == ""


def test_local_llm_unavailable_reason_when_not_fully_configured():
    config = _ai_config(llm_provider="local", llm_model="", local_llm_base_url="")
    assert is_available(config) is False
    assert "Local LLM isn't fully configured" in unavailable_reason(config)


def test_extract_with_local_llm(monkeypatch):
    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", lambda *a, **kw: _VALID)
    config = _ai_config(
        llm_provider="local", llm_model="llama3.1", local_llm_base_url="http://localhost:11434/v1",
        anthropic_api_key="", openai_api_key="",
    )

    fields = extract_with_llm(config, "Jane Doe, ML engineer")

    assert fields["seniority"] == "senior"


def test_empty_resume_text_is_rejected_before_any_api_call(monkeypatch):
    called = []
    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", lambda *a, **kw: called.append(1))

    with pytest.raises(LLMResumeError, match="no readable text"):
        extract_with_llm(_ai_config(), "   ")
    assert called == []


def test_long_resume_is_truncated_before_sending(monkeypatch):
    captured = {}

    def fake_call(cfg, system, user, **kwargs):
        captured["len"] = len(user)
        return _VALID

    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", fake_call)
    extract_with_llm(_ai_config(), "x" * (llm_extractor.MAX_RESUME_CHARS + 5_000))

    # The prompt wrapper adds a little, but the resume body itself is capped.
    assert captured["len"] < llm_extractor.MAX_RESUME_CHARS + 500


def test_resume_text_is_fenced_in_the_prompt(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.ai.llm_analyzer.call_llm",
        lambda cfg, system, user, **kw: captured.update(user=user, system=system) or _VALID,
    )

    extract_with_llm(_ai_config(), "Jane Doe\nSenior Engineer")

    assert "BEGIN RESUME" in captured["user"]
    assert "END RESUME" in captured["user"]
    assert "Jane Doe" in captured["user"]
    # Section 33: the model must not invent credentials.
    assert "Never invent" in captured["system"]


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------

def test_parse_valid_response():
    fields = parse_llm_fields(_VALID)
    assert fields["target_roles"] == ["Machine Learning Engineer", "Software Engineer"]
    assert fields["seniority"] == "senior"
    assert fields["years_experience"] == 8.5
    assert fields["domain_expertise"] == ["computer vision"]


def test_parse_strips_markdown_fence():
    assert parse_llm_fields("```json\n" + _VALID + "\n```")["seniority"] == "senior"


def test_parse_rejects_garbage():
    assert parse_llm_fields("not json") is None
    assert parse_llm_fields("[]") is None


def test_parse_rejects_an_invalid_seniority_rather_than_storing_it():
    """An unknown level would silently break seniority matching, which
    feeds three scoring layers."""
    fields = parse_llm_fields('{"seniority": "Chief Wizard", "target_roles": []}')
    assert fields["seniority"] == ""


def test_parse_clamps_implausible_years_of_experience():
    """Models occasionally answer in months or hallucinate a career
    longer than a lifetime."""
    assert parse_llm_fields('{"years_experience": 900}')["years_experience"] == 60.0
    assert parse_llm_fields('{"years_experience": -5}')["years_experience"] == 0.0
    assert parse_llm_fields('{"years_experience": "not a number"}')["years_experience"] == 0.0


def test_parse_ignores_non_list_and_non_string_junk():
    fields = parse_llm_fields(
        '{"technical_skills": "should be a list", "companies": ["Acme", null, {"x": 1}, "Acme"]}'
    )
    assert fields["technical_skills"] == []
    assert fields["companies"] == ["Acme"]  # dedup + junk dropped


def test_extract_raises_when_the_provider_returns_nothing(monkeypatch):
    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", lambda *a, **kw: None)
    with pytest.raises(LLMResumeError, match="did not return"):
        extract_with_llm(_ai_config(), "Jane Doe")


def test_extract_raises_on_an_unreadable_reply(monkeypatch):
    monkeypatch.setattr("app.ai.llm_analyzer.call_llm", lambda *a, **kw: "sorry, I can't help")
    with pytest.raises(LLMResumeError, match="could not be read"):
        extract_with_llm(_ai_config(), "Jane Doe")


# --------------------------------------------------------------------------
# Merge behavior
# --------------------------------------------------------------------------

def test_merge_never_loses_what_the_offline_parser_found():
    """The taxonomy's hits are concrete string matches against the actual
    resume - the more trustworthy half. They must survive even if the
    model doesn't repeat them."""
    rule_based = {"technical_skills": ["CFD", "thermal analysis"], "target_roles": ["CFD Engineer"]}
    llm = {"technical_skills": ["machine learning"], "target_roles": ["ML Engineer"]}

    merged = merge_llm_into_fields(rule_based, llm)

    assert "CFD" in merged["technical_skills"]
    assert "thermal analysis" in merged["technical_skills"]
    assert "machine learning" in merged["technical_skills"]
    assert merged["target_roles"] == ["CFD Engineer", "ML Engineer"]


def test_merge_is_case_insensitively_deduplicated():
    merged = merge_llm_into_fields(
        {"technical_skills": ["Python"]}, {"technical_skills": ["python", "PYTHON", "Rust"]}
    )
    assert merged["technical_skills"] == ["Python", "Rust"]


def test_merge_lets_the_model_win_on_interpretive_scalars():
    """Seniority and years of experience require reading a career, not
    pattern-matching tokens - the rule-based version guesses seniority
    from title keywords alone."""
    merged = merge_llm_into_fields(
        {"seniority": "mid", "years_experience": 3.0},
        {"seniority": "staff", "years_experience": 11.0},
    )
    assert merged["seniority"] == "staff"
    assert merged["years_experience"] == 11.0


def test_merge_keeps_rule_based_scalars_when_the_model_is_silent():
    merged = merge_llm_into_fields(
        {"seniority": "senior", "years_experience": 8.0},
        {"seniority": "", "years_experience": 0.0},
    )
    assert merged["seniority"] == "senior"
    assert merged["years_experience"] == 8.0


def test_merge_preserves_unrelated_rule_based_fields():
    """Fields the LLM schema doesn't cover (e.g. source_resume_ids) must
    pass through untouched."""
    merged = merge_llm_into_fields(
        {"source_resume_ids": [1, 2], "publications": ["A paper"]}, {"target_roles": ["Eng"]}
    )
    assert merged["source_resume_ids"] == [1, 2]
    assert merged["publications"] == ["A paper"]
