"""Runs the AI matching funnel (app.ai.ranker) on a background QThread,
mirroring `app.core.scan_worker` - embedding/LLM calls can take a while
and must never freeze the UI (section 30)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.core.app_context import get_context
from app.database.db import session_scope

logger = logging.getLogger(__name__)


class RankWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)  # RankingSummary
    failed = Signal(str)

    def run(self) -> None:
        try:
            from app.ai.ranker import run_ranking

            context = get_context()
            with session_scope() as session:
                summary = run_ranking(session, context, progress_callback=self.progress.emit)
            self.finished.emit(summary)
        except Exception as exc:
            logger.exception("Matching/ranking failed unexpectedly")
            self.failed.emit(str(exc))


def start_ranking(parent: QObject, on_progress, on_finished, on_failed) -> tuple[QThread, RankWorker]:
    thread = QThread(parent)
    worker = RankWorker()
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
