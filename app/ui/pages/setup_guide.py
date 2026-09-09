"""Setup Guide - the first thing a new user sees.

Everything this app does depends on a chain of setup (resume → search
profile → job sources → scan), and until the whole chain is complete the
app appears to do nothing: the Dashboard sits at zero and a scan finds
no matches. Previously nothing told the user which link was missing.

This page checks each step's real state in the database, shows what's
done and what isn't, and takes the user straight to the page that fixes
the next gap. It is deliberately a live status view rather than a
one-time wizard, so it stays useful later ("why did I stop getting
email?") instead of being dismissed once and forgotten.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.database.db import session_scope
from app.email.sender import resolve_email_config
from app.ui.base_page import BasePage, make_card


@dataclass
class SetupStep:
    number: int
    title: str
    done: bool
    detail: str
    action_label: str
    target_page: str | None
    required: bool = True


class SetupGuidePage(BasePage):
    title = "Setup Guide"
    subtitle = "Everything you need to start getting job matches"

    def build(self) -> None:
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.content_layout.addWidget(self.summary_label)

        self.intro_label = QLabel("")
        self.intro_label.setWordWrap(True)
        self.intro_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.content_layout.addWidget(self.intro_label)

        self.steps_container = QVBoxLayout()
        self.content_layout.addLayout(self.steps_container)

        self.refresh()

    # -- status detection ------------------------------------------------

    def _collect_steps(self) -> list[SetupStep]:
        with session_scope() as session:
            user = self.context.users_repo.get_or_create_default_user(
                session, self.context.config.email_to or "local-user@aijobfinder.local"
            )
            resumes = self.context.resumes_repo.list_for_user(session, user.id)
            profile = self.context.candidate_profile_repo.get_current(session, user.id)
            prefs = self.context.preferences_repo.get_active(session, user.id)
            sources = [s for s in self.context.job_sources_repo.list_all(session) if s.enabled]
            matches = self.context.job_matches_repo.top_matches(session, profile.id, limit=1)
            email_config = resolve_email_config(session, self.context)
            scheduler_on = self.context.settings_repo.get_bool(session, "scheduler.enabled", False)

            has_resume_text = any(r.raw_text for r in resumes)
            has_profile = bool(
                profile.target_roles or profile.technical_skills or profile.programming_languages
            )
            has_titles = bool(prefs.target_titles)
            source_count = len(sources)
            has_matches = bool(matches)
            email_ready = email_config.is_configured()

        return [
            SetupStep(
                1, "Upload your resume",
                done=has_resume_text,
                detail=(
                    f"{len(resumes)} resume(s) uploaded and read."
                    if has_resume_text else
                    "Everything else is built from your resume - this is the place to start. "
                    "PDF, DOCX or TXT."
                ),
                action_label="Go to Resumes",
                target_page="Resumes",
            ),
            SetupStep(
                2, "Check what was detected about you",
                done=has_profile,
                detail=(
                    f"Profile built: {len(profile.target_roles or [])} target role(s), "
                    f"{len(profile.technical_skills or []) + len(profile.programming_languages or [])} skill(s)."
                    if has_profile else
                    "Your candidate profile is empty. Upload a resume, then review the "
                    "auto-detected fields and correct anything wrong."
                ),
                action_label="Review Profile",
                target_page="Resumes",
            ),
            SetupStep(
                3, "Confirm what you're looking for",
                done=has_titles,
                detail=(
                    f"Searching for: {', '.join(prefs.target_titles[:4])}"
                    + (f" (+{len(prefs.target_titles) - 4} more)" if len(prefs.target_titles) > 4 else "")
                    if has_titles else
                    "No target job titles set. These are filled in automatically when you save "
                    "your resume - or you can type them yourself."
                ),
                action_label="Go to Job Search Profile",
                target_page="Job Search Profile",
            ),
            SetupStep(
                4, "Add companies to watch",
                done=source_count > 0,
                detail=(
                    f"{source_count} job source(s) enabled."
                    + ("  Tip: run \"Find Companies\" again to widen the net." if source_count < 10 else "")
                    if source_count else
                    "No job sources yet - there's nowhere to search. Use \"Find Companies\" to let "
                    "the AI pick companies matching your resume, add a specific company's board, "
                    "or add the Demo source to try the app with sample data."
                ),
                action_label="Go to Job Sources",
                target_page="Job Sources",
            ),
            SetupStep(
                5, "Run your first scan",
                done=has_matches,
                detail=(
                    "You have scored job matches - open Job Matches to see them."
                    if has_matches else
                    "Press SCAN NOW on the Dashboard. It fetches postings from your sources and "
                    "scores every one against your resume. The first run downloads the local AI "
                    "model, so allow a minute."
                ),
                action_label="Go to Dashboard",
                target_page="Dashboard",
            ),
            SetupStep(
                6, "Get matches emailed to you (optional)",
                done=email_ready,
                detail=(
                    "Email is configured." + ("  Daily schedule is ON." if scheduler_on else
                                              "  Turn on the daily schedule under Scheduler.")
                    if email_ready else
                    "Optional - the app works fine without it. Set this up to get a daily digest "
                    "instead of checking the app."
                ),
                action_label="Go to Email Settings",
                target_page="Email Settings",
                required=False,
            ),
        ]

    # -- rendering -------------------------------------------------------

    def refresh(self) -> None:
        while self.steps_container.count():
            item = self.steps_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        steps = self._collect_steps()
        required = [s for s in steps if s.required]
        done_count = sum(1 for s in required if s.done)
        total = len(required)

        if done_count == total:
            self.summary_label.setText("✅ You're all set up.")
            self.intro_label.setText(
                "Everything required is done. This page stays here as a health check - if matches "
                "or emails ever stop arriving, come back and see which step went red."
            )
        else:
            next_step = next((s for s in required if not s.done), None)
            self.summary_label.setText(f"Setup: {done_count} of {total} steps done")
            self.intro_label.setText(
                f"Next: step {next_step.number} - {next_step.title}." if next_step else ""
            )

        for step in steps:
            self.steps_container.addWidget(self._step_card(step))

    def _step_card(self, step: SetupStep) -> QWidget:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)

        marker = QLabel("✅" if step.done else f"{step.number}")
        marker.setFixedWidth(30)
        marker.setStyleSheet(
            "font-size: 16px; font-weight: 700;"
            + ("color: #059669;" if step.done else "color: #9ca3af;")
        )
        layout.addWidget(marker)

        text_column = QVBoxLayout()
        title = QLabel(step.title + ("" if step.required else "  (optional)"))
        title.setStyleSheet(
            "font-weight: 600; font-size: 14px;"
            + ("color: #6b7280;" if step.done else "color: #111827;")
        )
        text_column.addWidget(title)

        detail = QLabel(step.detail)
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #6b7280; font-size: 12px;")
        text_column.addWidget(detail)
        layout.addLayout(text_column, 1)

        if step.target_page:
            button = QPushButton(step.action_label)
            if not step.done:
                button.setObjectName("primaryButton")
            button.clicked.connect(lambda _checked=False, p=step.target_page: self._navigate(p))
            layout.addWidget(button)

        return card

    def _navigate(self, page_name: str) -> None:
        """Jumps to another sidebar page.

        Walks up to the MainWindow rather than holding a reference to it,
        so this page stays constructible on its own (the widget tests
        build pages in isolation)."""
        window = self.window()
        navigate = getattr(window, "navigate_to", None)
        if callable(navigate):
            navigate(page_name)
