"""Shared pytest fixtures.

The test suite never touches the real %LOCALAPPDATA%\\AIJobFinder data
directory or calls any external API/network - everything runs against a
temp SQLite DB and, for Qt tests, an offscreen platform plugin so tests
can run headless (e.g. in CI).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from app.core.app_context import AppContext
from app.core.config import AppConfig, reload_config_for_tests
from app.core.security import get_secret_box
from app.database import db
from app.database.migrations import run_migrations
from app.database.repository import (
    ApplicationHistoryRepository,
    CandidateProfileRepository,
    CompanyCandidateRepository,
    CompanyRepository,
    DashboardRepository,
    FeedbackRepository,
    JobEmbeddingRepository,
    JobMatchRepository,
    JobSourceRepository,
    PreferencesRepository,
    ResumeRepository,
    ScanHistoryRepository,
    SettingsRepository,
    UserRepository,
)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Fails any test that would make a real HTTP request.

    The suite must stay runnable offline and must never depend on a third
    party being up. Enforcing that is worth an autouse fixture rather
    than a convention, because the pipeline now reaches for the network
    in more places (company harvesting, cross-company search) and a
    missing stub would otherwise show up as a slow, flaky test rather
    than a clear failure.

    Tests that exercise the HTTP layer install their own
    `httpx.MockTransport` over `_transport_override`, which replaces this
    one, so they are unaffected."""
    import httpx

    from app.jobs import http_client

    def _refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            f"Test attempted a real network request to {request.url}. "
            "Stub the caller, or install an httpx.MockTransport via "
            "http_client._transport_override."
        )

    monkeypatch.setattr(http_client, "_transport_override", httpx.MockTransport(_refuse))


@pytest.fixture
def app_config(tmp_path, monkeypatch) -> AppConfig:
    monkeypatch.setenv("AIJF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIJF_DEMO_MODE", "true")
    monkeypatch.setenv("AIJF_LOG_LEVEL", "DEBUG")
    config = reload_config_for_tests()
    yield config
    reload_config_for_tests()


@pytest.fixture
def db_session(app_config):
    db.reset_engine_for_tests()
    db.init_engine(app_config.database_path)
    run_migrations(db.get_engine())
    with db.session_scope() as session:
        yield session
    db.reset_engine_for_tests()


@pytest.fixture
def secret_box(app_config):
    return get_secret_box(app_config.data_dir)


@pytest.fixture
def settings_repo(secret_box) -> SettingsRepository:
    return SettingsRepository(secret_box)


@pytest.fixture
def users_repo() -> UserRepository:
    return UserRepository()


@pytest.fixture
def preferences_repo() -> PreferencesRepository:
    return PreferencesRepository()


@pytest.fixture
def dashboard_repo() -> DashboardRepository:
    return DashboardRepository()


@pytest.fixture
def app_context(app_config, secret_box) -> AppContext:
    """A full `AppContext` wired to the same temp database as `db_session`,
    for tests exercising a service/orchestrator (ranker, email, pipeline)
    that takes the whole context rather than individual repos."""
    return AppContext(
        config=app_config,
        secret_box=secret_box,
        settings_repo=SettingsRepository(secret_box),
        users_repo=UserRepository(),
        preferences_repo=PreferencesRepository(),
        dashboard_repo=DashboardRepository(),
        resumes_repo=ResumeRepository(),
        candidate_profile_repo=CandidateProfileRepository(),
        job_sources_repo=JobSourceRepository(),
        companies_repo=CompanyRepository(),
        company_candidates_repo=CompanyCandidateRepository(),
        job_embeddings_repo=JobEmbeddingRepository(),
        job_matches_repo=JobMatchRepository(),
        feedback_repo=FeedbackRepository(),
        applications_repo=ApplicationHistoryRepository(),
        scan_history_repo=ScanHistoryRepository(),
    )
