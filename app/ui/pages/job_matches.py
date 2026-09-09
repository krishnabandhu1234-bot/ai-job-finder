"""Job Matches (section 15): every job the AI has evaluated, with working
filters/sorting and a detail view (section 15: "Full job information + AI
match analysis + resume evidence + potential gaps + apply button") that
also exposes the feedback loop (section 16) and application tracker
(section 31)."""

from __future__ import annotations

import html
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.constants import ApplicationStatus, FeedbackRating
from app.database.db import session_scope
from app.database.models import Job, JobMatch
from app.ui.base_page import BasePage, empty_state

_COLUMNS = ["Match", "Title", "Company", "Location", "Remote", "Salary", "Posted", "Source", "Status"]

# Score bands, mirroring `MatchCategory`. A wall of identical grey rows is
# hard to scan; the colour makes "which of these is actually worth
# opening" obvious at a glance, which is the page's whole job.
_SCORE_COLORS = [
    (90, "#7c3aed"),  # excellent+
    (85, "#2563eb"),  # strong
    (75, "#059669"),  # good
    (60, "#d97706"),  # possible
]
_SCORE_COLOR_DEFAULT = "#6b7280"

# Feedback ratings that mean "stop showing me this". Kept together so the
# hide-filter and any future suppression logic agree on what counts.
_REJECTED_RATINGS = {FeedbackRating.NOT_INTERESTED.value, FeedbackRating.POOR.value,
                     FeedbackRating.NEVER_SHOW_SIMILAR.value}


def _score_color(score: float) -> str:
    for threshold, color in _SCORE_COLORS:
        if score >= threshold:
            return color
    return _SCORE_COLOR_DEFAULT

_SORT_OPTIONS = {
    "Best match": (JobMatch.overall_score, True),
    "Newest": (Job.first_seen_at, True),
    "Salary": (Job.salary_max, True),
    "Company": (Job.company, False),
}

_FEEDBACK_BUTTONS = [
    ("Excellent", FeedbackRating.EXCELLENT.value),
    ("Good", FeedbackRating.GOOD.value),
    ("Not interested", FeedbackRating.NOT_INTERESTED.value),
    ("Poor match", FeedbackRating.POOR.value),
    ("Never show similar", FeedbackRating.NEVER_SHOW_SIMILAR.value),
]

_APPLICATION_STATUSES = [s.value for s in ApplicationStatus]


def _e(value: str | None) -> str:
    """Escapes a string for safe interpolation into a QLabel's rich-text
    (HTML) content. `value` may ultimately derive from an untrusted job
    posting (title, company, location, ...) or LLM analysis of one
    (section 24) - Qt's rich-text renderer isn't a full browser/no script
    execution, but unescaped `<`/`&` etc. can still break the intended
    layout or render unintended markup (e.g. a fake bold/link)."""
    return html.escape(value or "")


class JobMatchesPage(BasePage):
    title = "Job Matches"
    subtitle = "Every job the AI has evaluated for you — double-click a row for full details"

    def build(self) -> None:
        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search title or company...")
        self.search_input.textChanged.connect(self.refresh)
        self.min_score_combo = QComboBox()
        self.min_score_combo.addItems(["Any score", "60+", "75+", "85+", "90+", "95+"])
        self.min_score_combo.currentIndexChanged.connect(self.refresh)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(list(_SORT_OPTIONS.keys()))
        self.sort_combo.currentIndexChanged.connect(self.refresh)
        # Without this, marking a job "not interested" changes nothing you
        # can see, which makes the feedback buttons feel pointless.
        self.hide_rejected_check = QCheckBox("Hide ones I've passed on")
        self.hide_rejected_check.setChecked(True)
        self.hide_rejected_check.stateChanged.connect(self.refresh)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)

        filters.addWidget(self.search_input, 2)
        filters.addWidget(QLabel("Min score:"))
        filters.addWidget(self.min_score_combo)
        filters.addWidget(QLabel("Sort:"))
        filters.addWidget(self.sort_combo)
        filters.addWidget(self.hide_rejected_check)
        filters.addWidget(refresh_button)
        self.content_layout.addLayout(filters)

        self.result_count_label = QLabel("")
        self.result_count_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.content_layout.addWidget(self.result_count_label)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._open_selected_detail)
        self.content_layout.addWidget(self.table)

        self.empty_hint = QLabel(
            "No matches yet. Use \"Scan Now\" on the Dashboard to fetch postings and run AI matching."
        )
        self.empty_hint.setStyleSheet("color: #6b7280; padding: 12px;")
        self.content_layout.addWidget(self.empty_hint)

        self._match_ids: list[int] = []
        self.refresh()

    def refresh(self) -> None:
        min_score_text = self.min_score_combo.currentText()
        min_score = 0.0 if min_score_text == "Any score" else float(min_score_text.rstrip("+"))
        search_text = self.search_input.text().strip().lower()
        sort_column, descending = _SORT_OPTIONS[self.sort_combo.currentText()]

        with session_scope() as session:
            query = (
                select(JobMatch, Job)
                .join(Job, JobMatch.job_id == Job.id)
                .options(joinedload(Job.source))
                .where(JobMatch.overall_score >= min_score)
            )
            order = sort_column.desc() if descending else sort_column.asc()
            query = query.order_by(order).limit(500)
            rows = session.execute(query).all()

            if search_text:
                rows = [
                    (m, j) for m, j in rows
                    if search_text in (j.title or "").lower() or search_text in (j.company or "").lower()
                ]

            total_before_hiding = len(rows)
            statuses = self._status_labels(session, [m.id for m, _ in rows], [j.id for _, j in rows])
            if self.hide_rejected_check.isChecked():
                rows = [(m, j) for m, j in rows if m.id not in self._rejected_match_ids]

            self._match_ids = [m.id for m, _ in rows]
            self.table.setRowCount(len(rows))
            for r, (match, job) in enumerate(rows):
                values = [
                    f"{match.overall_score:.0f}%",
                    job.title,
                    job.company,
                    job.location_raw,
                    "Yes" if job.remote else "No",
                    self._format_salary(job),
                    job.posted_date.strftime("%Y-%m-%d") if job.posted_date else "",
                    job.source.name if job.source else "",
                    statuses.get(match.id, ""),
                ]
                for c, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setData(Qt.ItemDataRole.UserRole, match.id)
                    if c == 0:
                        item.setForeground(QColor(_score_color(match.overall_score)))
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    self.table.setItem(r, c, item)

            hidden = total_before_hiding - len(rows)
            self.result_count_label.setText(
                f"Showing {len(rows)} match(es)"
                + (f" — {hidden} hidden because you passed on them" if hidden else "")
            )

        self.empty_hint.setVisible(self.table.rowCount() == 0)

    def _status_labels(self, session, match_ids: list[int], job_ids: list[int]) -> dict[int, str]:
        """A short "where am I with this one" label per match.

        Application status wins over feedback when both exist - having
        actually applied is the more informative fact. Also records which
        matches count as rejected, for the hide filter."""
        from app.database.models import ApplicationHistory, Feedback

        self._rejected_match_ids: set[int] = set()
        labels: dict[int, str] = {}
        if not match_ids:
            return labels

        feedback_rows = session.execute(
            select(Feedback).where(Feedback.job_match_id.in_(match_ids))
        ).scalars().all()
        # Latest feedback per match wins - the user may have changed
        # their mind, and the newest opinion is the real one.
        for row in sorted(feedback_rows, key=lambda f: f.created_at or 0):
            labels[row.job_match_id] = row.rating.replace("_", " ").capitalize()
            if row.rating in _REJECTED_RATINGS:
                self._rejected_match_ids.add(row.job_match_id)
            else:
                self._rejected_match_ids.discard(row.job_match_id)

        if job_ids:
            job_to_match = {j: m for m, j in zip(match_ids, job_ids)}
            application_rows = session.execute(
                select(ApplicationHistory).where(ApplicationHistory.job_id.in_(job_ids))
            ).scalars().all()
            for row in application_rows:
                match_id = job_to_match.get(row.job_id)
                if match_id is not None:
                    labels[match_id] = row.status.replace("_", " ").capitalize()
        return labels

    def _open_selected_detail(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._match_ids):
            return
        dialog = MatchDetailDialog(self.context, self._match_ids[row], self)
        dialog.exec()
        self.refresh()

    @staticmethod
    def _format_salary(job: Job) -> str:
        if job.salary_min is None and job.salary_max is None:
            return "Unknown"
        currency = job.salary_currency or ""
        if job.salary_min is not None and job.salary_max is not None:
            return f"{currency} {job.salary_min:,.0f}-{job.salary_max:,.0f}"
        value = job.salary_min if job.salary_min is not None else job.salary_max
        return f"{currency} {value:,.0f}"


class MatchDetailDialog(QDialog):
    """Full match detail (section 15): job info, AI analysis with
    evidence-based strengths/gaps, feedback buttons (section 16), an
    application-status tracker (section 31), and an Apply link that
    always points at the real posting (section 32 - never fabricated)."""

    def __init__(self, context, job_match_id: int, parent=None):
        super().__init__(parent)
        self.context = context
        self.job_match_id = job_match_id
        self.setWindowTitle("Match Details")
        self.resize(560, 640)
        self._build()

    def _build(self) -> None:
        with session_scope() as session:
            match = session.get(JobMatch, self.job_match_id)
            job = session.get(Job, match.job_id) if match else None
            app_row = self.context.applications_repo.get_for_job(session, job.id) if job else None
            source_name = job.source.name if job and job.source else "Unknown"

        layout = QVBoxLayout(self)
        if match is None or job is None:
            layout.addWidget(QLabel("This match no longer exists."))
            return

        header = QLabel(f"<b style='font-size:16px;'>{_e(job.title)}</b><br>{_e(job.company)}")
        header.setWordWrap(True)
        layout.addWidget(header)

        score_label = QLabel(
            f"<span style='font-size:22px;font-weight:800;color:#3457d5;'>{match.overall_score:.0f}%</span> "
            f"&nbsp; {_e(match.category.title())} match"
        )
        layout.addWidget(score_label)

        details = QLabel(
            f"Location: {_e(job.location_raw) or 'Unspecified'}{' (Remote)' if job.remote else ''}<br>"
            f"Employment type: {_e(job.employment_type) or 'Unspecified'}<br>"
            f"Salary: {_e(JobMatchesPage._format_salary(job))}<br>"
            f"Posted: {job.posted_date.strftime('%Y-%m-%d') if job.posted_date else 'Unknown'}<br>"
            f"Source: {_e(source_name)}"
        )
        details.setWordWrap(True)
        layout.addWidget(details)

        if match.strengths:
            layout.addWidget(self._section_label("Why this matches", match.strengths, "#059669"))
        if match.gaps:
            layout.addWidget(self._section_label("Potential gaps", match.gaps, "#d97706"))
        if match.concerns:
            layout.addWidget(self._section_label("Concerns", match.concerns, "#dc2626"))
        if match.reasoning:
            reasoning_label = QLabel(f"<i>{_e(match.reasoning)}</i>")
            reasoning_label.setWordWrap(True)
            layout.addWidget(reasoning_label)

        if job.apply_url:
            apply_button = QPushButton("Apply Now")
            apply_button.setObjectName("primaryButton")
            apply_button.clicked.connect(lambda: webbrowser.open(job.apply_url))
            layout.addWidget(apply_button)
        else:
            layout.addWidget(QLabel("No apply link was provided by the source for this posting."))

        layout.addWidget(QLabel("<b>Application status</b>"))
        status_combo = QComboBox()
        status_combo.addItems(_APPLICATION_STATUSES)
        if app_row is not None and app_row.status in _APPLICATION_STATUSES:
            status_combo.setCurrentIndex(_APPLICATION_STATUSES.index(app_row.status))
        status_combo.currentTextChanged.connect(lambda status: self._set_application_status(job.id, status))
        layout.addWidget(status_combo)

        layout.addWidget(QLabel("<b>Feedback</b> (helps AI Job Finder learn what you like)"))
        feedback_row = QHBoxLayout()
        for label, rating in _FEEDBACK_BUTTONS:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked, r=rating: self._give_feedback(r))
            feedback_row.addWidget(button)
        layout.addLayout(feedback_row)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    @staticmethod
    def _section_label(title: str, items: list[str], color: str) -> QLabel:
        # `items` (strengths/gaps/concerns) may ultimately be derived from
        # LLM analysis of untrusted job-posting text (section 24) - never
        # interpolate them into rich-text HTML unescaped.
        bullets = "".join(f"<li>{_e(i)}</li>" for i in items)
        label = QLabel(f"<b style='color:{color};'>{_e(title)}:</b><ul style='margin-top:2px;'>{bullets}</ul>")
        label.setWordWrap(True)
        return label

    def _give_feedback(self, rating: str) -> None:
        with session_scope() as session:
            self.context.feedback_repo.create(session, self.job_match_id, rating)
        QMessageBox.information(self, "Feedback Recorded", "Thanks — this will help improve future matches.")

    def _set_application_status(self, job_id: int, status: str) -> None:
        with session_scope() as session:
            self.context.applications_repo.set_status(session, job_id, status)
