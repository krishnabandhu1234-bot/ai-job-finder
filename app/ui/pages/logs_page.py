"""Logs (section 22). Tails the real rotating log file written by
app/core/logging_setup.py - fully functional in Phase 1."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton

from app.core.logging_setup import tail_log_file
from app.ui.base_page import BasePage


class LogsPage(BasePage):
    title = "Logs"
    subtitle = "Recent application activity"

    def build(self) -> None:
        button_row = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        open_folder_button = QPushButton("Open Logs Folder")
        open_folder_button.clicked.connect(self._open_logs_folder)
        button_row.addWidget(refresh_button)
        button_row.addWidget(open_folder_button)
        button_row.addStretch(1)
        self.content_layout.addLayout(button_row)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        self.content_layout.addWidget(self.log_view)

        self.refresh()

    def refresh(self) -> None:
        lines = tail_log_file(self.context.config.logs_dir, max_lines=500)
        self.log_view.setPlainText("\n".join(lines) if lines else "No log entries yet.")
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _open_logs_folder(self) -> None:
        import os

        os.startfile(self.context.config.logs_dir)  # noqa: S606 - Windows-only, opens Explorer
