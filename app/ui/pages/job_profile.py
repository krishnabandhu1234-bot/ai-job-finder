"""Job Search Profile (section 3): what the user is looking for.

Fully functional in Phase 1 - it's pure form-over-database CRUD against
`UserPreferences`, with no dependency on resume parsing or job data. This
profile is what later phases (hard filters, matching) will read.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.constants import (
    DEFAULT_MIN_EMAIL_SCORE,
    EmploymentType,
    Seniority,
    VisaPreference,
    WorkArrangement,
)
from app.database.db import session_scope
from app.ui.base_page import BasePage, list_to_text, make_card, text_to_list

_SENIORITY_LABELS = {
    Seniority.ENTRY: "Entry",
    Seniority.MID: "Mid",
    Seniority.SENIOR: "Senior",
    Seniority.STAFF: "Staff",
    Seniority.PRINCIPAL: "Principal",
    Seniority.LEAD: "Lead",
    Seniority.MANAGER: "Manager",
    Seniority.DIRECTOR: "Director",
    Seniority.VP: "VP",
    Seniority.EXECUTIVE: "Executive",
}

_EMPLOYMENT_LABELS = {
    EmploymentType.FULL_TIME: "Full-time",
    EmploymentType.PART_TIME: "Part-time",
    EmploymentType.CONTRACT: "Contract",
    EmploymentType.TEMPORARY: "Temporary",
    EmploymentType.INTERNSHIP: "Internship",
}

_VISA_LABELS = {
    VisaPreference.NOT_SPECIFIED: "Not specified",
    VisaPreference.US_AUTHORIZED_NO_SPONSORSHIP: "US work authorized — no sponsorship needed",
    VisaPreference.SPONSORSHIP_REQUIRED: "Sponsorship required",
    VisaPreference.NO_SPONSORSHIP_NEEDED_ANY_COUNTRY: "No sponsorship needed (any country)",
    VisaPreference.WILLING_TO_RELOCATE: "Willing to relocate",
    VisaPreference.REMOTE_ONLY: "Remote only",
}


_list_to_text = list_to_text
_text_to_list = text_to_list


class JobProfilePage(BasePage):
    title = "Job Search Profile"
    subtitle = "Tell AI Job Finder exactly what you're looking for"

    def build(self) -> None:
        card = make_card()
        form_wrap = QVBoxLayout(card)
        form_wrap.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.titles_input = QLineEdit()
        self.titles_input.setPlaceholderText("Thermal Engineer, CFD Engineer, ML Engineer, ...")
        form.addRow("Job titles", self.titles_input)

        self.locations_input = QLineEdit()
        self.locations_input.setPlaceholderText("Worldwide, United States, Remote Worldwide, ...")
        form.addRow("Locations", self.locations_input)

        self.work_arrangement_combo = QComboBox()
        for wa in WorkArrangement:
            self.work_arrangement_combo.addItem(wa.value.capitalize(), wa.value)
        form.addRow("Work arrangement", self.work_arrangement_combo)

        seniority_row = QGridLayout()
        self.seniority_checks: dict[str, QCheckBox] = {}
        for i, (sen, label) in enumerate(_SENIORITY_LABELS.items()):
            cb = QCheckBox(label)
            self.seniority_checks[sen.value] = cb
            seniority_row.addWidget(cb, i // 4, i % 4)
        seniority_widget = QWidget()
        seniority_widget.setLayout(seniority_row)
        form.addRow("Seniority", seniority_widget)

        salary_row = QGridLayout()
        self.salary_min_input = QDoubleSpinBox()
        self.salary_min_input.setRange(0, 10_000_000)
        self.salary_min_input.setSingleStep(5000)
        self.salary_min_input.setPrefix("Min ")
        self.salary_max_input = QDoubleSpinBox()
        self.salary_max_input.setRange(0, 10_000_000)
        self.salary_max_input.setSingleStep(5000)
        self.salary_max_input.setPrefix("Max ")
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(["USD", "EUR", "GBP", "INR", "CAD", "AUD", "SGD", "JPY"])
        salary_row.addWidget(self.salary_min_input, 0, 0)
        salary_row.addWidget(self.salary_max_input, 0, 1)
        salary_row.addWidget(self.currency_combo, 0, 2)
        salary_widget = QWidget()
        salary_widget.setLayout(salary_row)
        form.addRow("Compensation", salary_widget)
        form.addRow(
            "", QLabel("Jobs with no listed salary are never rejected — they're marked \"Unknown\".")
        )

        self.industries_input = QLineEdit()
        self.industries_input.setPlaceholderText("Aerospace, Semiconductors, Climate Tech, ...")
        form.addRow("Industries", self.industries_input)

        self.preferred_companies_input = QLineEdit()
        self.preferred_companies_input.setPlaceholderText("NVIDIA, Apple, SpaceX, ...")
        form.addRow("Preferred companies", self.preferred_companies_input)

        self.excluded_companies_input = QLineEdit()
        self.excluded_companies_input.setPlaceholderText("Companies to never show")
        form.addRow("Excluded companies", self.excluded_companies_input)

        self.required_keywords_input = QLineEdit()
        form.addRow("Required keywords", self.required_keywords_input)
        self.preferred_keywords_input = QLineEdit()
        form.addRow("Preferred keywords", self.preferred_keywords_input)
        self.excluded_keywords_input = QLineEdit()
        form.addRow("Excluded keywords", self.excluded_keywords_input)

        employment_row = QGridLayout()
        self.employment_checks: dict[str, QCheckBox] = {}
        for i, (et, label) in enumerate(_EMPLOYMENT_LABELS.items()):
            cb = QCheckBox(label)
            self.employment_checks[et.value] = cb
            employment_row.addWidget(cb, 0, i)
        employment_widget = QWidget()
        employment_widget.setLayout(employment_row)
        form.addRow("Employment type", employment_widget)

        self.visa_combo = QComboBox()
        for vp in VisaPreference:
            self.visa_combo.addItem(_VISA_LABELS[vp], vp.value)
        form.addRow("Visa / work authorization", self.visa_combo)

        self.countries_input = QLineEdit()
        self.countries_input.setPlaceholderText("Countries you're willing to work in")
        form.addRow("Countries willing to work in", self.countries_input)

        self.priorities_text = QTextEdit()
        self.priorities_text.setPlaceholderText(
            "What matters most to you? e.g. \"Prioritize deep technical roles over people "
            "management, strongly prefer hardware/simulation work, salary matters less than fit.\""
        )
        self.priorities_text.setFixedHeight(70)
        form.addRow("What matters most", self.priorities_text)

        self.min_score_input = QDoubleSpinBox()
        self.min_score_input.setRange(0, 100)
        self.min_score_input.setValue(DEFAULT_MIN_EMAIL_SCORE)
        form.addRow("Minimum match score for email", self.min_score_input)

        form_wrap.addLayout(form)
        self.content_layout.addWidget(card)

        save_row = QVBoxLayout()
        self.save_button = QPushButton("Save Job Search Profile")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        save_row.addWidget(self.save_button)
        self.content_layout.addLayout(save_row)

        self._load()

    def _load(self) -> None:
        with session_scope() as session:
            user = self.context.users_repo.get_or_create_default_user(
                session, self.context.config.email_to or "local-user@aijobfinder.local"
            )
            prefs = self.context.preferences_repo.get_active(session, user.id)

            self.titles_input.setText(_list_to_text(prefs.target_titles))
            self.locations_input.setText(_list_to_text(prefs.locations))
            idx = self.work_arrangement_combo.findData(prefs.work_arrangement or "any")
            self.work_arrangement_combo.setCurrentIndex(max(idx, 0))
            for value in prefs.seniority_levels or []:
                if value in self.seniority_checks:
                    self.seniority_checks[value].setChecked(True)
            self.salary_min_input.setValue(prefs.salary_min or 0)
            self.salary_max_input.setValue(prefs.salary_max or 0)
            currency_idx = self.currency_combo.findText(prefs.salary_currency or "USD")
            self.currency_combo.setCurrentIndex(max(currency_idx, 0))
            self.industries_input.setText(_list_to_text(prefs.industries))
            self.preferred_companies_input.setText(_list_to_text(prefs.preferred_companies))
            self.excluded_companies_input.setText(_list_to_text(prefs.excluded_companies))
            self.required_keywords_input.setText(_list_to_text(prefs.required_keywords))
            self.preferred_keywords_input.setText(_list_to_text(prefs.preferred_keywords))
            self.excluded_keywords_input.setText(_list_to_text(prefs.excluded_keywords))
            for value in prefs.employment_types or []:
                if value in self.employment_checks:
                    self.employment_checks[value].setChecked(True)
            visa_idx = self.visa_combo.findData(prefs.visa_preference or "not_specified")
            self.visa_combo.setCurrentIndex(max(visa_idx, 0))
            self.countries_input.setText(_list_to_text(prefs.countries_willing_to_work))
            self.priorities_text.setPlainText(prefs.priorities_text or "")
            self.min_score_input.setValue(
                prefs.min_email_score if prefs.min_email_score is not None else DEFAULT_MIN_EMAIL_SCORE
            )

    def _save(self) -> None:
        with session_scope() as session:
            user = self.context.users_repo.get_or_create_default_user(
                session, self.context.config.email_to or "local-user@aijobfinder.local"
            )
            prefs = self.context.preferences_repo.get_active(session, user.id)
            self.context.preferences_repo.save(
                session,
                prefs,
                target_titles=_text_to_list(self.titles_input.text()),
                locations=_text_to_list(self.locations_input.text()),
                work_arrangement=self.work_arrangement_combo.currentData(),
                seniority_levels=[v for v, cb in self.seniority_checks.items() if cb.isChecked()],
                salary_min=self.salary_min_input.value() or None,
                salary_max=self.salary_max_input.value() or None,
                salary_currency=self.currency_combo.currentText(),
                industries=_text_to_list(self.industries_input.text()),
                preferred_companies=_text_to_list(self.preferred_companies_input.text()),
                excluded_companies=_text_to_list(self.excluded_companies_input.text()),
                required_keywords=_text_to_list(self.required_keywords_input.text()),
                preferred_keywords=_text_to_list(self.preferred_keywords_input.text()),
                excluded_keywords=_text_to_list(self.excluded_keywords_input.text()),
                employment_types=[v for v, cb in self.employment_checks.items() if cb.isChecked()],
                visa_preference=self.visa_combo.currentData(),
                countries_willing_to_work=_text_to_list(self.countries_input.text()),
                priorities_text=self.priorities_text.toPlainText(),
                min_email_score=int(self.min_score_input.value()),
            )
        QMessageBox.information(self, "Saved", "Your job search profile has been saved.")
