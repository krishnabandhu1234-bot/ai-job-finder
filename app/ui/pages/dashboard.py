"""Dashboard: the section-14 "at a glance" screen. Pulls real numbers from
the database (all zero/empty on a fresh install) rather than showing
placeholder/fake data."""

from __future__ import annotations

import re
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from app.core.constants import ScanTrigger
from app.core.rank_worker import start_ranking
from app.core.scan_worker import start_scan
from app.core.scheduler import get_scheduler
from app.database.db import session_scope
from app.ui.base_page import BasePage, empty_state, make_card


def _stat_card(value: str, label: str) -> QWidget:
    card = make_card()
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 16, 20, 16)
    value_label = QLabel(value)
    value_label.setObjectName("statValue")
    label_label = QLabel(label)
    label_label.setObjectName("statLabel")
    layout.addWidget(value_label)
    layout.addWidget(label_label)
    return card


class DashboardPage(BasePage):
    title = "Dashboard"
    subtitle = "Your job search at a glance"

    def build(self) -> None:
        # --- Update banner (only shown when a newer version is known) ---
        # The Dashboard is the screen every user lands on, so this is
        # where a pushed update actually gets seen - the Settings page
        # also shows it, but a user has no reason to visit Settings just
        # to check. Built hidden and only shown by _refresh_update_banner.
        self.update_banner = make_card()
        self.update_banner.setStyleSheet("background-color: #eef2ff; border: 1px solid #3457d5;")
        banner_layout = QHBoxLayout(self.update_banner)
        banner_layout.setContentsMargins(16, 12, 16, 12)
        self.update_banner_label = QLabel("")
        self.update_banner_label.setWordWrap(True)
        self.update_banner_label.setStyleSheet("color: #1e293b;")
        banner_layout.addWidget(self.update_banner_label, stretch=1)
        self.update_download_button = QPushButton("Get Update")
        self.update_download_button.setObjectName("primaryButton")
        self.update_download_button.clicked.connect(self._open_update_download)
        banner_layout.addWidget(self.update_download_button)
        self.update_banner.hide()
        self.content_layout.addWidget(self.update_banner)

        # --- Scan Now / status row ---
        action_row = QHBoxLayout()
        self.scan_button = QPushButton("SCAN NOW")
        self.scan_button.setObjectName("primaryButton")
        self.scan_button.setToolTip(
            "Fetches new postings from every enabled job source, dedupes them against what's "
            "already known, records which ones are new, then runs the AI matching engine "
            "against your candidate profile. This manual run never sends email - use "
            "\"Send Test Email\" (Email Settings) or \"Run Full Pipeline Now\" (Scheduler) for that."
        )
        self.scan_button.clicked.connect(self._start_scan)
        action_row.addWidget(self.scan_button)
        action_row.addStretch(1)
        self.status_label = QLabel("")
        self.status_label.setObjectName("pageSubtitle")
        action_row.addWidget(self.status_label)
        self.content_layout.addLayout(action_row)

        self.next_scan_label = QLabel("")
        self.next_scan_label.setStyleSheet("color: #6b7280;")
        self.content_layout.addWidget(self.next_scan_label)

        # --- Scan progress bar ---
        # Hidden outside of a scan/rank run. Scan and ranking each report
        # plain-text progress messages; where a stage can say how far
        # through it is (scanning source i of N, LLM-analyzing job i of
        # N), it puts "(i/N)" in that message and this bar reads it back
        # out - see _on_scan_progress. Stages that can't give a count
        # (e.g. "Computing hard filters...") just animate a busy bar
        # instead of sitting frozen on the last known number.
        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setTextVisible(False)
        self.scan_progress_bar.setFixedHeight(6)
        self.scan_progress_bar.hide()
        self.content_layout.addWidget(self.scan_progress_bar)

        # --- Stat cards ---
        self.stats_grid = QGridLayout()
        self.stats_grid.setSpacing(12)
        self.content_layout.addLayout(self.stats_grid)

        # --- Top matches ---
        top_matches_title = QLabel("TOP MATCHES")
        top_matches_title.setStyleSheet("font-weight: 600; color: #6b7280; letter-spacing: 1px;")
        self.content_layout.addWidget(top_matches_title)

        self.top_matches_container = QVBoxLayout()
        self.content_layout.addLayout(self.top_matches_container)

        self._scan_thread = None
        self._scan_worker = None
        self._rank_thread = None
        self._rank_worker = None
        self._scan_summary_message = ""
        self._last_scan_summary = None
        self.refresh()

    _PROGRESS_FRACTION_RE = re.compile(r"\((\d+)/(\d+)\)")

    def _start_scan(self) -> None:
        self.scan_button.setEnabled(False)
        self.scan_button.setText("SCANNING...")
        self.status_label.setText("Starting scan...")
        self._show_busy_progress()
        self._scan_thread, self._scan_worker = start_scan(
            self,
            on_progress=self._on_scan_progress,
            on_finished=self._on_scan_finished,
            on_failed=self._on_scan_failed,
            trigger=ScanTrigger.MANUAL.value,
        )

    def _show_busy_progress(self) -> None:
        """An animated, indeterminate bar - shown until progress reports
        a real fraction to switch to."""
        self.scan_progress_bar.setRange(0, 0)
        self.scan_progress_bar.show()

    def _on_scan_progress(self, message: str) -> None:
        self.status_label.setText(message)
        match = self._PROGRESS_FRACTION_RE.search(message)
        if match:
            current, total = int(match.group(1)), int(match.group(2))
            self.scan_progress_bar.setRange(0, total)
            self.scan_progress_bar.setValue(current)
        else:
            # A stage without a countable step (discovery, hard filters,
            # "no new jobs") - keep the bar visibly moving rather than
            # freezing on whatever fraction the previous stage left it at.
            self.scan_progress_bar.setRange(0, 0)
        self.scan_progress_bar.show()

    def _on_scan_finished(self, summary) -> None:
        self._last_scan_summary = summary
        self._scan_summary_message = (
            f"Retrieved {summary.jobs_retrieved} postings across "
            f"{len(summary.sources_scanned)} source(s).\n"
            f"New: {summary.total_new_or_reappeared}   "
            f"Updated: {summary.updated_jobs}   "
            f"No longer listed: {summary.disappeared_jobs}"
            + (f"\n\nFailed sources: {', '.join(summary.sources_failed)}" if summary.sources_failed else "")
        )
        self.scan_button.setText("RANKING...")
        self.status_label.setText("Scan complete. Running AI matching...")
        self._show_busy_progress()
        self.refresh()
        self._rank_thread, self._rank_worker = start_ranking(
            self,
            on_progress=self._on_scan_progress,
            on_finished=self._on_rank_finished,
            on_failed=self._on_rank_failed,
        )

    def _on_scan_failed(self, error: str) -> None:
        self.scan_button.setEnabled(True)
        self.scan_button.setText("SCAN NOW")
        self.status_label.setText("Scan failed.")
        self.scan_progress_bar.hide()
        QMessageBox.critical(self, "Scan Failed", f"The scan could not complete: {error}")

    def _on_rank_finished(self, summary) -> None:
        self.scan_button.setEnabled(True)
        self.scan_button.setText("SCAN NOW")
        self.scan_progress_bar.hide()
        if self._last_scan_summary is not None:
            with session_scope() as session:
                self.context.scan_history_repo.record_ai_results(
                    session, self._last_scan_summary.scan_history_id,
                    jobs_after_hard_filter=summary.jobs_considered - summary.hard_filtered_out,
                    jobs_embedded=summary.embedded,
                    jobs_llm_analyzed=summary.llm_analyzed,
                    excellent_matches=summary.exceptional + summary.excellent,
                )
        self.refresh()
        QMessageBox.information(
            self,
            "Scan Complete",
            self._scan_summary_message
            + f"\n\nAI matching: {summary.jobs_scored} job(s) scored, "
            f"{summary.exceptional} exceptional, {summary.excellent} excellent, "
            f"{summary.strong} strong matches.",
        )

    def _on_rank_failed(self, error: str) -> None:
        self.scan_button.setEnabled(True)
        self.scan_button.setText("SCAN NOW")
        self.status_label.setText("AI matching failed.")
        self.scan_progress_bar.hide()
        self.refresh()
        QMessageBox.warning(
            self,
            "Matching Failed",
            self._scan_summary_message + f"\n\nAI matching could not complete: {error}",
        )

    def refresh(self) -> None:
        self._refresh_update_banner()
        with session_scope() as session:
            stats = self.context.dashboard_repo.get_stats(session)

        # Clear and rebuild the stat cards
        while self.stats_grid.count():
            item = self.stats_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cards = [
            (str(stats.new_jobs_today), "New Jobs Today"),
            (str(stats.excellent_matches), "Excellent Matches"),
            (str(stats.strong_matches), "Strong Matches"),
            ("✓ Sent" if stats.email_sent_today else "Not sent yet", "Email Status"),
        ]
        for col, (value, label) in enumerate(cards):
            self.stats_grid.addWidget(_stat_card(value, label), 0, col)

        last_scan_text = (
            stats.last_scan_at.strftime("%B %d, %Y — %I:%M %p")
            if stats.last_scan_at
            else "No scans yet"
        )
        self.status_label.setText(f"Last scan: {last_scan_text}")
        self.next_scan_label.setText(f"Next scheduled scan: {self._next_scan_text()}")

        while self.top_matches_container.count():
            item = self.top_matches_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not stats.top_matches:
            # An empty Dashboard is exactly when a user most needs to know
            # what to do next, so point at the Setup Guide (which shows
            # which specific step is missing) rather than restating the
            # whole setup chain here and hoping they map it to reality.
            self.top_matches_container.addWidget(
                empty_state(
                    "No matches yet. The Setup Guide shows exactly which step is still "
                    "outstanding - it takes about five minutes end to end."
                )
            )
            setup_button = QPushButton("Open Setup Guide")
            setup_button.setObjectName("primaryButton")
            setup_button.clicked.connect(self._open_setup_guide)
            button_row = QHBoxLayout()
            button_row.addWidget(setup_button)
            button_row.addStretch(1)
            holder = QWidget()
            holder.setLayout(button_row)
            self.top_matches_container.addWidget(holder)
        else:
            for match in stats.top_matches:
                self.top_matches_container.addWidget(self._match_row(match))

    def _refresh_update_banner(self) -> None:
        """Shows the "get update" banner when a newer version is known.

        `check_for_update` itself is rate-limited to once a day and
        never raises, so calling it on every Dashboard visit is safe and
        cheap - most calls just read back the last cached result rather
        than making a request."""
        from app.core.updates import check_for_update

        try:
            with session_scope() as session:
                info = check_for_update(session, self.context)
        except Exception:
            self.update_banner.hide()
            return

        if not info.update_available:
            self.update_banner.hide()
            return

        self._update_download_url = info.download_url
        text = f"A new version is available: v{info.latest_version} (you have v{info.current_version})."
        if info.notes:
            text += f" {info.notes}"
        self.update_banner_label.setText(text)
        self.update_download_button.setEnabled(bool(info.download_url))
        self.update_banner.show()

    def _open_update_download(self) -> None:
        url = getattr(self, "_update_download_url", "")
        if url:
            webbrowser.open(url)

    def _open_setup_guide(self) -> None:
        window = self.window()
        navigate = getattr(window, "navigate_to", None)
        if callable(navigate):
            navigate("Setup Guide")

    @staticmethod
    def _next_scan_text() -> str:
        scheduler = get_scheduler()
        next_run = scheduler.next_run_time() if scheduler is not None else None
        if next_run is None:
            return "not scheduled (see the Scheduler page)"
        return next_run.strftime("%B %d, %Y — %I:%M %p %Z")

    def _match_row(self, match: dict) -> QWidget:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)

        score_label = QLabel(f"{match['score']:.0f}%")
        score_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #3457d5; min-width: 50px;")
        layout.addWidget(score_label)

        info = QVBoxLayout()
        title_label = QLabel(match["title"])
        title_label.setStyleSheet("font-weight: 600;")
        company_label = QLabel(f"{match['company']} — {match['location'] or 'Location unspecified'}")
        company_label.setStyleSheet("color: #6b7280;")
        info.addWidget(title_label)
        info.addWidget(company_label)
        layout.addLayout(info)
        layout.addStretch(1)
        return card
