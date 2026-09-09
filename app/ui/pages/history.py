"""History (section 22): past scans. Wired to the real `scan_history`
table - populated by every "Scan Now" run (Phase 3, done)."""

from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QPushButton, QTableWidget, QTableWidgetItem

from sqlalchemy import select

from app.database.db import session_scope
from app.database.models import ScanHistory
from app.ui.base_page import BasePage

_COLUMNS = ["Started", "Trigger", "Status", "Retrieved", "New Jobs", "Excellent Matches", "Email Sent"]


class HistoryPage(BasePage):
    title = "History"
    subtitle = "Past scans and what they found"

    def build(self) -> None:
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        self.content_layout.addWidget(refresh_button)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.content_layout.addWidget(self.table)

        self.refresh()

    def refresh(self) -> None:
        with session_scope() as session:
            scans = session.scalars(select(ScanHistory).order_by(ScanHistory.started_at.desc()).limit(200)).all()

        self.table.setRowCount(len(scans))
        for r, scan in enumerate(scans):
            values = [
                scan.started_at.strftime("%Y-%m-%d %H:%M"),
                scan.trigger,
                scan.status,
                scan.jobs_retrieved,
                scan.new_jobs_found,
                scan.excellent_matches,
                "Yes" if scan.email_sent else "No",
            ]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
