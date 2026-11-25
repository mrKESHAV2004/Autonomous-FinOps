"""Operational commands: ``finops-db``, ``finops-worker`` and ``finops-cleanup``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import timedelta

from finops_app import repository as repo
from finops_app.config import Config
from finops_app.db import Database, upgrade
from finops_app.jobs import QUEUE_NAME
from finops_app.logging_config import configure_logging
from finops_app.models import utcnow
from finops_app.storage import LocalStorage, Storage

logger = logging.getLogger(__name__)


def db_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finops-db", description="Manage the database schema.")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("upgrade", help="apply migrations (default: to the latest)")
    up.add_argument("revision", nargs="?", default="head")
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    configure_logging(cfg.log_level, json_logs=cfg.log_json)
    upgrade(cfg.database_url, args.revision)
    return 0


def worker_main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="finops-worker", description="Run analysis jobs from Redis (FINOPS_REDIS_URL)."
    ).parse_args(argv)
    cfg = Config.from_env()
    configure_logging(cfg.log_level, json_logs=cfg.log_json)
    if not cfg.redis_url:
        logger.error("FINOPS_REDIS_URL is not set; without it the web app runs jobs itself")
        return 2

    from redis import Redis
    from rq import Queue, Worker

    connection = Redis.from_url(cfg.redis_url)
    Worker([Queue(QUEUE_NAME, connection=connection)], connection=connection).work()
    return 0


def delete_expired_uploads(db: Database, storage: Storage, retention_days: int) -> int:
    """Delete raw files older than ``retention_days``; results are kept."""
    cutoff = utcnow() - timedelta(days=retention_days)
    deleted = 0
    with db.session() as session:
        for dataset in repo.datasets_with_raw_before(session, cutoff):
            storage.delete(dataset.storage_key)
            dataset.raw_deleted_at = utcnow()
            repo.audit(session, dataset.org_id, "dataset.raw_deleted", "dataset", dataset.id)
            deleted += 1
    return deleted


def cleanup_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="finops-cleanup", description="Delete raw uploads past the retention period."
    )
    parser.add_argument("--days", type=int, help="override FINOPS_RETENTION_DAYS")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    configure_logging(cfg.log_level, json_logs=cfg.log_json)
    days = args.days if args.days is not None else cfg.retention_days
    if days < 1:
        parser.error("--days must be at least 1")

    db = Database(cfg.database_url)
    try:
        count = delete_expired_uploads(db, LocalStorage(cfg.upload_dir), days)
    finally:
        db.dispose()
    logger.info("Retention cleanup finished", extra={"deleted": count, "days": days})
    sys.stdout.write(f"Deleted {count} raw upload(s) older than {days} days.\n")
    return 0
