"""Companies view: real aggregated stats from ingested jobs. Populates as
soon as any job source has been scanned (Phase 3) - never fabricated.
Preferred/excluded company lists are edited on the Job Search Profile
page, not here."""

from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem

from app.database.db import session_scope
from app.ui.base_page import BasePage, empty_state

_COLUMNS = ["Company", "Open Roles", "Remote", "Avg. Salary (where known)", "Latest Posting"]


class CompaniesPage(BasePage):
    title = "Companies"
    subtitle = "Companies appearing in your scanned job postings"

    def build(self) -> None:
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        self.content_layout.addWidget(refresh_button)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.content_layout.addWidget(self.table)

        self.empty_hint = empty_state(
            "No company data yet. Add and scan a job source (Job Sources page) to see "
            "companies here. Edit your preferred/excluded company lists on the Job Search "
            "Profile page."
        )
        self.content_layout.addWidget(self.empty_hint)

        self.refresh()

    def refresh(self) -> None:
        with session_scope() as session:
            stats = self.context.companies_repo.get_company_stats(session)

        self.table.setRowCount(len(stats))
        for r, company in enumerate(stats):
            if company.avg_salary_midpoint:
                salary_text = f"{company.salary_currency} {company.avg_salary_midpoint:,.0f} ({company.salary_known_count}/{company.job_count} listed)"
            else:
                salary_text = "Unknown"
            values = [
                company.company,
                str(company.job_count),
                f"{company.remote_count}/{company.job_count}",
                salary_text,
                company.latest_posted_date.strftime("%Y-%m-%d") if company.latest_posted_date else "",
            ]
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))

        self.table.setVisible(bool(stats))
        self.empty_hint.setVisible(not stats)
