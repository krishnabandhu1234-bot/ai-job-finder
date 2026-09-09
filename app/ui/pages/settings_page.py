"""General Settings + Privacy (sections 20, 25)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from app.core import startup
from app.ui.base_page import BasePage, make_card


class SettingsPage(BasePage):
    title = "Settings"
    subtitle = "Local data, privacy, and general configuration"

    def build(self) -> None:
        cfg = self.context.config

        general_card = make_card()
        general_layout = QVBoxLayout(general_card)
        general_layout.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()
        form.addRow("Demo mode", QLabel("On" if cfg.demo_mode else "Off"))
        form.addRow("Data directory", QLabel(str(cfg.data_dir)))
        form.addRow("Database file", QLabel(str(cfg.database_path)))
        form.addRow("Log level", QLabel(cfg.log_level))
        general_layout.addLayout(form)

        open_data_button = QPushButton("Open Data Folder")
        open_data_button.clicked.connect(lambda: os.startfile(cfg.data_dir))  # noqa: S606
        general_layout.addWidget(open_data_button)

        note = QLabel(
            "Demo mode is set via the .env file (or the AIJF_DEMO_MODE environment "
            "variable) before the app starts - see .env.example. AI provider selection "
            "and API keys have their own editor on the AI Settings page; email/SMTP "
            "settings are on the Email Settings page."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280; font-size: 12px;")
        general_layout.addWidget(note)

        self.content_layout.addWidget(general_card)
        self.content_layout.addWidget(self._updates_card())

        startup_card = make_card()
        startup_layout = QVBoxLayout(startup_card)
        startup_layout.setContentsMargins(20, 20, 20, 20)
        self.startup_check = QCheckBox("Start with Windows (run in the background from login)")
        self.startup_check.setEnabled(startup.is_supported())
        self.startup_check.setChecked(startup.is_supported() and startup.is_enabled())
        self.startup_check.toggled.connect(self._toggle_startup)
        startup_layout.addWidget(self.startup_check)
        startup_note = QLabel(
            "Needed for scheduled scans (see the Scheduler page) to run at your chosen time "
            "even before you've opened the app that day."
            if startup.is_supported()
            else "Only available in the installed application, not when running from source."
        )
        startup_note.setWordWrap(True)
        startup_note.setStyleSheet("color: #6b7280; font-size: 12px;")
        startup_layout.addWidget(startup_note)
        self.content_layout.addWidget(startup_card)

        privacy_card = make_card()
        privacy_layout = QVBoxLayout(privacy_card)
        privacy_layout.setContentsMargins(20, 20, 20, 20)
        privacy_title = QLabel("What data goes where")
        privacy_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        privacy_layout.addWidget(privacy_title)

        privacy_text = QLabel(
            "<b>Stored locally, never leaves this computer:</b> your uploaded resumes, "
            "the structured candidate profile, your job search preferences, every job "
            "posting collected, match scores and history, your feedback, and application "
            "tracking. All of it lives in the SQLite database shown above.<br><br>"
            "<b>Sent to an external AI provider (only if you configure one in AI "
            "Settings, and only for the small shortlist of top-ranked jobs):</b> the job "
            "title/description text, and relevant excerpts of your candidate profile "
            "(skills, experience summary) needed to judge fit. Your raw resume file is "
            "never uploaded.<br><br>"
            "Enable <b>Local-only mode</b> on the AI Settings page to disable all "
            "external AI calls and use local embeddings + rule-based scoring only."
        )
        privacy_text.setWordWrap(True)
        privacy_layout.addWidget(privacy_text)

        self.content_layout.addWidget(privacy_card)

    def _updates_card(self):
        """Shows whether a newer version of the app exists.

        The daily email carries this too (that's the channel the user
        actually reads); this is here for when they're already in the
        app. Both read the same `app.core.updates` check, so they can't
        disagree."""
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("App updates")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        self.update_status_label = QLabel("")
        self.update_status_label.setWordWrap(True)
        self.update_status_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(self.update_status_label)

        self.check_updates_button = QPushButton("Check for Updates Now")
        self.check_updates_button.clicked.connect(lambda: self._refresh_update_status(force=True))
        layout.addWidget(self.check_updates_button)

        self._refresh_update_status(force=False)
        return card

    def _refresh_update_status(self, force: bool) -> None:
        from app.core.updates import check_for_update
        from app.database.db import session_scope

        try:
            with session_scope() as session:
                info = check_for_update(session, self.context, force=force)
        except Exception as exc:  # never let a settings page fail over this
            self.update_status_label.setText(f"Could not check for updates: {exc}")
            return

        if info.update_available:
            text = f"🔔 {info.summary_line()}"
            if info.notes:
                text += f"\n\n{info.notes}"
            self.update_status_label.setText(text)
        elif not (self.context.config.update_manifest_url
                  or self._stored_manifest_url()):
            self.update_status_label.setText(
                f"You're running v{info.current_version}. Automatic update checking isn't "
                "configured for this build (no update manifest URL is set), so the app will "
                "never phone home - set AIJF_UPDATE_MANIFEST_URL if you want it to."
            )
        else:
            self.update_status_label.setText(info.summary_line())

    def _stored_manifest_url(self) -> str:
        from app.core.updates import SETTING_MANIFEST_URL
        from app.database.db import session_scope

        try:
            with session_scope() as session:
                return self.context.settings_repo.get(session, SETTING_MANIFEST_URL, "")
        except Exception:
            return ""

    def _toggle_startup(self, checked: bool) -> None:
        try:
            startup.set_enabled(checked)
        except RuntimeError as exc:
            self.startup_check.blockSignals(True)
            self.startup_check.setChecked(not checked)
            self.startup_check.blockSignals(False)
            QMessageBox.warning(self, "Couldn't Change Startup Setting", str(exc))
