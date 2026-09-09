from __future__ import annotations

from sqlalchemy import inspect, select

from app.core.constants import DEFAULT_MIN_EMAIL_SCORE
from app.database import db
from app.database.migrations import run_migrations
from app.database.models import Setting

EXPECTED_TABLES = {
    "users",
    "resumes",
    "candidate_profiles",
    "job_sources",
    "jobs",
    "job_embeddings",
    "job_matches",
    "user_preferences",
    "feedback",
    "email_history",
    "scan_history",
    "application_history",
    "settings",
    "schema_migrations",
}


def test_all_expected_tables_are_created(db_session):
    inspector = inspect(db.get_engine())
    table_names = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(table_names)


def test_migrations_are_idempotent(db_session):
    # Should not raise, and should not create duplicate rows for version 1.
    run_migrations(db.get_engine())
    run_migrations(db.get_engine())
    rows = db_session.execute(select(Setting)).all()
    assert rows == []  # unrelated table, just confirms no crash/side effects


def test_settings_roundtrip_plain(db_session, settings_repo):
    settings_repo.set(db_session, "some.key", "hello")
    assert settings_repo.get(db_session, "some.key") == "hello"


def test_settings_roundtrip_secret_is_encrypted_at_rest(db_session, settings_repo):
    settings_repo.set(db_session, "api.key", "sk-super-secret", secret=True)

    raw_row = db_session.scalar(select(Setting).where(Setting.key == "api.key"))
    assert raw_row.is_secret is True
    assert raw_row.value != "sk-super-secret"  # never stored in plain text

    assert settings_repo.get(db_session, "api.key") == "sk-super-secret"


def test_settings_get_bool_and_int_defaults(db_session, settings_repo):
    assert settings_repo.get_bool(db_session, "missing.flag", default=True) is True
    assert settings_repo.get_int(db_session, "missing.number", default=42) == 42

    settings_repo.set(db_session, "flag", "true")
    settings_repo.set(db_session, "number", "7")
    assert settings_repo.get_bool(db_session, "flag") is True
    assert settings_repo.get_int(db_session, "number") == 7


def test_user_and_preferences_have_sane_defaults(db_session, users_repo, preferences_repo):
    user = users_repo.get_or_create_default_user(db_session, "test@example.com")
    prefs = preferences_repo.get_active(db_session, user.id)

    assert prefs.work_arrangement == "any"
    # 75, not a higher-sounding 85: measured against real postings, a
    # genuinely strong match scores ~78-80, so an 85 default meant the
    # daily email silently never sent. See DEFAULT_MIN_EMAIL_SCORE.
    assert prefs.min_email_score == DEFAULT_MIN_EMAIL_SCORE
    assert prefs.max_email_jobs == 15
    assert prefs.target_titles == []


def test_get_or_create_default_user_is_idempotent(db_session, users_repo):
    first = users_repo.get_or_create_default_user(db_session, "test@example.com")
    second = users_repo.get_or_create_default_user(db_session, "test@example.com")
    assert first.id == second.id


def test_preferences_save_updates_fields(db_session, users_repo, preferences_repo):
    user = users_repo.get_or_create_default_user(db_session, "test@example.com")
    prefs = preferences_repo.get_active(db_session, user.id)

    preferences_repo.save(
        db_session,
        prefs,
        target_titles=["Thermal Engineer", "CFD Engineer"],
        salary_min=150000,
        excluded_companies=["Acme Corp"],
    )

    reloaded = preferences_repo.get_active(db_session, user.id)
    assert reloaded.target_titles == ["Thermal Engineer", "CFD Engineer"]
    assert reloaded.salary_min == 150000
    assert reloaded.excluded_companies == ["Acme Corp"]


def test_preferences_save_rejects_unknown_field(db_session, users_repo, preferences_repo):
    user = users_repo.get_or_create_default_user(db_session, "test@example.com")
    prefs = preferences_repo.get_active(db_session, user.id)
    try:
        preferences_repo.save(db_session, prefs, not_a_real_field="x")
        assert False, "expected AttributeError"
    except AttributeError:
        pass


def test_settings_get_survives_a_corrupted_secret(db_session, settings_repo):
    """A single undecryptable secret must degrade to "unset", not crash the
    caller - regression test for the Phase 1 review finding where a bad
    stored secret took down the whole app at startup."""
    settings_repo.set(db_session, "api.key", "sk-real-secret", secret=True)

    row = db_session.scalar(select(Setting).where(Setting.key == "api.key"))
    row.value = "not-a-valid-fernet-token"
    db_session.flush()

    assert settings_repo.get(db_session, "api.key", default="fallback") == "fallback"


def test_settings_exists_and_delete(db_session, settings_repo):
    assert settings_repo.exists(db_session, "some.key") is False
    settings_repo.set(db_session, "some.key", "value")
    assert settings_repo.exists(db_session, "some.key") is True
    settings_repo.delete(db_session, "some.key")
    assert settings_repo.exists(db_session, "some.key") is False
    assert settings_repo.get(db_session, "some.key", default="gone") == "gone"


def test_dashboard_stats_on_empty_database(db_session, dashboard_repo):
    stats = dashboard_repo.get_stats(db_session)
    assert stats.new_jobs_today == 0
    assert stats.excellent_matches == 0
    assert stats.strong_matches == 0
    assert stats.email_sent_today is False
    assert stats.last_scan_at is None
    assert stats.top_matches == []


def test_migration_relaxes_stale_default_min_email_score(tmp_path):
    """Migration 2: the old 85 default was unreachable in practice, so
    every existing install would silently never send an email. Rows still
    holding exactly the old default are corrected; a deliberately-chosen
    different value is left alone."""
    from sqlalchemy import create_engine, text

    from app.core.constants import DEFAULT_MIN_EMAIL_SCORE

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE user_preferences (id INTEGER PRIMARY KEY, min_email_score INTEGER)"
        ))
        conn.execute(text(
            "INSERT INTO user_preferences (id, min_email_score) VALUES (1, 85), (2, 95), (3, 60)"
        ))

    run_migrations(engine)

    with engine.begin() as conn:
        scores = dict(conn.execute(text("SELECT id, min_email_score FROM user_preferences")).all())
    assert scores[1] == DEFAULT_MIN_EMAIL_SCORE  # stale default corrected
    assert scores[2] == 95  # deliberate stricter choice untouched
    assert scores[3] == 60  # deliberate looser choice untouched


def test_migrations_are_idempotent(tmp_path):
    """Running twice must not re-apply anything - migrations are stamped
    in schema_migrations."""
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'twice.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE user_preferences (id INTEGER PRIMARY KEY, min_email_score INTEGER)"
        ))
        conn.execute(text("INSERT INTO user_preferences (id, min_email_score) VALUES (1, 85)"))

    run_migrations(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE user_preferences SET min_email_score = 85 WHERE id = 1"))
    run_migrations(engine)  # second run must be a no-op

    with engine.begin() as conn:
        score = conn.execute(text("SELECT min_email_score FROM user_preferences")).scalar()
        applied = conn.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar()
    assert score == 85  # not re-applied
    assert applied == len(__import__("app.database.migrations", fromlist=["MIGRATIONS"]).MIGRATIONS)
