"""Email Settings (sections 11-12, 29). SMTP configuration, preview, and
test/real sending are all fully functional."""

from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QTimeEdit,
    QVBoxLayout,
)

from app.core.constants import DEFAULT_MIN_EMAIL_SCORE
from app.core.scheduler import get_scheduler
from app.database.db import session_scope
from app.ui.base_page import BasePage, make_card

_KEY_PREFIX = "email."


class EmailSettingsPage(BasePage):
    title = "Email Settings"
    subtitle = "Where and when your daily job report is sent"

    def build(self) -> None:
        card = make_card()
        wrap = QVBoxLayout(card)
        wrap.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()
        form.setSpacing(10)

        self.recipient_input = QLineEdit()
        self.recipient_input.setPlaceholderText("you@example.com")
        form.addRow("Send report to", self.recipient_input)

        self.smtp_host_input = QLineEdit()
        self.smtp_host_input.setPlaceholderText("smtp.gmail.com")
        form.addRow("SMTP host", self.smtp_host_input)

        self.smtp_port_input = QSpinBox()
        self.smtp_port_input.setRange(1, 65535)
        self.smtp_port_input.setValue(587)
        form.addRow("SMTP port", self.smtp_port_input)

        self.smtp_username_input = QLineEdit()
        form.addRow("SMTP username", self.smtp_username_input)

        self.smtp_password_input = QLineEdit()
        self.smtp_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.smtp_password_input.setPlaceholderText("App-specific password (encrypted at rest)")
        form.addRow("SMTP app password", self.smtp_password_input)

        self.send_time_input = QTimeEdit()
        self.send_time_input.setDisplayFormat("hh:mm AP")
        form.addRow("Send time", self.send_time_input)

        self.timezone_combo = QComboBox()
        self.timezone_combo.addItems(
            ["America/Los_Angeles", "America/New_York", "America/Chicago", "America/Denver",
             "Europe/London", "Europe/Berlin", "Asia/Kolkata", "Asia/Singapore",
             "Australia/Sydney", "UTC"]
        )
        form.addRow("Time zone", self.timezone_combo)

        self.max_jobs_input = QSpinBox()
        self.max_jobs_input.setRange(1, 100)
        self.max_jobs_input.setValue(15)
        form.addRow("Max jobs per email", self.max_jobs_input)

        wrap.addLayout(form)
        self.content_layout.addWidget(card)

        button_row = QHBoxLayout()
        self.save_button = QPushButton("Save Email Settings")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        preview_button = QPushButton("Preview Daily Email")
        preview_button.clicked.connect(self._preview)
        test_button = QPushButton("Send Test Email")
        test_button.clicked.connect(self._send_test)
        button_row.addWidget(self.save_button)
        button_row.addWidget(preview_button)
        button_row.addWidget(test_button)
        button_row.addStretch(1)
        self.content_layout.addLayout(button_row)

        note = QLabel(
            "Passwords are encrypted before being written to the local database and are "
            "never stored in plain text or logged."
        )
        note.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.content_layout.addWidget(note)

        self._load()

    def _load(self) -> None:
        from app.database.db import session_scope
        from app.email.sender import resolve_email_config

        with session_scope() as session:
            repo = self.context.settings_repo
            # Populate every field with its EFFECTIVE current value (a
            # saved override if one exists, else whatever .env provides -
            # the exact same resolution `sender.py` uses to actually send)
            # rather than only the raw DB override. Loading just the raw
            # override left every field blank whenever the corresponding
            # AIJF_SMTP_*/AIJF_EMAIL_TO value came from .env instead, and
            # `_save()` always writes whatever's currently shown - so
            # saving the page for any reason (e.g. just changing the send
            # time) would silently overwrite a working .env configuration
            # with blanks and break email sending entirely.
            email_config = resolve_email_config(session, self.context)
            self.recipient_input.setText(email_config.recipient)
            self.smtp_host_input.setText(email_config.smtp_host)
            self.smtp_port_input.setValue(email_config.smtp_port)
            self.smtp_username_input.setText(email_config.smtp_username)
            self.smtp_password_input.setText(email_config.smtp_password)
            self.max_jobs_input.setValue(repo.get_int(session, _KEY_PREFIX + "max_jobs", 15))
            tz = repo.get(session, _KEY_PREFIX + "timezone", "America/Los_Angeles")
            idx = self.timezone_combo.findText(tz)
            if idx >= 0:
                self.timezone_combo.setCurrentIndex(idx)
            send_time = repo.get(session, _KEY_PREFIX + "send_time", "07:00")
            parsed_time = QTime.fromString(send_time, "HH:mm")
            self.send_time_input.setTime(parsed_time if parsed_time.isValid() else QTime(7, 0))

    def _save(self) -> None:
        from app.database.db import session_scope

        with session_scope() as session:
            repo = self.context.settings_repo
            repo.set(session, _KEY_PREFIX + "recipient", self.recipient_input.text())
            repo.set(session, _KEY_PREFIX + "smtp_host", self.smtp_host_input.text())
            repo.set(session, _KEY_PREFIX + "smtp_port", str(self.smtp_port_input.value()))
            repo.set(session, _KEY_PREFIX + "smtp_username", self.smtp_username_input.text())
            repo.set(
                session,
                _KEY_PREFIX + "smtp_password",
                self.smtp_password_input.text(),
                secret=True,
            )
            repo.set(session, _KEY_PREFIX + "max_jobs", str(self.max_jobs_input.value()))
            repo.set(session, _KEY_PREFIX + "timezone", self.timezone_combo.currentText())
            repo.set(session, _KEY_PREFIX + "send_time", self.send_time_input.time().toString("HH:mm"))
        scheduler = get_scheduler()
        if scheduler is not None:
            scheduler.reload()
        QMessageBox.information(self, "Saved", "Email settings saved.")

    def _preview(self) -> None:
        from app.email.report import build_preview_report

        with session_scope() as session:
            user = self.context.users_repo.get_or_create_default_user(
                session, self.context.config.email_to or "local-user@aijobfinder.local"
            )
            profile = self.context.candidate_profile_repo.get_current(session, user.id)
            prefs = self.context.preferences_repo.get_active(session, user.id)
            max_jobs = self.context.settings_repo.get_int(session, "email.max_jobs", prefs.max_email_jobs or 15)
            report = build_preview_report(
                session, self.context, profile.id,
                min_score=prefs.min_email_score or DEFAULT_MIN_EMAIL_SCORE,
                max_jobs=max_jobs,
            )

        dialog = QDialog(self)
        dialog.setWindowTitle("Preview: " + report.subject)
        dialog.resize(650, 700)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(report.html_body)
        layout.addWidget(browser)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()

    def _send_test(self) -> None:
        from app.email.sender import EmailSendError
        from app.email.service import send_test_email

        with session_scope() as session:
            try:
                send_test_email(session, self.context)
            except EmailSendError as exc:
                QMessageBox.critical(self, "Test Email Failed", str(exc))
                return
        QMessageBox.information(self, "Test Email Sent", "A test email was sent successfully.")
