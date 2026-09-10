"""Job Sources (section 4). Add/enable/disable/remove sources backed by
real connectors (Greenhouse/Lever/Ashby/Workable/SmartRecruiters/Demo),
and test connectivity for one source at a time without running a full
scan.

Beyond those five ATS platforms, "Company career page (any URL)" (see
app/jobs/career_page_source.py) reads any company's own careers page
directly - it just needs a URL rather than a documented API, so it's the
one type here that isn't limited to a fixed list of platforms. Nothing
here bypasses CAPTCHAs, auth, or robots.txt.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.core.discovery_worker import start_discovery
from app.database.db import session_scope
from app.jobs.discovery import DEFAULT_SUGGESTION_COUNT, MAX_SUGGESTIONS
from app.jobs.scan_orchestrator import build_source
from app.ui.base_page import BasePage, empty_state, make_card

_SOURCE_TYPE_LABELS = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workable": "Workable",
    "smartrecruiters": "SmartRecruiters",
    "resume_search": "Job search (automatic)",
    "company_career_page": "Company career page (any URL)",
    "demo": "Demo (example data)",
}

# Source types the app manages itself - offering them in the "add a
# source by hand" dropdown would be confusing, since there's nothing for
# the user to type and the app creates/refreshes it automatically.
_SELF_MANAGED_SOURCE_TYPES = {"resume_search"}

_CONFIG_FIELD_LABELS = {
    "greenhouse": ("board_token", "Board token (from boards.greenhouse.io/<token>)"),
    "lever": ("company_slug", "Company slug (from jobs.lever.co/<slug>)"),
    "ashby": ("board_name", "Board name (from jobs.ashbyhq.com/<name>)"),
    "workable": ("account_slug", "Account slug (from apply.workable.com/<slug>)"),
    "smartrecruiters": ("company_slug", "Company slug (from jobs.smartrecruiters.com/<slug>)"),
    "company_career_page": ("url", "Careers page URL (e.g. https://company.com/careers) - works on any company's own page, not just these five platforms"),
    "demo": (None, None),
}


class JobSourcesPage(BasePage):
    title = "Job Sources"
    subtitle = "Where AI Job Finder looks for new postings"

    def build(self) -> None:
        note = QLabel(
            "Only official ATS public job-board APIs (Greenhouse, Lever, Ashby, Workable, "
            "SmartRecruiters) and the built-in Demo source are supported - never CAPTCHA/auth "
            "bypass, and always respecting robots.txt and rate limits. Company career pages and "
            "additional public APIs are a planned extension (see app/jobs/source.py)."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280;")
        self.content_layout.addWidget(note)

        self.content_layout.addWidget(self._discovery_card())
        self.content_layout.addWidget(self._add_source_form())

        list_title = QLabel("CONFIGURED SOURCES")
        list_title.setStyleSheet("font-weight: 600; color: #6b7280; letter-spacing: 1px;")
        self.content_layout.addWidget(list_title)

        self.sources_container = QVBoxLayout()
        self.content_layout.addLayout(self.sources_container)

        self.refresh()

    def _discovery_card(self):
        """Section 4's "find companies for me" path: instead of the user
        hand-entering an ATS token per company, the AI proposes companies
        that fit their resume and the app verifies which actually have a
        public job board before adding any of them."""
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Find companies for me (AI)")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        explanation = QLabel(
            "Uses your resume-derived candidate profile to have the AI suggest companies that hire "
            "for your roles, then checks each one for a real public job board (Greenhouse/Lever/"
            "Ashby) and adds only the ones that actually exist and have openings.\n\n"
            "This needs an LLM provider configured on the AI Settings page. It's deliberately slow "
            "- every company is checked one at a time through the same rate-limited client used for "
            "scanning - so expect a few minutes for a large batch. You can keep using the app while "
            "it runs."
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(explanation)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Companies to look for:"))
        self.discovery_count_input = QSpinBox()
        self.discovery_count_input.setRange(1, MAX_SUGGESTIONS)
        self.discovery_count_input.setValue(DEFAULT_SUGGESTION_COUNT)
        controls.addWidget(self.discovery_count_input)

        self.discover_button = QPushButton("Find Companies")
        self.discover_button.setObjectName("primaryButton")
        self.discover_button.clicked.connect(self._start_discovery)
        controls.addWidget(self.discover_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.discovery_status = QLabel("")
        self.discovery_status.setWordWrap(True)
        self.discovery_status.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(self.discovery_status)

        self._discovery_thread = None
        self._discovery_worker = None
        return card

    def _start_discovery(self) -> None:
        self.discover_button.setEnabled(False)
        self.discover_button.setText("Searching...")
        self.discovery_status.setText("Starting...")
        self._discovery_thread, self._discovery_worker = start_discovery(
            self,
            on_progress=self.discovery_status.setText,
            on_finished=self._on_discovery_finished,
            on_failed=self._on_discovery_failed,
            count=self.discovery_count_input.value(),
        )

    def _on_discovery_finished(self, result) -> None:
        self.discover_button.setEnabled(True)
        self.discover_button.setText("Find Companies")
        self.refresh()

        if result.error:
            self.discovery_status.setText("")
            QMessageBox.warning(self, "Discovery Could Not Run", result.error)
            return

        summary = (
            f"Added {len(result.added)} new job board(s).\n\n"
            f"Checked: {len(result.suggested)} suggested compan(ies)\n"
            f"No public board found: {len(result.unresolved)}\n"
            f"Already configured: {result.skipped_existing}"
        )
        if result.added:
            preview = "\n".join(f"• {b.company_name} — {b.job_count} open role(s)" for b in result.added[:10])
            more = f"\n... and {len(result.added) - 10} more" if len(result.added) > 10 else ""
            summary += f"\n\nNewly added:\n{preview}{more}\n\nRun a scan to pull in their postings."
        self.discovery_status.setText(f"Added {len(result.added)} new board(s).")
        QMessageBox.information(self, "Discovery Complete", summary)

    def _on_discovery_failed(self, error: str) -> None:
        self.discover_button.setEnabled(True)
        self.discover_button.setText("Find Companies")
        self.discovery_status.setText("")
        QMessageBox.critical(self, "Discovery Failed", f"Company discovery could not complete: {error}")

    def _add_source_form(self):
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Acme Corp (Greenhouse)")
        form.addRow("Display name", self.name_input)

        self.type_combo = QComboBox()
        for value, label in _SOURCE_TYPE_LABELS.items():
            if value in _SELF_MANAGED_SOURCE_TYPES:
                continue
            self.type_combo.addItem(label, value)
        self.type_combo.currentIndexChanged.connect(self._update_config_field_label)
        form.addRow("Source type", self.type_combo)

        self.config_label = QLabel()
        self.config_input = QLineEdit()
        form.addRow(self.config_label, self.config_input)

        self.company_name_input = QLineEdit()
        self.company_name_input.setPlaceholderText("Display name for the company (defaults to the token above)")
        form.addRow("Company display name", self.company_name_input)

        layout.addLayout(form)

        add_button = QPushButton("Add Source")
        add_button.setObjectName("primaryButton")
        add_button.clicked.connect(self._add_source)
        layout.addWidget(add_button)

        self._update_config_field_label()
        return card

    def _update_config_field_label(self) -> None:
        source_type = self.type_combo.currentData()
        field_name, label = _CONFIG_FIELD_LABELS.get(source_type, (None, None))
        if field_name is None:
            self.config_label.setText("(no configuration needed)")
            self.config_input.setEnabled(False)
            self.config_input.clear()
        else:
            self.config_label.setText(label)
            self.config_input.setEnabled(True)

    def _add_source(self) -> None:
        name = self.name_input.text().strip()
        source_type = self.type_combo.currentData()
        field_name, _label = _CONFIG_FIELD_LABELS.get(source_type, (None, None))

        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a display name for this source.")
            return

        config = {}
        if field_name:
            value = self.config_input.text().strip()
            if not value:
                QMessageBox.warning(self, "Missing Configuration", f"Please enter the {self.config_label.text()}.")
                return
            config[field_name] = value
            if self.company_name_input.text().strip():
                config["company_name"] = self.company_name_input.text().strip()

        with session_scope() as session:
            self.context.job_sources_repo.create(session, name=name, source_type=source_type, config=config)

        self.name_input.clear()
        self.config_input.clear()
        self.company_name_input.clear()
        self.refresh()

    def refresh(self) -> None:
        while self.sources_container.count():
            item = self.sources_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        with session_scope() as session:
            sources = self.context.job_sources_repo.list_all(session)

        if not sources:
            self.sources_container.addWidget(
                empty_state("No job sources configured yet. Add one above, or add the Demo source to try the app.")
            )
            return

        for source in sources:
            self.sources_container.addWidget(self._source_row(source))

    def _source_row(self, source):
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)

        enabled_check = QCheckBox()
        enabled_check.setChecked(source.enabled)
        enabled_check.stateChanged.connect(
            lambda state, sid=source.id: self._set_enabled(sid, state != 0)
        )
        layout.addWidget(enabled_check)

        info = QVBoxLayout()
        name_label = QLabel(source.name)
        name_label.setStyleSheet("font-weight: 600;")
        info.addWidget(name_label)

        type_label = _SOURCE_TYPE_LABELS.get(source.source_type, source.source_type)
        status_bits = [type_label]
        if source.last_scanned_at:
            status_bits.append(f"last scanned {source.last_scanned_at.strftime('%Y-%m-%d %H:%M')}")
        if source.last_error:
            status_bits.append(f"error: {source.last_error}")
        status_label = QLabel(" — ".join(status_bits))
        status_label.setStyleSheet("color: #dc2626;" if source.last_error else "color: #6b7280;")
        status_label.setWordWrap(True)
        info.addWidget(status_label)
        layout.addLayout(info, 1)

        test_button = QPushButton("Fetch Now")
        test_button.clicked.connect(lambda _checked=False, sid=source.id: self._test_source(sid))
        layout.addWidget(test_button)

        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(lambda _checked=False, sid=source.id: self._remove_source(sid))
        layout.addWidget(remove_button)

        return card

    def _set_enabled(self, source_id: int, enabled: bool) -> None:
        with session_scope() as session:
            self.context.job_sources_repo.set_enabled(session, source_id, enabled)

    def _remove_source(self, source_id: int) -> None:
        with session_scope() as session:
            self.context.job_sources_repo.delete(session, source_id)
        self.refresh()

    def _test_source(self, source_id: int) -> None:
        from app.ai.embeddings import resolve_ai_config
        from app.jobs.career_page_source import resolve_browser_agent_config

        with session_scope() as session:
            source_row = self.context.job_sources_repo.get(session, source_id)
            if source_row is None:
                return
            ai_config = resolve_ai_config(session, self.context)
            browser_config = resolve_browser_agent_config(session, self.context)
            source = build_source(source_row, ai_config=ai_config, browser_config=browser_config)
            if source is None:
                QMessageBox.warning(
                    self, "Not Supported",
                    f"No connector is implemented yet for source type {source_row.source_type!r}.",
                )
                return

        result = source.fetch()
        if result.success:
            preview = "\n".join(f"• {p.title} — {p.company}" for p in result.postings[:5])
            more = f"\n... and {result.fetched_count - 5} more" if result.fetched_count > 5 else ""
            QMessageBox.information(
                self, "Fetch Successful",
                f"Retrieved {result.fetched_count} posting(s):\n\n{preview}{more}",
            )
        else:
            QMessageBox.critical(self, "Fetch Failed", result.error or "Unknown error.")
