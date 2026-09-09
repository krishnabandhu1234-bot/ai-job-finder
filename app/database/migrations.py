"""Lightweight schema migration runner.

We deliberately don't use Alembic: this is a single-file embedded SQLite
database shipped inside a frozen executable, and Alembic's autogeneration
/ env.py machinery adds packaging complexity (script location resolution
inside a PyInstaller bundle) with little benefit for a schema this size.

Instead: `Base.metadata.create_all()` (called from `db.init_engine`)
always creates a brand-new database at the CURRENT full schema. For
databases created by an older version of the app, `run_migrations()`
applies any additive migrations (new columns/tables) that were introduced
since. Each migration is a plain function given a raw SQLAlchemy
connection; migrations must be additive and idempotent-safe (guard with
`IF NOT EXISTS` / catch "duplicate column" where relevant) since SQLite's
ALTER TABLE support is limited.

To add a migration in a later phase: append a new
`(version, description, fn)` tuple to MIGRATIONS. Never renumber or edit
existing entries once released — that breaks upgrades for users who
already applied them.
"""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import Connection, Engine, text

logger = logging.getLogger(__name__)

Migration = tuple[int, str, Callable[[Connection], None]]


def _baseline(_conn: Connection) -> None:
    """No-op: version 1 is whatever `Base.metadata.create_all()` produces.

    This entry exists so version numbering starts at 1 and so
    `run_migrations` has something to stamp on a fresh install.
    """


_OLD_DEFAULT_MIN_EMAIL_SCORE = 85


def _relax_stale_default_min_email_score(conn: Connection) -> None:
    """Corrects the old, empirically-unreachable 85 email threshold.

    85 was chosen to mean "strong match" but, measured against ~750 real
    postings, a genuinely strong match scores about 78-80 on this scale
    (several components stay deliberately neutral when a posting doesn't
    state something, capping the achievable total). The practical effect
    was that the daily email silently never sent - the app's main output,
    never firing. `DEFAULT_MIN_EMAIL_SCORE` is now 75.

    Only rows still holding exactly the old default are updated. A user
    who deliberately set 85 themselves is indistinguishable from one who
    never touched it, so this does very slightly risk overriding a
    deliberate choice - accepted because the alternative (leaving every
    existing install permanently emailing nothing) is clearly worse, and
    the value stays editable on the Job Search Profile page."""
    from app.core.constants import DEFAULT_MIN_EMAIL_SCORE

    result = conn.execute(
        text("UPDATE user_preferences SET min_email_score = :new WHERE min_email_score = :old"),
        {"new": DEFAULT_MIN_EMAIL_SCORE, "old": _OLD_DEFAULT_MIN_EMAIL_SCORE},
    )
    if result.rowcount:
        logger.info(
            "Relaxed min_email_score from %s to %s for %d preference row(s) - "
            "the old value was unreachable in practice, so no email would ever have sent.",
            _OLD_DEFAULT_MIN_EMAIL_SCORE, DEFAULT_MIN_EMAIL_SCORE, result.rowcount,
        )


def _add_company_candidates(conn: Connection) -> None:
    """Adds the company-candidate queue (see `models.CompanyCandidate`).

    A brand-new database already has this table from `create_all()`; this
    exists for databases created by an earlier version. `IF NOT EXISTS`
    keeps it safe in both cases."""
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS company_candidates ("
            "id INTEGER PRIMARY KEY, "
            "name VARCHAR(255) NOT NULL, "
            "normalized_name VARCHAR(255) NOT NULL, "
            "status VARCHAR(20) DEFAULT 'pending', "
            "discovered_from VARCHAR(60) DEFAULT '', "
            "attempts INTEGER DEFAULT 0, "
            "last_attempt_at DATETIME, "
            "resolved_source_type VARCHAR(50) DEFAULT '', "
            "created_at DATETIME, "
            "CONSTRAINT uq_company_candidate_name UNIQUE (normalized_name)"
            ")"
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_company_candidates_status "
            "ON company_candidates (status)"
        )
    )


MIGRATIONS: list[Migration] = [
    (1, "baseline schema", _baseline),
    (2, "relax unreachable default min_email_score", _relax_stale_default_min_email_score),
    (3, "company candidate queue for unbounded discovery", _add_company_candidates),
]


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "applied_at TEXT NOT NULL, "
                "description VARCHAR(500) DEFAULT ''"
                ")"
            )
        )
        applied = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}

        for version, description, fn in MIGRATIONS:
            if version in applied:
                continue
            logger.info("Applying migration %s: %s", version, description)
            fn(conn)
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, applied_at, description) "
                    "VALUES (:v, datetime('now'), :d)"
                ),
                {"v": version, "d": description},
            )
