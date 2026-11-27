"""Sync engine: pulls cloud billing exports, validates them, and creates queued analyses."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from finops_app import repository as repo
from finops_app.connectors.aws import AwsConnector
from finops_app.connectors.azure import AzureConnector
from finops_app.connectors.base import BaseConnector
from finops_app.connectors.gcp import GcpConnector
from finops_app.models import Analysis, CloudConnection, utcnow
from finops_app.storage import Storage, make_key
from finops_app.uploads import check_contents

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from finops_app.jobs import JobQueue

logger = logging.getLogger(__name__)


def get_connector(conn: CloudConnection) -> BaseConnector:
    """Instantiate the appropriate connector implementation for a CloudConnection record."""
    if conn.provider == "aws":
        if not conn.role_arn or not conn.s3_bucket:
            raise ValueError(f"AWS connection {conn.name} is missing role_arn or s3_bucket")
        return AwsConnector(
            role_arn=conn.role_arn,
            external_id=conn.external_id,
            s3_bucket=conn.s3_bucket,
            s3_prefix=conn.s3_prefix or "",
            region=conn.region or "us-east-1",
        )
    elif conn.provider == "azure":
        return AzureConnector(
            storage_account=conn.s3_bucket or "",
            container=conn.s3_prefix or "",
            client_id=conn.role_arn or "",
            tenant_id=conn.region or "",
        )
    elif conn.provider == "gcp":
        return GcpConnector(
            project_id=conn.s3_bucket or "",
            dataset_id=conn.s3_prefix or "",
            table_name=conn.role_arn or "",
            service_account_email=conn.region or "",
        )
    raise ValueError(f"Unsupported cloud provider: {conn.provider}")


def sync_connection(
    session: Session,
    storage: Storage,
    queue: JobQueue,
    conn: CloudConnection,
    *,
    max_rows: int = 1_000_000,
    force: bool = False,
) -> Analysis | None:
    """Pull the newest billing export from a cloud connection and queue an analysis."""
    connector = get_connector(conn)
    logger.info("Starting sync for connection %s (%s)", conn.name, conn.provider)

    exports = connector.list_exports()
    if not exports:
        conn.last_synced_at = utcnow()
        conn.status = "active"
        conn.last_error = "No billing export files found in target bucket/prefix"
        session.flush()
        logger.info("No export files found for connection %s", conn.name)
        return None

    newest = exports[0]
    # Check if we already synced this export (unless force=True)
    if not force and conn.last_synced_at and newest.last_modified <= conn.last_synced_at:
        logger.info(
            "Connection %s already up to date (latest export %s at %s)",
            conn.name,
            newest.key,
            newest.last_modified,
        )
        return None

    logger.info("Downloading export %s (%d bytes)", newest.key, newest.size_bytes)
    filename = newest.key.split("/")[-1]
    with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        data = connector.download_export(newest.key, dest=tmp)
        if isinstance(data, (bytes, bytearray)):
            tmp.write(data)

    try:
        check = check_contents(tmp_path, max_rows=max_rows)
        storage_key = make_key(conn.org_id)
        storage.put_file(storage_key, tmp_path)

        analysis = repo.create_upload(
            session,
            conn.org_id,
            original_filename=filename,
            storage_key=storage_key,
            size_bytes=check.size_bytes,
            row_count=check.row_count,
            connection_id=conn.id,
        )

        conn.status = "active"
        conn.last_synced_at = newest.last_modified
        conn.last_error = None
        repo.audit(
            session,
            conn.org_id,
            "connection.synced",
            "cloud_connection",
            conn.id,
            {"filename": filename, "export_key": newest.key, "analysis_id": analysis.id},
        )
        session.commit()

        queue.enqueue(conn.org_id, analysis.id)
        logger.info(
            "Sync successful for %s: queued analysis %s with %d rows",
            conn.name,
            analysis.id,
            check.row_count,
        )
        return analysis
    except Exception as exc:
        conn.status = "error"
        conn.last_error = str(exc)
        session.flush()
        logger.error("Sync failed for connection %s: %s", conn.name, exc)
        raise
    finally:
        tmp_path.unlink(missing_ok=True)


def sync_all_active_connections(
    session: Session,
    storage: Storage,
    queue: JobQueue,
    *,
    max_rows: int = 1_000_000,
) -> list[tuple[str, str | None]]:
    """Sync all active connections across all organisations.

    Returns a list of (connection_id, analysis_id_or_none) pairs.
    """
    active_conns = repo.all_active_connections(session)
    logger.info("Found %d active cloud connections to sync", len(active_conns))
    results: list[tuple[str, str | None]] = []

    for conn in active_conns:
        try:
            analysis = sync_connection(session, storage, queue, conn, max_rows=max_rows)
            results.append((conn.id, analysis.id if analysis else None))
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error("Failed to sync connection %s: %s", conn.name, exc)
            # Re-fetch conn in new transaction to record error
            try:
                db_conn = repo.get_connection(session, conn.org_id, conn.id)
                if db_conn:
                    db_conn.status = "error"
                    db_conn.last_error = str(exc)
                    session.commit()
            except Exception:
                session.rollback()
            results.append((conn.id, None))

    return results
