"""Database engine, sessions and migrations.

The web app opens one session per request (:func:`get_session`); the worker
uses :meth:`Database.session` as a context manager. Schema changes go through
Alembic (``src/finops_app/migrations``), applied with :func:`upgrade`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from flask import Flask, current_app, g
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
EXTENSION_KEY = "finops_db"


class Database:
    """An engine plus a session factory for one database URL."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = _make_engine(url)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def new_session(self) -> Session:
        return self._factory()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Commit on success, roll back on error, always close."""
        session = self.new_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


def _make_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"future": True}
    if url.startswith("sqlite"):
        # The web app and its background thread share the file.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def alembic_config(url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url: str, revision: str = "head") -> None:
    """Apply migrations up to ``revision``."""
    command.upgrade(alembic_config(url), revision)
    logger.info("Database migrated", extra={"revision": revision})


def downgrade(url: str, revision: str) -> None:
    """Revert migrations down to ``revision`` (``"base"`` empties the schema)."""
    command.downgrade(alembic_config(url), revision)


def init_app(app: Flask, db: Database) -> None:
    app.extensions[EXTENSION_KEY] = db

    @app.teardown_appcontext
    def _close_session(_exc: BaseException | None) -> None:
        session: Session | None = g.pop("db_session", None)
        if session is not None:
            session.close()


def get_db() -> Database:
    db: Database = current_app.extensions[EXTENSION_KEY]
    return db


def get_session() -> Session:
    """The current request's session (opened on first use)."""
    if "db_session" not in g:
        g.db_session = get_db().new_session()
    session: Session = g.db_session
    return session
