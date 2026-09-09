"""Scheduler (section 13). Backed by a real APScheduler instance
(`app.core.scheduler`) that runs the full scan -> AI ranking -> email
pipeline in the background while the app is open."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from app.core.constants import ScheduleFrequency
from app.core.scheduler import get_scheduler
from app.database.db import session_scope
from app.ui.base_page import BasePage, make_card

_KEY_PREFIX = "scheduler."

_FREQUENCY_LABELS = {
    ScheduleFrequency.EVERY_12_HOURS: "Every 12 hours",
    ScheduleFrequency.DAILY: "Daily",
    ScheduleFrequency.WEEKLY: "Weekly",
    ScheduleFrequency.MANUAL_ONLY: "Manual only",
}


class SchedulerPage(BasePage):
    title = "Scheduler"
    subtitle = "How often AI Job Finder scans for new jobs"

    def build(self) -> None:
        card = make_card()
        wrap = QVBoxLayout(card)
        wrap.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()

        self.enabled_check = QCheckBox("Run scheduled scans automatically")
        form.addRow(self.enabled_check)

        self.frequency_combo = QComboBox()
        for freq, label in _FREQUENCY_LABELS.items():
            self.frequency_combo.addItem(label, freq.value)
        form.addRow("Frequency", self.frequency_combo)

        wrap.addLayout(form)
        self.content_layout.addWidget(card)

        self.next_run_label = QLabel("")
        self.next_run_label.setStyleSheet("color: #6b7280; font-weight: 600;")
        self.content_layout.addWidget(self.next_run_label)

        note = QLabel(
            "The scan time and time zone come from the Send Time / Time Zone fields on the "
            "Email Settings page. Scheduling only runs while AI Job Finder is running - enable "
            "\"Start with Windows\" on the Settings page so it's already running in the "
            "background at the time you pick. Weekly runs fire every Monday."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280;")
        self.content_layout.addWidget(note)

        self.save_button = QPushButton("Save Schedule")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        self.content_layout.addWidget(self.save_button)

        run_now_button = QPushButton("Run Full Pipeline Now (scan + AI matching + email)")
        run_now_button.clicked.connect(self._run_now)
        self.content_layout.addWidget(run_now_button)

        self._load()
        self.refresh()

    def refresh(self) -> None:
        scheduler = get_scheduler()
        next_run = scheduler.next_run_time() if scheduler is not None else None
        if next_run is None:
            self.next_run_label.setText("Next scheduled run: not scheduled")
        else:
            self.next_run_label.setText(
                "Next scheduled run: " + next_run.strftime("%B %d, %Y — %I:%M %p %Z")
            )

    def _load(self) -> None:
        with session_scope() as session:
            repo = self.context.settings_repo
            self.enabled_check.setChecked(repo.get_bool(session, _KEY_PREFIX + "enabled", False))
            freq = repo.get(session, _KEY_PREFIX + "frequency", ScheduleFrequency.DAILY.value)
            idx = self.frequency_combo.findData(freq)
            self.frequency_combo.setCurrentIndex(max(idx, 0))

    def _save(self) -> None:
        with session_scope() as session:
            repo = self.context.settings_repo
            repo.set(session, _KEY_PREFIX + "enabled", "true" if self.enabled_check.isChecked() else "false")
            repo.set(session, _KEY_PREFIX + "frequency", self.frequency_combo.currentData())
        scheduler = get_scheduler()
        if scheduler is not None:
            scheduler.reload()
        self.refresh()
        QMessageBox.information(self, "Saved", "Schedule saved.")

    def _run_now(self) -> None:
        scheduler = get_scheduler()
        if scheduler is None:
            QMessageBox.warning(self, "Unavailable", "The scheduler isn't running.")
            return
        scheduler.run_now_async()
        QMessageBox.information(
            self, "Started",
            "Running the full pipeline in the background (scan, AI matching, and email if "
            "anything qualifies). Check the Dashboard and Logs page shortly for results.",
        )
