"""Tests for stripping job-description HTML down to plain text."""

from __future__ import annotations

from app.jobs.html_text import html_to_text


def test_empty_input():
    assert html_to_text("") == ""
    assert html_to_text(None) == ""


def test_strips_simple_tags():
    assert html_to_text("<p>Hello world</p>") == "Hello world"


def test_inline_tag_does_not_fracture_a_sentence():
    # Regression: an earlier version used get_text(separator="\n"), which
    # split "Great role" into "Great\nrole" because of the inline <b> tag.
    assert html_to_text("<p>Great <b>role</b></p>") == "Great role"


def test_block_tags_produce_line_breaks():
    result = html_to_text("<p>Paragraph one</p><p>Paragraph two</p>")
    assert result == "Paragraph one\nParagraph two"


def test_list_items_get_their_own_line():
    result = html_to_text("<ul><li>Requirement A</li><li>Requirement B</li></ul>")
    assert "Requirement A" in result.split("\n")
    assert "Requirement B" in result.split("\n")


def test_br_becomes_a_newline():
    result = html_to_text("Line one<br>Line two")
    assert result == "Line one\nLine two"


def test_html_entity_escaped_markup_is_unescaped_then_stripped():
    """Regression: observed on Greenhouse's real public API - the
    'content' field can be HTML-escaped ("&lt;div&gt;...") rather than
    real markup. Naively parsing that leaves the escaped tags looking
    like literal text (nothing to strip), so job descriptions ended up
    containing visible "<div class=...>" garbage. See netcheck2.py from
    the manual verification against boards-api.greenhouse.io/v1/boards/
    gitlab/jobs for how this was found."""
    escaped = "&lt;div class=&quot;content-intro&quot;&gt;&lt;p&gt;Hello world&lt;/p&gt;&lt;/div&gt;"
    assert html_to_text(escaped) == "Hello world"


def test_plain_unescaped_html_is_unaffected_by_the_unescape_step():
    assert html_to_text("<p>Already real HTML</p>") == "Already real HTML"


def test_collapses_excess_whitespace():
    result = html_to_text("<p>Too    many     spaces</p>")
    assert result == "Too many spaces"
