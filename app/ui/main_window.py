"""Main window: sidebar navigation (section 14) driving a QStackedWidget
of pages. Each page is only constructed once; `refresh()` is called every
time the user navigates to it so data stays current without rebuilding
widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.core.app_context import AppContext
from app.ui.pages.ai_settings import AISettingsPage
from app.ui.pages.companies import CompaniesPage
from app.ui.pages.dashboard import DashboardPage
from app.ui.pages.email_settings import EmailSettingsPage
from app.ui.pages.history import HistoryPage
from app.ui.pages.job_matches import JobMatchesPage
from app.ui.pages.job_profile import JobProfilePage
from app.ui.pages.job_sources import JobSourcesPage
from app.ui.pages.logs_page import LogsPage
from app.ui.pages.resumes import ResumesPage
from app.ui.pages.scheduler_page import SchedulerPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.setup_guide import SetupGuidePage

_NAV_PAGES = [
    ("Setup Guide", SetupGuidePage),
    ("Dashboard", DashboardPage),
    ("Resumes", ResumesPage),
    ("Job Search Profile", JobProfilePage),
    ("Job Matches", JobMatchesPage),
    ("Companies", CompaniesPage),
    ("Job Sources", JobSourcesPage),
    ("Email Settings", EmailSettingsPage),
    ("Scheduler", SchedulerPage),
    ("AI Settings", AISettingsPage),
    ("History", HistoryPage),
    ("Logs", LogsPage),
    ("Settings", SettingsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext):
        super().__init__()
        self.context = context
        self.setWindowTitle("AI Job Finder")
        self.resize(1180, 780)

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.pages: list[QWidget] = []
        for _name, page_cls in _NAV_PAGES:
            page = page_cls(context)
            self.pages.append(page)
            self.stack.addWidget(page)
        root_layout.addWidget(self.stack, 1)

        # Open on the Setup Guide the first time (nothing has been set up
        # yet, so the Dashboard would just be a wall of zeros), and on the
        # Dashboard once the user is up and running.
        self.nav_list.setCurrentRow(0 if self._needs_setup() else 1)
        self._on_nav_changed(self.nav_list.currentRow())

        status_bar = QStatusBar()
        mode = "Demo Mode" if context.config.demo_mode else "Live Mode"
        status_bar.showMessage(f"AI Job Finder v{__version__} — {mode}")
        self.setStatusBar(status_bar)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        title = QLabel("AI JOB FINDER")
        title.setObjectName("sidebarTitle")
        layout.addWidget(title)

        subtitle = QLabel("AI-powered job discovery")
        subtitle.setObjectName("sidebarSubtitle")
        layout.addWidget(subtitle)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for name, _page_cls in _NAV_PAGES:
            QListWidgetItem(name, self.nav_list)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        layout.addWidget(self.nav_list, 1)

        return sidebar

    def _on_nav_changed(self, index: int) -> None:
        if index < 0:
            return
        self.stack.setCurrentIndex(index)
        page = self.pages[index]
        page.refresh()

    def _needs_setup(self) -> bool:
        """Whether the user still has essential setup left to do.

        Uses the narrowest possible check - "is there a resume and a job
        source" - because this only decides which page opens first, and
        being wrong should never be worse than a click."""
        from app.database.db import session_scope

        try:
            with session_scope() as session:
                user = self.context.users_repo.get_or_create_default_user(
                    session, self.context.config.email_to or "local-user@aijobfinder.local"
                )
                resumes = self.context.resumes_repo.list_for_user(session, user.id)
                sources = self.context.job_sources_repo.list_all(session)
                return not (any(r.raw_text for r in resumes) and sources)
        except Exception:  # never block startup over a nice-to-have
            return True

    def navigate_to(self, page_name: str) -> None:
        """Switches to a page by its sidebar name.

        Public because pages use it to send the user somewhere useful -
        the Setup Guide's step buttons, and the Dashboard's empty state."""
        for row, (name, _cls) in enumerate(_NAV_PAGES):
            if name == page_name:
                self.nav_list.setCurrentRow(row)
                return
