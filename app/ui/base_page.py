"""Common base class for every sidebar page, so headers/empty-states look
consistent and each page doesn't reinvent layout boilerplate."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.app_context import AppContext


class BasePage(QWidget):
    """Subclasses set `title`/`subtitle` and build their content into
    `self.content_layout` inside `build()`."""

    title: str = ""
    subtitle: str = ""

    def __init__(self, context: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.context = context

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        header = QVBoxLayout()
        header.setSpacing(2)
        title_label = QLabel(self.title)
        title_label.setObjectName("pageTitle")
        header.addWidget(title_label)
        if self.subtitle:
            subtitle_label = QLabel(self.subtitle)
            subtitle_label.setObjectName("pageSubtitle")
            header.addWidget(subtitle_label)
        outer.addLayout(header)

        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(16)
        outer.addLayout(self.content_layout)
        outer.addStretch(1)

        self.build()

    def build(self) -> None:
        """Override in subclasses to populate `self.content_layout`."""
        raise NotImplementedError

    def refresh(self) -> None:
        """Called whenever this page becomes visible again. Override to
        re-pull data from the database (e.g. Dashboard stats)."""


def make_card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    card.setProperty("class", "Card")
    return card


def empty_state(text: str) -> QWidget:
    container = QFrame()
    container.setObjectName("card")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(24, 40, 24, 40)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("color: #6b7280;")
    layout.addWidget(label)
    return container


def list_to_text(items: list) -> str:
    """Comma-joins a JSON list field for display in a QLineEdit."""
    return ", ".join(items or [])


def text_to_list(text: str) -> list:
    """Inverse of `list_to_text`, for reading a QLineEdit back into a JSON
    list field. Blank/whitespace-only entries are dropped."""
    return [part.strip() for part in text.split(",") if part.strip()]
