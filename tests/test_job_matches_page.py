"""Tests for the Job Matches detail dialog's HTML-escaping (section 24):
job titles/companies and LLM-derived strengths/gaps/reasoning may
ultimately come from untrusted job-posting text and must never be
interpolated unescaped into Qt rich-text (HTML) labels."""

from __future__ import annotations

from app.ui.pages.job_matches import MatchDetailDialog, _e


def test_escape_helper_neutralizes_html_special_characters():
    assert _e("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"
    assert _e("Q&A") == "Q&amp;A"
    assert _e(None) == ""
    assert _e("") == ""


def test_section_label_escapes_items_and_title(qtbot):
    # `qtbot` ensures a QApplication exists - constructing a QLabel
    # without one crashes rather than raising a catchable Python error.
    label = MatchDetailDialog._section_label(
        "Why this matches",
        ["<script>alert(1)</script>", "Normal strength & more"],
        "#059669",
    )
    text = label.text()
    assert "<script>alert(1)</script>" not in text  # never present unescaped
    assert "&lt;script&gt;" in text
    assert "Normal strength &amp; more" in text
