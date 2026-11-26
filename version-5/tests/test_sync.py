from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from finops_app import repository as repo
from finops_app.connectors.base import DiscoveredExport
from finops_app.connectors.sync import sync_all_active_connections, sync_connection
from finops_app.db import Database, upgrade
from finops_app.jobs import InlineQueue
from finops_app.models import Organization
from finops_app.storage import LocalStorage


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    url = f"sqlite:///{tmp_path / 'sync_test.db'}"
    upgrade(url)
    database = Database(url)
    yield database
    database.dispose()


def test_sync_connection_success(db: Database, tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "uploads")
    queue = InlineQueue(db, storage)

    # Simple valid FOCUS CSV bytes
    sample_csv = (
        b"ChargePeriodStart,ChargePeriodEnd,ProviderName,BillingAccountId,SubAccountId,"
        b"ServiceName,ServiceCategory,RegionId,ResourceId,ChargeCategory,EffectiveCost,BilledCost,"
        b"ConsumedQuantity,ConsumedUnit\n"
        b"2026-11-01,2026-11-02,AWS,111,222,AmazonEC2,Compute,us-east-1,i-1234,Usage,10.5,10.5,24,Hours\n"
        b"2026-11-02,2026-11-03,AWS,111,222,AmazonEC2,Compute,us-east-1,i-1234,Usage,10.5,10.5,24,Hours\n"
    )

    with db.session() as session:
        org = Organization(slug="sync-org", name="Sync Org")
        session.add(org)
        session.flush()

        conn = repo.create_connection(
            session,
            org.id,
            provider="aws",
            name="Prod AWS",
            role_arn="arn:aws:iam::123456789012:role/FinOpsRole",
            s3_bucket="my-billing-bucket",
            s3_prefix="cur/",
            status="active",
        )
        session.commit()

        mock_connector = MagicMock()
        mock_connector.list_exports.return_value = [
            DiscoveredExport(
                key="cur/2026-11/focus_export.csv",
                last_modified=datetime(2026, 11, 26, 12, 0, tzinfo=UTC),
                size_bytes=len(sample_csv),
            )
        ]
        mock_connector.download_export.return_value = sample_csv

        with patch("finops_app.connectors.sync.get_connector", return_value=mock_connector):
            analysis = sync_connection(session, storage, queue, conn)
            assert analysis is not None
            assert conn.status == "active"
            assert conn.last_synced_at == datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
            assert conn.last_error is None
            assert analysis.dataset.connection_id == conn.id
            assert analysis.dataset.original_filename == "focus_export.csv"


def test_sync_connection_already_up_to_date(db: Database, tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "uploads")
    queue = InlineQueue(db, storage)

    with db.session() as session:
        org = Organization(slug="sync-org-2", name="Sync Org 2")
        session.add(org)
        session.flush()

        conn = repo.create_connection(
            session,
            org.id,
            provider="aws",
            name="Prod AWS",
            role_arn="arn:aws:iam::123456789012:role/FinOpsRole",
            s3_bucket="my-billing-bucket",
            status="active",
        )
        conn.last_synced_at = datetime(2026, 11, 26, 14, 0, tzinfo=UTC)
        session.commit()

        mock_connector = MagicMock()
        mock_connector.list_exports.return_value = [
            DiscoveredExport(
                key="cur/2026-11/focus_export.csv",
                last_modified=datetime(2026, 11, 26, 12, 0, tzinfo=UTC),
                size_bytes=100,
            )
        ]

        with patch("finops_app.connectors.sync.get_connector", return_value=mock_connector):
            analysis = sync_connection(session, storage, queue, conn)
            assert analysis is None
            mock_connector.download_export.assert_not_called()


def test_sync_all_active_connections(db: Database, tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "uploads")
    queue = InlineQueue(db, storage)

    with db.session() as session:
        org = Organization(slug="sync-org-3", name="Sync Org 3")
        session.add(org)
        session.flush()

        conn1 = repo.create_connection(
            session,
            org.id,
            provider="aws",
            name="AWS 1",
            role_arn="arn:1",
            s3_bucket="b1",
            status="active",
        )
        repo.create_connection(
            session,
            org.id,
            provider="aws",
            name="AWS 2",
            role_arn="arn:2",
            s3_bucket="b2",
            status="pending",
        )
        session.commit()

        mock_connector = MagicMock()
        mock_connector.list_exports.return_value = []

        with patch("finops_app.connectors.sync.get_connector", return_value=mock_connector):
            results = sync_all_active_connections(session, storage, queue)
            # Only conn1 is active
            assert len(results) == 1
            assert results[0][0] == conn1.id
            assert results[0][1] is None
