"""Runs automatic company discovery (app.jobs.discovery) on a background
QThread, mirroring `app.core.rank_worker`.

Discovery is by far the slowest action in the app - one LLM call plus up
to several hundred throttled HTTP probes - so running it on the UI thread
would freeze the window for minutes (section 30). It's deliberately slow
rather than parallel: the probes go through the shared rate-limited HTTP
client so the app stays a well-behaved API client even when checking
hundreds of companies.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.core.app_context import get_context
from app.database.db import session_scope

logger = logging.getLogger(__name__)


class DiscoveryWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)  # DiscoveryResult
    failed = Signal(str)

    def __init__(self, count: int):
        super().__init__()
        self._count = count

    def run(self) -> None:
        try:
            from app.ai.embeddings import resolve_ai_config
            from app.jobs.discovery import discover_and_add_sources

            context = get_context()
            with session_scope() as session:
                user = context.users_repo.get_or_create_default_user(
                    session, context.config.email_to or "local-user@aijobfinder.local"
                )
                profile = context.candidate_profile_repo.get_current(session, user.id)
                prefs = context.preferences_repo.get_active(session, user.id)
                ai_config = resolve_ai_config(session, context)
                result = discover_and_add_sources(
                    session, context, ai_config, profile, prefs,
                    count=self._count, progress_callback=self.progress.emit,
                )
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("Company discovery failed unexpectedly")
            self.failed.emit(str(exc))


def start_discovery(
    parent: QObject, on_progress, on_finished, on_failed, count: int
) -> tuple[QThread, DiscoveryWorker]:
    thread = QThread(parent)
    worker = DiscoveryWorker(count)
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
