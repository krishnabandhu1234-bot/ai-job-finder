"""Engine/session management.

A single module-level engine is created lazily against the configured
SQLite path. `session_scope()` is the standard way to get a session with
commit/rollback handled for you; use it from repository functions and
services rather than constructing sessions ad hoc.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_engine(db_path: Path, echo: bool = False) -> Engine:
    global _engine, _SessionLocal

    db_path.parent.mkdir(parents=True, exist_ok=True)
    # `check_same_thread=False`: the app legitimately opens sessions from
    # multiple OS threads over time (Qt background workers for scan/rank,
    # and the APScheduler thread for scheduled runs) - never concurrently
    # sharing one Session/connection, always one thread at a time via
    # `session_scope()`. Without this, SQLAlchemy's connection pool can
    # hand a pooled sqlite3 connection to a different thread than the one
    # that created it, which pysqlite rejects outright.
    _engine = create_engine(
        f"sqlite:///{db_path}", echo=echo, future=True, connect_args={"check_same_thread": False}
    )
    event.listen(_engine, "connect", _enable_sqlite_foreign_keys)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)

    Base.metadata.create_all(_engine)
    logger.info("Database engine initialized at %s", db_path)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() at startup.")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() at startup.")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_tests() -> None:
    """Used by the test suite between tests when it wants a fresh in-memory DB."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
