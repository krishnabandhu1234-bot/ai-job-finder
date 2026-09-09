"""Runs opt-in AI resume reading on a background QThread.

An LLM reading a full resume takes several seconds to a minute, so it
can't run on the UI thread (section 30). Mirrors `app.core.rank_worker`.

The actual work - and the privacy reasoning behind it - lives in
`app/resume/llm_extractor.py`; this module only handles threading and
turning the outcome into a message the page can show.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.core.app_context import get_context
from app.database.db import session_scope

logger = logging.getLogger(__name__)


class ResumeAIWorker(QObject):
    progress = Signal(str)
    finished = Signal(str)  # human-readable summary of what changed
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.finished.emit(self._read_resumes())
        except Exception as exc:
            from app.resume.llm_extractor import LLMResumeError

            if isinstance(exc, LLMResumeError):
                # Expected, explainable conditions (no API key, local-only
                # mode, unreadable reply) - show the message as-is.
                self.failed.emit(str(exc))
            else:
                logger.exception("AI resume reading failed unexpectedly")
                self.failed.emit(f"Unexpected error: {exc}")

    def _read_resumes(self) -> str:
        from app.ai.embeddings import resolve_ai_config
        from app.resume.extractor import extract_resume
        from app.resume.llm_extractor import (
            LLMResumeError,
            extract_with_llm,
            merge_llm_into_fields,
        )
        from app.resume.profile_builder import build_candidate_profile_fields

        context = get_context()
        with session_scope() as session:
            user = context.users_repo.get_or_create_default_user(
                session, context.config.email_to or "local-user@aijobfinder.local"
            )
            ai_config = resolve_ai_config(session, context)
            resumes = [r for r in context.resumes_repo.list_for_user(session, user.id) if r.raw_text]
            if not resumes:
                raise LLMResumeError("No resume with readable text was found.")

            # Start from the offline parse so the AI's reading is added to
            # what the taxonomy reliably found, never instead of it.
            self.progress.emit("Reading resume(s) offline first...")
            rule_based = build_candidate_profile_fields(
                [(r.id, extract_resume(r.raw_text)) for r in resumes]
            )

            combined_text = "\n\n".join(r.raw_text for r in resumes)
            self.progress.emit(f"Asking your AI provider to read {len(resumes)} resume(s)...")
            llm_fields = extract_with_llm(ai_config, combined_text)

            merged = merge_llm_into_fields(rule_based, llm_fields)
            profile = context.candidate_profile_repo.get_current(session, user.id)
            context.candidate_profile_repo.save(session, profile, **merged)

            # Seed the job search profile too, so a first-time user is
            # ready to scan straight after this.
            from app.resume.profile_autofill import autofill_preferences_from_profile

            prefs = context.preferences_repo.get_active(session, user.id)
            autofill = autofill_preferences_from_profile(session, context, profile, prefs)

        return self._summarize(rule_based, llm_fields, merged, autofill)

    @staticmethod
    def _summarize(rule_based: dict, llm_fields: dict, merged: dict, autofill) -> str:
        """Says specifically what the AI added, so the user can judge
        whether it was worth sending their resume rather than just being
        told "done"."""
        lines = ["The AI read your resume and updated your candidate profile."]

        roles = merged.get("target_roles") or []
        if roles:
            lines.append(f"\nTarget roles: {', '.join(roles[:6])}")
        if merged.get("seniority"):
            lines.append(f"Seniority: {merged['seniority']}")
        if merged.get("years_experience"):
            lines.append(f"Years of experience: {merged['years_experience']}")

        added = []
        for key in ("technical_skills", "domain_expertise", "industries", "software"):
            before = {str(v).casefold() for v in (rule_based.get(key) or [])}
            new_items = [v for v in (llm_fields.get(key) or []) if str(v).casefold() not in before]
            if new_items:
                label = key.replace("_", " ")
                added.append(f"  • {label}: {', '.join(new_items[:6])}")
        if added:
            lines.append("\nThings the offline parser missed that the AI found:")
            lines.extend(added)

        if autofill is not None and autofill.any_filled:
            lines.append("\n" + autofill.summary())

        lines.append("\nEverything is editable below - review it before scanning.")
        return "\n".join(lines)


def start_resume_ai_read(parent: QObject, on_progress, on_finished, on_failed):
    thread = QThread(parent)
    worker = ResumeAIWorker()
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    thread.start()
    return thread, worker
