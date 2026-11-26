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
from finops_app.storage import Storage, build_storage

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
        count = delete_expired_uploads(db, build_storage(cfg), days)
    finally:
        db.dispose()
    logger.info("Retention cleanup finished", extra={"deleted": count, "days": days})
    sys.stdout.write(f"Deleted {count} raw upload(s) older than {days} days.\n")
    return 0


def sync_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="finops-sync",
        description="Ingest latest billing exports from active cloud connections.",
    )
    parser.add_argument("--connection-id", help="sync a specific connection id only")
    parser.add_argument(
        "--force",
        action="store_true",
        help="force download even if last_modified has not changed",
    )
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    configure_logging(cfg.log_level, json_logs=cfg.log_json)

    from sqlalchemy import select

    from finops_app.connectors.sync import sync_all_active_connections, sync_connection
    from finops_app.jobs import InlineQueue, JobQueue, RQQueue
    from finops_app.models import CloudConnection

    db = Database(cfg.database_url)
    storage = build_storage(cfg)
    queue: JobQueue = RQQueue(cfg.redis_url) if cfg.redis_url else InlineQueue(db, storage)

    try:
        with db.session() as session:
            if args.connection_id:
                conn = session.scalars(
                    select(CloudConnection).where(CloudConnection.id == args.connection_id)
                ).first()
                if not conn:
                    sys.stderr.write(f"Connection {args.connection_id} not found.\n")
                    return 1
                analysis = sync_connection(
                    session, storage, queue, conn, max_rows=cfg.max_rows, force=args.force
                )
                session.commit()
                if analysis:
                    sys.stdout.write(f"Synced connection {conn.name} -> analysis {analysis.id}\n")
                else:
                    sys.stdout.write(f"Connection {conn.name} is up to date.\n")
            else:
                results = sync_all_active_connections(
                    session, storage, queue, max_rows=cfg.max_rows
                )
                session.commit()
                synced_count = sum(1 for _, a in results if a is not None)
                sys.stdout.write(f"Synced {synced_count} of {len(results)} active connection(s).\n")
    finally:
        db.dispose()
    return 0
