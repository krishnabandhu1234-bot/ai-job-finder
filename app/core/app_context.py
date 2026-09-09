"""Wires together config, logging, database, and repositories once at
startup, and hands out a single `AppContext` instance the UI layer reads
from. This avoids scattering `get_config()` / ad-hoc session creation
throughout the UI, and gives tests a single seam to substitute a temp
database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import AppConfig, get_config
from app.core.logging_setup import configure_logging
from app.core.security import SecretBox, get_secret_box
from app.database import db
from app.database.migrations import run_migrations
from app.database.repository import (
    ApplicationHistoryRepository,
    CandidateProfileRepository,
    CompanyRepository,
    DashboardRepository,
    FeedbackRepository,
    JobEmbeddingRepository,
    JobMatchRepository,
    CompanyCandidateRepository,
    JobSourceRepository,
    PreferencesRepository,
    ResumeRepository,
    ScanHistoryRepository,
    SettingsRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    config: AppConfig
    secret_box: SecretBox
    settings_repo: SettingsRepository
    users_repo: UserRepository
    preferences_repo: PreferencesRepository
    dashboard_repo: DashboardRepository
    resumes_repo: ResumeRepository
    candidate_profile_repo: CandidateProfileRepository
    job_sources_repo: JobSourceRepository
    company_candidates_repo: CompanyCandidateRepository
    companies_repo: CompanyRepository
    job_embeddings_repo: JobEmbeddingRepository
    job_matches_repo: JobMatchRepository
    feedback_repo: FeedbackRepository
    applications_repo: ApplicationHistoryRepository
    scan_history_repo: ScanHistoryRepository


_context: AppContext | None = None


def bootstrap(config: AppConfig | None = None) -> AppContext:
    """Initializes logging, the database engine/schema, and repositories.

    Safe to call more than once (e.g. from tests) - later calls reuse the
    already-initialized engine unless `db.reset_engine_for_tests()` was
    called first.
    """
    global _context

    cfg = config or get_config()
    configure_logging(cfg.logs_dir, cfg.log_level)

    db.init_engine(cfg.database_path)
    run_migrations(db.get_engine())

    secret_box = get_secret_box(cfg.data_dir, cfg.encryption_key_override)

    _context = AppContext(
        config=cfg,
        secret_box=secret_box,
        settings_repo=SettingsRepository(secret_box),
        users_repo=UserRepository(),
        preferences_repo=PreferencesRepository(),
        dashboard_repo=DashboardRepository(),
        resumes_repo=ResumeRepository(),
        candidate_profile_repo=CandidateProfileRepository(),
        job_sources_repo=JobSourceRepository(),
        company_candidates_repo=CompanyCandidateRepository(),
        companies_repo=CompanyRepository(),
        job_embeddings_repo=JobEmbeddingRepository(),
        job_matches_repo=JobMatchRepository(),
        feedback_repo=FeedbackRepository(),
        applications_repo=ApplicationHistoryRepository(),
        scan_history_repo=ScanHistoryRepository(),
    )
    logger.info("Application context bootstrapped (demo_mode=%s)", cfg.demo_mode)
    return _context


def get_context() -> AppContext:
    if _context is None:
        raise RuntimeError("AppContext not bootstrapped. Call app_context.bootstrap() first.")
    return _context
