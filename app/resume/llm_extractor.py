"""Optional LLM-assisted resume understanding.

The rule-based extractor (`app/resume/extractor.py`) is fast, free,
private and completely offline - but it can only recognize what its
taxonomy already knows. It reads "Python" and "Kubernetes" reliably; it
cannot infer that someone whose resume never says the words "Machine
Learning Engineer" is nonetheless one, or summarize a career narrative
into target roles, industries and domain expertise.

This module adds that understanding when the user opts in, by having
their configured LLM read the resume text and return the same structured
fields the rest of the app already uses.

PRIVACY - the important part
----------------------------
Everything else in this app is built so the resume never leaves the
machine: the raw file is never uploaded, and only a compact structured
profile is ever sent to an LLM (see `app/ai/llm_analyzer.py`). This
feature is the single deliberate exception: it sends the resume's TEXT
to whichever provider the user configured.

That is a real, meaningful change in what leaves the computer, so:
  * it is OFF by default,
  * it never runs implicitly as a side effect of uploading a resume -
    the user has to turn it on and re-parse,
  * the UI states plainly that resume text is sent, to which provider,
    and the docs say the same, and
  * "Local-only mode" in AI Settings disables it outright, no matter
    what this setting says, because that toggle's whole promise is that
    nothing leaves the machine.

Results are MERGED with the rule-based extraction rather than replacing
it (`merge_llm_into_fields`), so the concrete, verifiable things the
taxonomy found are never lost if the model omits them - and, per section
33, the model is instructed to extract only what the resume actually
says rather than inferring credentials the candidate doesn't claim.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Resumes are short; this is generous enough for a long CV while
# bounding what a runaway file could send to a metered API.
MAX_RESUME_CHARS = 24_000
_MAX_OUTPUT_TOKENS = 4096
_TIMEOUT_SECONDS = 120.0

_SYSTEM_PROMPT = """You are parsing a candidate's resume into structured data for a job-matching \
system.

Extract ONLY what the resume actually supports. Never invent a skill, employer, credential, \
degree or achievement that is not present in the text. If something isn't stated, leave that \
field empty - an empty field is correct and useful; a guessed one corrupts every downstream \
match.

`target_roles` is the exception to "only what's stated": infer 2-5 job titles this person is \
realistically a strong candidate for TODAY, based on what they have actually done. Use \
conventional industry titles someone would really search for, not creative phrasing.

`years_experience` is total professional experience in years as a number (a decimal is fine). \
Estimate it from employment dates if it isn't stated outright; use 0 if there's no basis at all.

`seniority` must be exactly one of: entry, mid, senior, staff, principal, lead, manager, \
director, vp, executive.

Respond with ONLY a JSON object of this exact shape, no other text:
{
  "target_roles": ["<title>"],
  "seniority": "<one of the levels above>",
  "years_experience": <number>,
  "industries": ["<industry the person has actually worked in>"],
  "technical_skills": ["<skill>"],
  "programming_languages": ["<language>"],
  "software": ["<tool or platform>"],
  "domain_expertise": ["<subject-matter area>"],
  "certifications": ["<certification>"],
  "companies": ["<employer name>"],
  "education": ["<degree - institution>"],
  "leadership": ["<leadership scope, e.g. 'Led a team of 6 engineers'>"],
  "achievements": ["<quantified accomplishment, copied faithfully from the resume>"],
  "locations": ["<place the candidate is based in or says they want to work>"]
}
"""

# Fields whose values are lists of strings, merged by union.
_LIST_FIELDS = (
    "target_roles", "industries", "technical_skills", "programming_languages",
    "software", "domain_expertise", "certifications", "companies", "education",
    "leadership", "achievements", "locations",
)

_VALID_SENIORITY = {
    "entry", "mid", "senior", "staff", "principal",
    "lead", "manager", "director", "vp", "executive",
}


class LLMResumeError(Exception):
    """Raised when an explicitly-requested LLM parse could not run.

    Deliberately raised rather than silently degrading: the user asked
    for AI parsing and is waiting on it, so quietly falling back to the
    rule-based result would look like the feature did nothing (section
    23: never silently fail)."""


def is_available(ai_config) -> bool:
    """Whether AI resume reading can run at all right now.

    Delegates entirely to `AIRuntimeConfig.has_usable_llm()`, which
    already encodes the one exception to "local_only blocks everything":
    a `llm_provider == "local"` model runs on this machine and never
    sends anything anywhere, so it satisfies local_only's promise rather
    than breaking it, and stays available under it."""
    return ai_config.has_usable_llm()


def unavailable_reason(ai_config) -> str:
    if ai_config.has_usable_llm():
        return ""
    if ai_config.llm_provider == "local":
        return (
            "Local LLM isn't fully configured yet. Set both the endpoint URL and the model "
            "name on the AI Settings page, and make sure Ollama/LM Studio is running."
        )
    if ai_config.local_only:
        return (
            "Local-only mode is on (AI Settings), so nothing may be sent to an external API. "
            "Turn it off to use a paid provider here, switch 'LLM provider' to \"local\" to use "
            "a model on your own machine instead, or keep using the offline rule-based reader."
        )
    return (
        "No LLM provider is configured. Set 'LLM provider' to anthropic, openai, gemini, or "
        "local on the AI Settings page (and add that provider's API key, if it needs one)."
    )


def extract_with_llm(ai_config, resume_text: str) -> dict:
    """Reads a resume with the configured LLM and returns profile fields.

    Raises `LLMResumeError` if it can't run or the model's reply can't be
    used. Callers surface that to the user rather than pretending the
    parse succeeded."""
    if not is_available(ai_config):
        raise LLMResumeError(unavailable_reason(ai_config))

    text = (resume_text or "").strip()
    if not text:
        raise LLMResumeError("This resume has no readable text to analyze.")
    if len(text) > MAX_RESUME_CHARS:
        logger.info("Resume text truncated from %d to %d chars for LLM parsing.", len(text), MAX_RESUME_CHARS)
        text = text[:MAX_RESUME_CHARS]

    from app.ai.llm_analyzer import call_llm

    prompt = (
        "Parse this resume.\n\n"
        "--- BEGIN RESUME ---\n"
        f"{text}\n"
        "--- END RESUME ---"
    )
    raw = call_llm(
        ai_config, _SYSTEM_PROMPT, prompt,
        max_tokens=_MAX_OUTPUT_TOKENS, timeout=_TIMEOUT_SECONDS,
    )
    if not raw:
        raise LLMResumeError(
            "The AI provider did not return a result. Check your API key and network "
            "connection - the Logs page shows the underlying error."
        )

    parsed = parse_llm_fields(raw)
    if parsed is None:
        raise LLMResumeError("The AI returned a response that could not be read as resume data.")
    return parsed


def parse_llm_fields(raw_text: str) -> dict | None:
    """Turns the model's JSON reply into clean profile fields, or None.

    Tolerant of the usual model output quirks (markdown fences, a stray
    non-list where a list belongs) but never of made-up structure: an
    unusable reply returns None so the caller can say so plainly."""
    try:
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Could not parse LLM resume response as JSON.")
        return None

    if not isinstance(data, dict):
        return None

    fields: dict = {}
    for key in _LIST_FIELDS:
        fields[key] = _clean_string_list(data.get(key))

    seniority = str(data.get("seniority") or "").strip().lower()
    fields["seniority"] = seniority if seniority in _VALID_SENIORITY else ""

    try:
        years = float(data.get("years_experience") or 0)
    except (TypeError, ValueError):
        years = 0.0
    # A model occasionally answers in months, or hallucinates a career
    # longer than a human lifetime; clamp rather than trust it blindly.
    fields["years_experience"] = round(max(0.0, min(years, 60.0)), 1)

    return fields


def _clean_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, (str, int, float)):
            continue
        text = str(item).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def merge_llm_into_fields(rule_based: dict, llm_fields: dict) -> dict:
    """Combines the offline extraction with the LLM's reading.

    Union for lists, rule-based first: the taxonomy's hits are concrete
    string matches against the resume, so they're the more trustworthy
    half and shouldn't be dropped just because the model didn't repeat
    them. The model's additions come after, which is also the order a
    reader will scan them in.

    For the two interpretive scalars - seniority and years of experience
    - the model wins when it produced something, because those require
    reading a career rather than pattern-matching tokens (the rule-based
    version guesses seniority from title keywords alone). Both remain
    editable in the UI before anything is saved."""
    merged = dict(rule_based)

    for key in _LIST_FIELDS:
        if key not in llm_fields:
            continue
        combined = list(rule_based.get(key) or []) + list(llm_fields.get(key) or [])
        seen: set[str] = set()
        deduped: list[str] = []
        for item in combined:
            text = str(item).strip()
            lookup = text.casefold()
            if text and lookup not in seen:
                seen.add(lookup)
                deduped.append(text)
        merged[key] = deduped

    if llm_fields.get("seniority"):
        merged["seniority"] = llm_fields["seniority"]
    if llm_fields.get("years_experience"):
        merged["years_experience"] = llm_fields["years_experience"]

    return merged
