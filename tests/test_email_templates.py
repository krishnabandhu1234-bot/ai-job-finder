"""Tests for daily email content generation (section 11)."""

from __future__ import annotations

import datetime as dt

from app.email.templates import ReportItem, format_salary, render_html_body, render_subject, render_text_body


def _item(**overrides) -> ReportItem:
    base = dict(
        match_id=1, job_id=1, title="Principal Thermal Engineer", company="NVIDIA",
        location="Austin, TX", remote=False, overall_score=97.0, category="exceptional",
        salary_text="USD 180,000 - 220,000", posted_date=dt.datetime(2026, 9, 6),
        apply_url="https://example.com/apply/1",
        strengths=["15+ years of relevant simulation experience"],
        gaps=["Resume does not explicitly mention Ansys Icepak"],
        reasoning="Excellent fit.",
    )
    base.update(overrides)
    return ReportItem(**base)


def test_format_salary_range():
    assert format_salary(120000, 150000, "USD") == "USD 120,000 - 150,000"


def test_format_salary_single_value():
    assert format_salary(140000, 140000, "USD") == "USD 140,000"


def test_format_salary_unknown():
    assert format_salary(None, None, "") == "Unknown"


def test_subject_mentions_count_and_date():
    subject = render_subject(6, dt.datetime(2026, 9, 7))
    assert "6" in subject
    assert "September 07, 2026" in subject


def test_subject_zero_jobs_says_no_new_jobs():
    subject = render_subject(0, dt.datetime(2026, 9, 7))
    assert "No new" in subject


def test_text_body_includes_job_details_and_apply_link():
    body = render_text_body([_item()], dt.datetime(2026, 9, 7))
    assert "Principal Thermal Engineer" in body
    assert "NVIDIA" in body
    assert "97%" in body
    assert "https://example.com/apply/1" in body


def test_text_body_empty_is_honest_not_fabricated():
    body = render_text_body([], dt.datetime(2026, 9, 7))
    assert "No new jobs" in body


def test_html_body_escapes_untrusted_job_content():
    """Section 24/32: job posting content (here, an attacker-controlled
    company name) must never be interpreted as HTML/JS in the email."""
    item = _item(company="<script>alert(1)</script>")
    html = render_html_body([item], dt.datetime(2026, 9, 7))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_body_includes_apply_button_link():
    html = render_html_body([_item()], dt.datetime(2026, 9, 7))
    assert "https://example.com/apply/1" in html
    assert "Apply Now" in html


def test_html_body_empty_state_has_no_job_cards():
    html = render_html_body([], dt.datetime(2026, 9, 7))
    assert "Apply Now" not in html
