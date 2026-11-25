from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, select

from factories import finding, result
from finops_app import repository as repo
from finops_app.db import Database, downgrade, upgrade
from finops_app.models import Analysis, AuditLog, Dataset, Organization, utcnow

# CI also runs these against PostgreSQL (see .github/workflows/ci.yml).
POSTGRES_URL = os.environ.get("FINOPS_TEST_POSTGRES_URL")
BACKENDS = ["sqlite"] + (["postgres"] if POSTGRES_URL else [])


@pytest.fixture(params=BACKENDS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Database]:
    url = POSTGRES_URL if request.param == "postgres" else f"sqlite:///{tmp_path / 'test.db'}"
    assert url
    upgrade(url)
    database = Database(url)
    yield database
    database.dispose()
    if request.param == "postgres":
        downgrade(url, "base")


def _upload(session, org_id: str, key: str = "k1") -> Analysis:
    return repo.create_upload(
        session, org_id, original_filename="bill.csv", storage_key=key, size_bytes=10, row_count=2
    )


def test_migration_creates_every_table(db: Database) -> None:
    tables = set(inspect(db.engine).get_table_names())
    assert {
        "organizations", "users", "memberships", "datasets", "analyses",
        "findings", "forecast_points", "audit_log", "alembic_version",
    } <= tables  # fmt: skip


def test_default_org_is_created_once(db: Database) -> None:
    with db.session() as s:
        first = repo.default_org_id(s)
    with db.session() as s:
        assert repo.default_org_id(s) == first
        assert len(s.scalars(select(Organization)).all()) == 1


def test_scoped_refuses_a_missing_org() -> None:
    with pytest.raises(ValueError, match="org_id is required"):
        repo.scoped(Analysis, "")


def test_upload_creates_dataset_queued_analysis_and_audit(db: Database) -> None:
    with db.session() as s:
        org = repo.default_org_id(s)
        analysis = _upload(s, org)
        aid = analysis.id
    with db.session() as s:
        stored = repo.get_analysis(s, org, aid)
        assert stored is not None and stored.status == "queued"
        assert stored.dataset.original_filename == "bill.csv"
        assert s.scalars(select(AuditLog.action)).all() == ["analysis.queued"]


def test_other_orgs_cannot_see_an_analysis(db: Database) -> None:
    with db.session() as s:
        mine = repo.default_org_id(s)
        other = Organization(slug="other", name="Other")
        s.add(other)
        s.flush()
        aid = _upload(s, mine).id
        _upload(s, other.id, key="k2")
    with db.session() as s:
        assert repo.get_analysis(s, other.id, aid) is None
        assert [a.org_id for a in repo.list_analyses(s, other.id)] == [other.id]
        assert len(repo.list_analyses(s, mine)) == 1


def test_result_round_trips_through_the_database(db: Database) -> None:
    original = result(
        findings=(finding(resource_key="a", estimated_waste=5.0), finding(resource_key="b")),
    )
    with db.session() as s:
        org = repo.default_org_id(s)
        analysis = _upload(s, org)
        repo.mark_running(s, analysis)
        repo.save_result(s, analysis, original)
        aid = analysis.id
    with db.session() as s:
        stored = repo.get_analysis(s, org, aid)
        assert stored is not None and stored.status == "succeeded"
        assert stored.started_at is not None and stored.finished_at is not None
        assert repo.load_result(stored) == original


def test_load_result_refuses_unfinished_analysis(db: Database) -> None:
    with db.session() as s:
        analysis = _upload(s, repo.default_org_id(s))
        with pytest.raises(ValueError, match="no result"):
            repo.load_result(analysis)


def test_mark_failed_records_message(db: Database) -> None:
    with db.session() as s:
        analysis = _upload(s, repo.default_org_id(s))
        repo.mark_failed(s, analysis, "Missing required column(s): EffectiveCost")
        assert analysis.status == "failed" and analysis.finished_at is not None
        assert "EffectiveCost" in (analysis.error_message or "")


def test_history_is_newest_first(db: Database) -> None:
    with db.session() as s:
        org = repo.default_org_id(s)
        older = _upload(s, org, key="old")
        older.created_at = utcnow() - timedelta(days=1)
        newer = _upload(s, org, key="new")
        assert [a.id for a in repo.list_analyses(s, org)] == [newer.id, older.id]


def test_retention_query_finds_only_old_files_still_stored(db: Database) -> None:
    with db.session() as s:
        org = repo.default_org_id(s)
        old = _upload(s, org, key="old").dataset
        old.created_at = utcnow() - timedelta(days=100)
        gone = _upload(s, org, key="gone").dataset
        gone.created_at = utcnow() - timedelta(days=100)
        gone.raw_deleted_at = utcnow()
        _upload(s, org, key="fresh")
        s.flush()
        found = repo.datasets_with_raw_before(s, utcnow() - timedelta(days=90))
        assert [d.storage_key for d in found] == ["old"]
        assert isinstance(found[0], Dataset)


def test_models_match_the_migrations(db: Database) -> None:
    """Fails if a model changed without a new Alembic revision."""
    from alembic import command

    from finops_app.db import alembic_config

    command.check(alembic_config(db.url))
