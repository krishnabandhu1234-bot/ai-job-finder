"""Runs a job-source scan on a background QThread so the UI stays
responsive and can show progress (section 30: "Show progress"), rather
than freezing while network requests to job sources are in flight.

Usage from a page:

    self._scan_thread, self._scan_worker = start_scan(
        self, on_progress=self._on_scan_progress,
        on_finished=self._on_scan_finished, on_failed=self._on_scan_failed,
    )

The caller MUST keep a reference to both the returned thread and worker
(e.g. as `self._scan_thread`/`self._scan_worker`) until a finished/failed
signal fires - Qt does not keep them alive on its own, and losing the
reference while the thread runs can crash the app.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from app.core.constants import ScanTrigger
from app.database.db import session_scope
from app.jobs.scan_orchestrator import ScanSummary, run_scan

logger = logging.getLogger(__name__)


class ScanWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)  # ScanSummary
    failed = Signal(str)

    def __init__(self, trigger: str = ScanTrigger.MANUAL.value):
        super().__init__()
        self.trigger = trigger

    def run(self) -> None:
        try:
            # Look for new companies to watch BEFORE scanning, so a scan
            # covers everything found this run rather than always being a
            # run behind. The user never supplies a company list - the app
            # finds employers matching their resume by itself (see
            # `app.core.pipeline.run_auto_discovery`). Silently skipped
            # when no AI provider is set up, and never fatal.
            from app.core.app_context import get_context
            from app.core.pipeline import run_auto_discovery

            context = get_context()
            self.progress.emit("Looking for new companies that match your resume...")
            added, _error = run_auto_discovery(context)
            if added:
                self.progress.emit(f"Found {added} new compan{'y' if added == 1 else 'ies'} to watch.")

            with session_scope() as session:
                summary: ScanSummary = run_scan(
                    session, trigger=self.trigger, progress_callback=self.progress.emit, context=context
                )
            self.finished.emit(summary)
        except Exception as exc:
            logger.exception("Scan failed unexpectedly")
            self.failed.emit(str(exc))


def start_scan(
    parent: QObject,
    on_progress,
    on_finished,
    on_failed,
    trigger: str = ScanTrigger.MANUAL.value,
) -> tuple[QThread, ScanWorker]:
    thread = QThread(parent)
    worker = ScanWorker(trigger)
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
