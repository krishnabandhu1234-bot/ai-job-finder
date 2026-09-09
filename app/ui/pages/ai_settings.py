"""AI Settings (sections 8, 17, 20, 25). Provider/model selection, API
keys, and the matching funnel's cost-optimization thresholds."""

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
    QWidget,
)

from app.ai.ranker import DEFAULT_EMBEDDING_TOP_N, DEFAULT_LLM_TOP_N
from app.core.constants import EmbeddingProvider, LLMProvider
from app.database.db import session_scope
from app.ui.base_page import BasePage, make_card

_KEY_PREFIX = "ai."


class AISettingsPage(BasePage):
    title = "AI Settings"
    subtitle = "Which AI providers analyze your resume and job matches"

    def build(self) -> None:
        privacy_card = make_card()
        privacy_layout = QVBoxLayout(privacy_card)
        privacy_layout.setContentsMargins(20, 16, 20, 16)
        self.local_only_check = QCheckBox("Local-only mode - never send resume or job data to any external API")
        privacy_layout.addWidget(self.local_only_check)
        privacy_note = QLabel(
            "When enabled, matching uses only local sentence-transformers embeddings and "
            "rule-based scoring - no data leaves your computer. A \"local\" LLM provider "
            "below (a model running on this machine via Ollama/LM Studio/etc.) is exempt "
            "and keeps working even with this on, since it never leaves the computer "
            "either. When disabled, the remote provider you choose below may receive job "
            "descriptions and relevant excerpts of your candidate profile (never the raw "
            "resume file) for the final shortlist only - see the funnel described on the "
            "Dashboard."
        )
        privacy_note.setWordWrap(True)
        privacy_note.setStyleSheet("color: #6b7280; font-size: 12px;")
        privacy_layout.addWidget(privacy_note)
        self.content_layout.addWidget(privacy_card)

        card = make_card()
        wrap = QVBoxLayout(card)
        wrap.setContentsMargins(20, 20, 20, 20)
        form = QFormLayout()
        form.setSpacing(10)

        self.embedding_provider_combo = QComboBox()
        for p in EmbeddingProvider:
            self.embedding_provider_combo.addItem(p.value, p.value)
        form.addRow("Embedding provider", self.embedding_provider_combo)

        self.embedding_model_input = QLineEdit()
        self.embedding_model_input.setPlaceholderText("all-MiniLM-L6-v2")
        form.addRow("Embedding model", self.embedding_model_input)

        self.llm_provider_combo = QComboBox()
        for p in LLMProvider:
            self.llm_provider_combo.addItem(p.value, p.value)
        self.llm_provider_combo.currentIndexChanged.connect(self._update_llm_fields_for_provider)
        form.addRow(
            "LLM provider (shortlist reasoning, \"Find Companies\", \"Read My Resume with AI\")",
            self.llm_provider_combo,
        )

        self.llm_model_input = QLineEdit()
        form.addRow("LLM model", self.llm_model_input)

        self.local_llm_url_label = QLabel("Local LLM endpoint URL")
        self.local_llm_url_input = QLineEdit()
        self.local_llm_url_input.setPlaceholderText("http://localhost:11434/v1")
        form.addRow(self.local_llm_url_label, self.local_llm_url_input)

        self.local_llm_note = QLabel(
            "Runs a model on THIS computer (Ollama, LM Studio, llama.cpp's server, ...) instead of a "
            "paid API - no key, no cost, nothing leaves the machine, and it works even with "
            "\"Local-only mode\" on above. Install Ollama, run e.g. \"ollama pull llama3.1\", leave the "
            "URL as the default, and set LLM model to the exact name you pulled (\"llama3.1\")."
        )
        self.local_llm_note.setWordWrap(True)
        self.local_llm_note.setStyleSheet("color: #6b7280; font-size: 12px;")
        form.addRow("", self.local_llm_note)

        self.anthropic_key_input = QLineEdit()
        self.anthropic_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key_clear = QPushButton("Clear")
        self.anthropic_key_clear.clicked.connect(self._clear_anthropic_key)
        form.addRow("Anthropic API key", self._key_row(self.anthropic_key_input, self.anthropic_key_clear))

        self.openai_key_input = QLineEdit()
        self.openai_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key_clear = QPushButton("Clear")
        self.openai_key_clear.clicked.connect(self._clear_openai_key)
        form.addRow("OpenAI API key", self._key_row(self.openai_key_input, self.openai_key_clear))

        self.gemini_key_input = QLineEdit()
        self.gemini_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_clear = QPushButton("Clear")
        self.gemini_key_clear.clicked.connect(self._clear_gemini_key)
        form.addRow("Google Gemini API key", self._key_row(self.gemini_key_input, self.gemini_key_clear))

        self.voyage_key_input = QLineEdit()
        self.voyage_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.voyage_key_clear = QPushButton("Clear")
        self.voyage_key_clear.clicked.connect(self._clear_voyage_key)
        form.addRow(
            "Voyage API key (embeddings)", self._key_row(self.voyage_key_input, self.voyage_key_clear)
        )

        wrap.addLayout(form)
        self.content_layout.addWidget(card)

        funnel_card = make_card()
        funnel_wrap = QVBoxLayout(funnel_card)
        funnel_wrap.setContentsMargins(20, 20, 20, 20)
        funnel_title = QLabel("Matching funnel (cost optimization)")
        funnel_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        funnel_wrap.addWidget(funnel_title)
        funnel_note = QLabel(
            "Every active job gets the free heuristic score (hard filters, skills, experience). "
            "Only the top-scoring shortlist below gets the semantic-embedding pass, and only the "
            "top of THAT shortlist gets an LLM call - see section 17 of the spec.\n\n"
            "Embeddings default to 0 = every job, because the local model is free and offline: "
            "capping it would let a strong match be cut on its title/keywords alone, before its "
            "description is ever read semantically. If you switch to a paid remote embedding "
            "provider, 0 automatically becomes a bounded 300 instead so a large scan can't run up "
            "an unexpected bill - set an explicit number here to override that."
        )
        funnel_note.setWordWrap(True)
        funnel_note.setStyleSheet("color: #6b7280; font-size: 12px;")
        funnel_wrap.addWidget(funnel_note)

        funnel_form = QFormLayout()
        self.embedding_top_n_input = QSpinBox()
        self.embedding_top_n_input.setRange(0, 100000)
        self.embedding_top_n_input.setSpecialValueText("0 (every job)")
        funnel_form.addRow("Jobs sent to embedding similarity", self.embedding_top_n_input)
        self.llm_top_n_input = QSpinBox()
        self.llm_top_n_input.setRange(0, 500)
        funnel_form.addRow("Jobs sent to LLM analysis (0 = never)", self.llm_top_n_input)
        funnel_wrap.addLayout(funnel_form)
        self.content_layout.addWidget(funnel_card)

        self.save_button = QPushButton("Save AI Settings")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save)
        self.content_layout.addWidget(self.save_button)

        note = QLabel("API keys are encrypted before being stored and are never written to logs.")
        note.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.content_layout.addWidget(note)

        self._load()

    def _update_llm_fields_for_provider(self) -> None:
        """Swaps the model-name placeholder and shows/hides the local
        endpoint field so the form only asks for what the selected
        provider actually needs - an Anthropic API key field is
        meaningless noise while "local" is selected, and vice versa."""
        provider = self.llm_provider_combo.currentData()
        is_local = provider == LLMProvider.LOCAL.value
        self.local_llm_url_label.setVisible(is_local)
        self.local_llm_url_input.setVisible(is_local)
        self.local_llm_note.setVisible(is_local)
        if is_local:
            self.llm_model_input.setPlaceholderText("llama3.1")
        elif provider == LLMProvider.OPENAI.value:
            self.llm_model_input.setPlaceholderText("gpt-4o-mini")
        elif provider == LLMProvider.GEMINI.value:
            self.llm_model_input.setPlaceholderText("gemini-2.0-flash")
        else:
            self.llm_model_input.setPlaceholderText("claude-sonnet-5")

    def _load(self) -> None:
        cfg = self.context.config
        with session_scope() as session:
            repo = self.context.settings_repo
            self.local_only_check.setChecked(repo.get_bool(session, _KEY_PREFIX + "local_only", False))

            emb_provider = repo.get(session, _KEY_PREFIX + "embedding_provider", cfg.embedding_provider.value)
            idx = self.embedding_provider_combo.findData(emb_provider)
            self.embedding_provider_combo.setCurrentIndex(max(idx, 0))
            self.embedding_model_input.setText(
                repo.get(session, _KEY_PREFIX + "embedding_model", cfg.embedding_model)
            )

            llm_provider = repo.get(session, _KEY_PREFIX + "llm_provider", cfg.llm_provider.value)
            idx = self.llm_provider_combo.findData(llm_provider)
            self.llm_provider_combo.setCurrentIndex(max(idx, 0))
            self.llm_model_input.setText(repo.get(session, _KEY_PREFIX + "llm_model", cfg.llm_model))
            self.local_llm_url_input.setText(
                repo.get(session, _KEY_PREFIX + "local_llm_base_url", cfg.local_llm_base_url)
            )
            self._update_llm_fields_for_provider()

            self._load_key_field(
                session, self.anthropic_key_input, _KEY_PREFIX + "anthropic_api_key", cfg.anthropic_api_key
            )
            self._load_key_field(
                session, self.openai_key_input, _KEY_PREFIX + "openai_api_key", cfg.openai_api_key
            )
            self._load_key_field(
                session, self.gemini_key_input, _KEY_PREFIX + "gemini_api_key", cfg.gemini_api_key
            )
            self._load_key_field(
                session, self.voyage_key_input, _KEY_PREFIX + "voyage_api_key", cfg.voyage_api_key
            )

            self.embedding_top_n_input.setValue(
                repo.get_int(session, _KEY_PREFIX + "embedding_top_n", DEFAULT_EMBEDDING_TOP_N)
            )
            self.llm_top_n_input.setValue(repo.get_int(session, _KEY_PREFIX + "llm_top_n", DEFAULT_LLM_TOP_N))

    def _load_key_field(self, session, field: QLineEdit, key: str, env_value: str) -> None:
        """Loads a secret field WITHOUT ever pre-filling it with the .env
        value. If a DB override already exists, show it (the user typed it
        themselves, so re-showing it is expected). Otherwise leave the
        field blank and use a placeholder to say whether an .env value will
        be used - so Save can never silently copy the .env secret into the
        database (see the docstring on `app.core.config.AppConfig`)."""
        repo = self.context.settings_repo
        if repo.exists(session, key):
            field.setText(repo.get(session, key, ""))
            field.setPlaceholderText("")
        else:
            field.clear()
            field.setPlaceholderText(
                "Using key from .env (enter a value here to override)" if env_value else "Not set"
            )

    def _clear_anthropic_key(self) -> None:
        self._clear_key(self.anthropic_key_input, _KEY_PREFIX + "anthropic_api_key", self.context.config.anthropic_api_key)

    def _clear_openai_key(self) -> None:
        self._clear_key(self.openai_key_input, _KEY_PREFIX + "openai_api_key", self.context.config.openai_api_key)

    def _clear_gemini_key(self) -> None:
        self._clear_key(self.gemini_key_input, _KEY_PREFIX + "gemini_api_key", self.context.config.gemini_api_key)

    def _clear_voyage_key(self) -> None:
        self._clear_key(self.voyage_key_input, _KEY_PREFIX + "voyage_api_key", self.context.config.voyage_api_key)

    def _clear_key(self, field: QLineEdit, key: str, env_value: str) -> None:
        with session_scope() as session:
            self.context.settings_repo.delete(session, key)
        field.clear()
        field.setPlaceholderText(
            "Using key from .env (enter a value here to override)" if env_value else "Not set"
        )

    @staticmethod
    def _key_row(field: QLineEdit, clear_button: QPushButton) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field, 1)
        layout.addWidget(clear_button)
        return row

    def _save(self) -> None:
        with session_scope() as session:
            repo = self.context.settings_repo
            repo.set(
                session, _KEY_PREFIX + "local_only", "true" if self.local_only_check.isChecked() else "false"
            )
            repo.set(session, _KEY_PREFIX + "embedding_provider", self.embedding_provider_combo.currentData())
            repo.set(session, _KEY_PREFIX + "embedding_model", self.embedding_model_input.text())
            repo.set(session, _KEY_PREFIX + "llm_provider", self.llm_provider_combo.currentData())
            repo.set(session, _KEY_PREFIX + "llm_model", self.llm_model_input.text())
            repo.set(session, _KEY_PREFIX + "local_llm_base_url", self.local_llm_url_input.text())
            # Only ever persist an override when the user actually typed one -
            # an empty field means "keep using whatever .env/existing override
            # already applies", never "overwrite it with the .env value".
            if self.anthropic_key_input.text():
                repo.set(session, _KEY_PREFIX + "anthropic_api_key", self.anthropic_key_input.text(), secret=True)
            if self.openai_key_input.text():
                repo.set(session, _KEY_PREFIX + "openai_api_key", self.openai_key_input.text(), secret=True)
            if self.gemini_key_input.text():
                repo.set(session, _KEY_PREFIX + "gemini_api_key", self.gemini_key_input.text(), secret=True)
            if self.voyage_key_input.text():
                repo.set(session, _KEY_PREFIX + "voyage_api_key", self.voyage_key_input.text(), secret=True)
            repo.set(session, _KEY_PREFIX + "embedding_top_n", str(self.embedding_top_n_input.value()))
            repo.set(session, _KEY_PREFIX + "llm_top_n", str(self.llm_top_n_input.value()))
        QMessageBox.information(self, "Saved", "AI settings saved.")
