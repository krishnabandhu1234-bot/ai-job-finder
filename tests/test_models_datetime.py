"""Regression tests for the naive-UTC-everywhere datetime convention.

SQLite has no real timezone-aware column type: SQLAlchemy silently strips
tzinfo from a timezone-aware Python datetime when it round-trips through
a `Job`/`ScanHistory`/etc. row. If column defaults used
`datetime.now(timezone.utc)` (aware) while application code compared
against it with a freshly-created aware "now", any Python-level arithmetic
(not a SQL WHERE clause - see below) would raise `TypeError: can't
subtract offset-naive and offset-aware datetimes` the moment code tried to
compute something like "how long has this job been inactive". This
suite locks in the fix: every datetime the app produces (column defaults
AND app.database.models.utc_now()) is naive-but-UTC, so they're always
comparable to each other.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.database.models import Setting, utc_now


def test_utc_now_is_naive():
    now = utc_now()
    assert now.tzinfo is None


def test_column_default_round_trips_as_naive(db_session):
    row = Setting(key="k", value="v")
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    assert row.updated_at.tzinfo is None


def test_arithmetic_between_fresh_now_and_db_loaded_value_does_not_raise(db_session):
    row = Setting(key="k", value="v")
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    # This is exactly the pattern that would previously blow up: comparing
    # "now" against a value that just came back from the database.
    delta = utc_now() - row.updated_at
    assert isinstance(delta, dt.timedelta)
    assert delta.total_seconds() >= 0


def test_sql_level_comparison_against_utc_now_still_works(db_session):
    row = Setting(key="k", value="v")
    db_session.add(row)
    db_session.flush()

    earlier = utc_now() - dt.timedelta(minutes=5)
    matches = db_session.scalars(select(Setting).where(Setting.updated_at >= earlier)).all()
    assert row in matches
