"""AI Job Finder entry point.

Run with:  python main.py
Package with: pyinstaller --noconfirm packaging/aijobfinder.spec
Self-test a build (no GUI) with: AIJF_SELFTEST=1 python main.py
    (or AIJF_SELFTEST=1 dist\\AIJobFinder\\AIJobFinder.exe once frozen)
"""

from __future__ import annotations

import logging
import os
import sys
import traceback

logger = logging.getLogger(__name__)


def _install_global_exception_hook(app) -> None:
    """Section 23: the app should never silently fail. Any exception that
    escapes a Qt event handler is logged and shown to the user instead of
    crashing to a blank desktop with no explanation."""
    from PySide6.QtWidgets import QMessageBox

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logger.error("Unhandled exception:\n%s", message)
        QMessageBox.critical(
            None,
            "AI Job Finder — Unexpected Error",
            "Something went wrong. Details have been written to the log file "
            "(see the Logs page).\n\n" + str(exc_value),
        )

    sys.excepthook = handle_exception


def _run_gui() -> int:
    from PySide6.QtWidgets import QApplication

    from app.core.app_context import bootstrap
    from app.core.scheduler import init_scheduler
    from app.ui.main_window import MainWindow
    from app.ui.theme import STYLESHEET

    context = bootstrap()

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    app.setApplicationName("AI Job Finder")

    _install_global_exception_hook(app)

    scheduler = init_scheduler(context)
    app.aboutToQuit.connect(scheduler.shutdown)

    window = MainWindow(context)
    window.show()

    logger.info("AI Job Finder started")
    return app.exec()


def main() -> int:
    if os.environ.get("AIJF_SELFTEST") == "1":
        from app.core.selftest import run_selftest

        return run_selftest()
    return _run_gui()


if __name__ == "__main__":
    sys.exit(main())
