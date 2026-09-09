"""Resumes (section 2). Fully functional: upload PDF/DOCX/TXT, parse and
extract a structured candidate profile, merge multiple resumes, and let
the user review/edit everything before it's used for matching (Phase 4+).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.core.constants import Seniority
from app.core.resume_ai_worker import start_resume_ai_read
from app.database.db import session_scope
from app.resume.extractor import extract_resume
from app.resume.parser import ResumeParseError, parse_resume_file
from app.resume.profile_autofill import autofill_preferences_from_profile
from app.resume.profile_builder import build_candidate_profile_fields
from app.ui.base_page import BasePage, empty_state, list_to_text, make_card, text_to_list

logger = logging.getLogger(__name__)

_EMPTY_PROFILE_FIELDS = {
    "source_resume_ids": [],
    "target_roles": [],
    "seniority": "",
    "years_experience": 0.0,
    "technical_skills": [],
    "programming_languages": [],
    "software": [],
    "domain_expertise": [],
    "leadership": [],
    "education": [],
    "certifications": [],
    "companies": [],
    "locations": [],
    "achievements": [],
    "publications": [],
    "projects": [],
}

_PROFILE_LIST_FIELDS = [
    ("technical_skills", "Technical skills"),
    ("programming_languages", "Programming languages"),
    ("software", "Software / tools"),
    ("domain_expertise", "Domain expertise"),
    ("industries", "Industries"),
    ("certifications", "Certifications"),
    ("companies", "Companies"),
    ("education", "Education"),
    ("leadership", "Leadership experience"),
]


class ResumesPage(BasePage):
    title = "Resumes"
    subtitle = "Upload one or more resumes to build your candidate profile"

    def build(self) -> None:
        upload_row = QHBoxLayout()
        upload_button = QPushButton("Upload Resume (PDF, DOCX, TXT)")
        upload_button.setObjectName("primaryButton")
        upload_button.clicked.connect(self._upload_resumes)
        upload_row.addWidget(upload_button)
        upload_row.addStretch(1)
        self.content_layout.addLayout(upload_row)

        self.content_layout.addWidget(self._ai_reading_card())

        resumes_title = QLabel("UPLOADED RESUMES")
        resumes_title.setStyleSheet("font-weight: 600; color: #6b7280; letter-spacing: 1px;")
        self.content_layout.addWidget(resumes_title)

        self.resumes_container = QVBoxLayout()
        self.content_layout.addLayout(self.resumes_container)

        profile_title = QLabel("CANDIDATE PROFILE")
        profile_title.setStyleSheet("font-weight: 600; color: #6b7280; letter-spacing: 1px;")
        self.content_layout.addWidget(profile_title)

        self.profile_container = QVBoxLayout()
        self.content_layout.addLayout(self.profile_container)

        self.profile_inputs: dict = {}
        self.refresh()

    def _ai_reading_card(self):
        """Opt-in AI resume reading.

        This is the one feature in the app that sends resume text off the
        machine, so the card says so in plain language rather than hiding
        it behind a friendly label - see `app/resume/llm_extractor.py`."""
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("Read my resume with AI (optional)")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        explanation = QLabel(
            "Your resume is always read offline by a built-in rule-based parser, which needs no "
            "API key and sends nothing anywhere. That parser can only recognize skills it already "
            "knows by name.\n\n"
            "Turning this on additionally has your configured AI provider read the resume, which "
            "understands it far better - inferring the roles you're a strong candidate for, your "
            "seniority, industries and domain expertise, even when the resume never uses those "
            "words. Results are merged with the offline parse and stay fully editable below "
            "before anything is saved.\n\n"
            "⚠ Unless you've picked a \"local\" model (which never sends anything anywhere), this "
            "sends your resume's TEXT to that provider (Anthropic, OpenAI or Google). It's the only "
            "part of this app that does. It's off unless you press the button, and it is disabled "
            "entirely while \"Local-only mode\" is on in AI Settings."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(explanation)

        row = QHBoxLayout()
        self.ai_read_button = QPushButton("Read My Resume with AI")
        self.ai_read_button.clicked.connect(self._start_ai_read)
        row.addWidget(self.ai_read_button)
        self.ai_read_status = QLabel("")
        self.ai_read_status.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.ai_read_status.setWordWrap(True)
        row.addWidget(self.ai_read_status, 1)
        layout.addLayout(row)

        self._ai_thread = None
        self._ai_worker = None
        return card

    def _start_ai_read(self) -> None:
        with session_scope() as session:
            user = self._get_user(session)
            resumes = self.context.resumes_repo.list_for_user(session, user.id)
            has_text = any(r.raw_text for r in resumes)

        if not has_text:
            QMessageBox.information(
                self, "No Resume Yet",
                "Upload a resume first - there's no text for the AI to read.",
            )
            return

        self.ai_read_button.setEnabled(False)
        self.ai_read_button.setText("Reading...")
        self.ai_read_status.setText("Sending resume text to your AI provider...")
        self._ai_thread, self._ai_worker = start_resume_ai_read(
            self,
            on_progress=self.ai_read_status.setText,
            on_finished=self._on_ai_read_finished,
            on_failed=self._on_ai_read_failed,
        )

    def _on_ai_read_finished(self, summary: str) -> None:
        self.ai_read_button.setEnabled(True)
        self.ai_read_button.setText("Read My Resume with AI")
        self.ai_read_status.setText("Done - review the profile below.")
        self.refresh()
        QMessageBox.information(self, "AI Reading Complete", summary)

    def _on_ai_read_failed(self, error: str) -> None:
        self.ai_read_button.setEnabled(True)
        self.ai_read_button.setText("Read My Resume with AI")
        self.ai_read_status.setText("")
        QMessageBox.warning(self, "AI Reading Could Not Run", error)

    def refresh(self) -> None:
        self._reload_resumes_list()
        self._reload_profile_editor()

    # --- shared helpers -----------------------------------------------

    def _get_user(self, session):
        return self.context.users_repo.get_or_create_default_user(
            session, self.context.config.email_to or "local-user@aijobfinder.local"
        )

    # --- upload / parse -------------------------------------------------

    def _upload_resumes(self) -> None:
        selected_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select resume file(s)",
            str(Path.home()),
            "Resumes (*.pdf *.docx *.txt);;All Files (*.*)",
        )
        if not selected_paths:
            return

        errors: list[str] = []
        for path_str in selected_paths:
            error = self._process_upload(Path(path_str))
            if error:
                errors.append(error)

        self._rebuild_candidate_profile()
        self.refresh()

        if errors:
            QMessageBox.warning(self, "Some Files Had Issues", "\n\n".join(errors))

    def _process_upload(self, source_path: Path) -> str | None:
        """Copies the file into the app's resume store and parses it.
        Returns an error message on failure, or None on success - the
        Resume row is still created either way (with parse_error set) so
        the user can see and remove failed uploads rather than them
        vanishing silently."""
        dest_dir = self.context.config.resumes_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{uuid4().hex}_{source_path.name}"

        try:
            shutil.copy2(source_path, dest_path)
        except OSError as exc:
            logger.error("Could not copy uploaded resume %s: %s", source_path, exc)
            return f"{source_path.name}: could not copy file ({exc})"

        raw_text = ""
        parse_error: str | None = None
        try:
            parsed = parse_resume_file(dest_path)
            raw_text = parsed.text
            if parsed.warnings:
                logger.warning("%s parsed with warnings: %s", source_path.name, "; ".join(parsed.warnings))
                if not raw_text:
                    parse_error = parsed.warnings[0]
        except ResumeParseError as exc:
            parse_error = str(exc)
            logger.error("Failed to parse %s: %s", source_path.name, exc)

        with session_scope() as session:
            user = self._get_user(session)
            self.context.resumes_repo.create(
                session,
                user_id=user.id,
                filename=source_path.name,
                file_path=str(dest_path),
                file_type=dest_path.suffix.lstrip(".").lower(),
                raw_text=raw_text,
                parse_error=parse_error,
            )

        return f"{source_path.name}: {parse_error}" if parse_error else None

    def _rebuild_candidate_profile(self) -> None:
        with session_scope() as session:
            user = self._get_user(session)
            resumes = self.context.resumes_repo.list_for_user(session, user.id)
            extracted_pairs = [
                (resume.id, extract_resume(resume.raw_text)) for resume in resumes if resume.raw_text
            ]
            profile = self.context.candidate_profile_repo.get_current(session, user.id)
            if not extracted_pairs:
                # Every resume was removed (or none has parsed text yet) - clear the
                # profile rather than silently keeping a stale one that no longer
                # has any source resume behind it (it would otherwise keep being
                # used for AI matching indefinitely).
                self.context.candidate_profile_repo.save(session, profile, **_EMPTY_PROFILE_FIELDS)
                return
            fields = build_candidate_profile_fields(extracted_pairs)
            self.context.candidate_profile_repo.save(session, profile, **fields)

    # --- resumes list -----------------------------------------------------

    def _reload_resumes_list(self) -> None:
        while self.resumes_container.count():
            item = self.resumes_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        with session_scope() as session:
            user = self._get_user(session)
            resumes = self.context.resumes_repo.list_for_user(session, user.id)

        if not resumes:
            self.resumes_container.addWidget(
                empty_state("No resumes uploaded yet. Upload a PDF, DOCX, or TXT resume to get started.")
            )
            return

        for resume in resumes:
            self.resumes_container.addWidget(self._resume_row(resume))

    def _resume_row(self, resume):
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)

        info = QVBoxLayout()
        name_label = QLabel(resume.filename)
        name_label.setStyleSheet("font-weight: 600;")
        info.addWidget(name_label)

        if resume.parse_error:
            status_text = f"Uploaded {resume.uploaded_at.strftime('%Y-%m-%d %H:%M')} — {resume.parse_error}"
            status_color = "#dc2626"
        else:
            word_count = len(resume.raw_text.split()) if resume.raw_text else 0
            status_text = f"Uploaded {resume.uploaded_at.strftime('%Y-%m-%d %H:%M')} — {word_count} words extracted"
            status_color = "#6b7280"
        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"color: {status_color};")
        status_label.setWordWrap(True)
        info.addWidget(status_label)
        layout.addLayout(info, 1)

        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(lambda _checked=False, rid=resume.id: self._remove_resume(rid))
        layout.addWidget(remove_button)
        return card

    def _remove_resume(self, resume_id: int) -> None:
        with session_scope() as session:
            self.context.resumes_repo.deactivate(session, resume_id)
        self._rebuild_candidate_profile()
        self.refresh()

    # --- candidate profile editor -----------------------------------------

    def _reload_profile_editor(self) -> None:
        while self.profile_container.count():
            item = self.profile_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.profile_inputs = {}

        with session_scope() as session:
            user = self._get_user(session)
            has_resumes = bool(self.context.resumes_repo.list_for_user(session, user.id))
            profile = self.context.candidate_profile_repo.get_current(session, user.id)
            profile_data = self._profile_to_dict(profile)

        if not has_resumes:
            self.profile_container.addWidget(
                empty_state(
                    "Your structured candidate profile will appear here once you upload a resume. "
                    "You'll be able to review and edit everything extracted before it's used for matching."
                )
            )
            return

        card = make_card()
        form_wrap = QVBoxLayout(card)
        form_wrap.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()
        form.setSpacing(10)

        self.profile_inputs["target_roles"] = QLineEdit(list_to_text(profile_data["target_roles"]))
        form.addRow("Target roles", self.profile_inputs["target_roles"])

        seniority_combo = QComboBox()
        for s in Seniority:
            seniority_combo.addItem(s.value.capitalize(), s.value)
        idx = seniority_combo.findData(profile_data["seniority"] or "any")
        seniority_combo.setCurrentIndex(max(idx, 0))
        self.profile_inputs["seniority"] = seniority_combo
        form.addRow("Seniority (auto-detected — please check)", seniority_combo)

        years_input = QDoubleSpinBox()
        years_input.setRange(0, 60)
        years_input.setSingleStep(0.5)
        years_input.setValue(profile_data["years_experience"])
        self.profile_inputs["years_experience"] = years_input
        form.addRow("Years of experience (auto-detected — please check)", years_input)

        for field_name, label in _PROFILE_LIST_FIELDS:
            line_edit = QLineEdit(list_to_text(profile_data[field_name]))
            self.profile_inputs[field_name] = line_edit
            form.addRow(label, line_edit)

        achievements_edit = QTextEdit()
        achievements_edit.setPlainText("\n".join(profile_data["achievements"]))
        achievements_edit.setFixedHeight(90)
        self.profile_inputs["achievements"] = achievements_edit
        form.addRow("Achievements (one per line)", achievements_edit)

        form_wrap.addLayout(form)
        self.profile_container.addWidget(card)

        note = QLabel(
            "Fields marked \"auto-detected\" come from a rule-based reading of your resume text "
            "and can be wrong - please review them. Nothing here is sent anywhere until you "
            "configure an AI provider in AI Settings."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.profile_container.addWidget(note)

        save_button = QPushButton("Save Candidate Profile")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._save_profile)
        self.profile_container.addWidget(save_button)

    @staticmethod
    def _profile_to_dict(profile) -> dict:
        return {
            "target_roles": profile.target_roles or [],
            "seniority": profile.seniority or "",
            "years_experience": profile.years_experience or 0.0,
            "technical_skills": profile.technical_skills or [],
            "programming_languages": profile.programming_languages or [],
            "software": profile.software or [],
            "domain_expertise": profile.domain_expertise or [],
            "industries": profile.industries or [],
            "certifications": profile.certifications or [],
            "companies": profile.companies or [],
            "education": profile.education or [],
            "leadership": profile.leadership or [],
            "achievements": profile.achievements or [],
        }

    def _save_profile(self) -> None:
        with session_scope() as session:
            user = self._get_user(session)
            profile = self.context.candidate_profile_repo.get_current(session, user.id)
            fields = {
                "target_roles": text_to_list(self.profile_inputs["target_roles"].text()),
                "seniority": self.profile_inputs["seniority"].currentData(),
                "years_experience": self.profile_inputs["years_experience"].value(),
                "achievements": [
                    line.strip()
                    for line in self.profile_inputs["achievements"].toPlainText().split("\n")
                    if line.strip()
                ],
            }
            for field_name, _label in _PROFILE_LIST_FIELDS:
                fields[field_name] = text_to_list(self.profile_inputs[field_name].text())
            self.context.candidate_profile_repo.save(session, profile, **fields)

            # Seed the Job Search Profile from what we just extracted, so a
            # new user isn't asked to re-type target titles/seniority the
            # resume already told us - matching needs those populated to
            # find anything at all. Only ever fills fields still empty.
            user_prefs = self.context.preferences_repo.get_active(session, user.id)
            autofill = autofill_preferences_from_profile(session, self.context, profile, user_prefs)

        message = "Candidate profile saved."
        if autofill.any_filled:
            message += (
                "\n\n" + autofill.summary()
                + "\n\nReview these on the Job Search Profile page - they drive every match."
            )
        QMessageBox.information(self, "Saved", message)
