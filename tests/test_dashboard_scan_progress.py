"""Tests for the Dashboard's scan progress bar (`app/ui/pages/dashboard.py`).

Scan and ranking report plain-text progress messages; some of those
messages carry a "(i/N)" fraction (see the matching comments in
scan_orchestrator.run_scan and ranker.run_ranking) and the bar is
supposed to read that back out to become determinate, falling back to
an animated/indeterminate state for stages that can't report a count.
"""

from __future__ import annotations

import pytest

from app.ui.pages.dashboard import DashboardPage

pytest.importorskip("PySide6")


@pytest.fixture
def page(qtbot, db_session, app_context):
    app_context.config.email_to = "test@example.com"
    widget = DashboardPage(app_context)
    qtbot.addWidget(widget)
    return widget


def test_progress_bar_hidden_until_a_scan_starts(page):
    assert page.scan_progress_bar.isHidden()


def test_progress_bar_shown_and_indeterminate_when_scan_starts(page, monkeypatch):
    monkeypatch.setattr(
        "app.ui.pages.dashboard.start_scan",
        lambda self, on_progress, on_finished, on_failed, trigger: (None, None),
    )

    page._start_scan()

    assert not page.scan_progress_bar.isHidden()
    assert page.scan_progress_bar.minimum() == 0
    assert page.scan_progress_bar.maximum() == 0  # indeterminate/busy


def test_progress_bar_becomes_determinate_from_a_fractioned_message(page):
    page._on_scan_progress("Scanning Acme... (3/10)")

    assert page.scan_progress_bar.minimum() == 0
    assert page.scan_progress_bar.maximum() == 10
    assert page.scan_progress_bar.value() == 3


def test_progress_bar_falls_back_to_indeterminate_without_a_fraction(page):
    page._on_scan_progress("Scanning Acme... (3/10)")
    page._on_scan_progress("Looking for new companies that match your resume...")

    assert page.scan_progress_bar.maximum() == 0


def test_progress_bar_tracks_llm_analysis_fraction(page):
    page._on_scan_progress("Running LLM analysis... (7/20)")

    assert page.scan_progress_bar.maximum() == 20
    assert page.scan_progress_bar.value() == 7


def test_progress_bar_hides_on_scan_failure(page, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

    page._show_busy_progress()
    page._on_scan_failed("network unreachable")

    assert page.scan_progress_bar.isHidden()


def test_progress_bar_hides_when_ranking_finishes(page, monkeypatch):
    from dataclasses import dataclass

    from PySide6.QtWidgets import QMessageBox

    # _on_rank_finished shows a modal QMessageBox.information() on success -
    # real user interaction, not something a headless test should block on.
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

    @dataclass
    class _FakeSummary:
        candidate_profile_id: int = 1
        jobs_considered: int = 0
        jobs_scored: int = 0
        hard_filtered_out: int = 0
        embedded: int = 0
        llm_analyzed: int = 0
        exceptional: int = 0
        excellent: int = 0
        strong: int = 0

    page._show_busy_progress()
    page._scan_summary_message = "Retrieved 0 postings."
    page._on_rank_finished(_FakeSummary())

    assert page.scan_progress_bar.isHidden()


def test_progress_bar_hides_when_ranking_fails(page, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))

    page._show_busy_progress()
    page._scan_summary_message = "Retrieved 0 postings."
    page._on_rank_failed("LLM provider unreachable")

    assert page.scan_progress_bar.isHidden()
