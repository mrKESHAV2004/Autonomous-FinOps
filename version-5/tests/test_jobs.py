from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import fakeredis
import pytest
from sqlalchemy import select

from finops_app import cli, jobs, tasks
from finops_app import repository as repo
from finops_app.db import Database, upgrade
from finops_app.models import Analysis, AuditLog, utcnow
from finops_app.storage import LocalStorage, make_key


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    upgrade(url)
    database = Database(url)
    yield database
    database.dispose()


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "store")


def queued(db: Database, storage: LocalStorage, source: Path) -> tuple[str, str]:
    """Store ``source`` and create a queued analysis; returns (org_id, analysis_id)."""
    with db.session() as s:
        org = repo.default_org_id(s)
        key = make_key(org)
        copy = source.with_suffix(".copy")
        shutil.copy(source, copy)
        storage.put_file(key, copy)
        analysis = repo.create_upload(
            s, org, original_filename="bill.csv", storage_key=key, size_bytes=1, row_count=1
        )
        return org, analysis.id


def status_of(db: Database, org: str, aid: str) -> Analysis:
    with db.session() as s:
        found = repo.get_analysis(s, org, aid)
        assert found is not None
        return found


def test_process_analysis_stores_the_result(
    db: Database, storage: LocalStorage, make_billing_csv: Callable[..., Path]
) -> None:
    org, aid = queued(db, storage, make_billing_csv(days=10))
    tasks.process_analysis(db, storage, org, aid)

    done = status_of(db, org, aid)
    assert done.status == "succeeded"
    assert done.total_spend and done.total_spend > 0
    assert done.forecast_method


def test_bad_data_marks_the_analysis_failed(
    db: Database, storage: LocalStorage, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("Date,Cost\n2024-01-01,5\n")
    org, aid = queued(db, storage, bad)
    tasks.process_analysis(db, storage, org, aid)

    failed = status_of(db, org, aid)
    assert failed.status == "failed"
    assert "Missing required column" in (failed.error_message or "")


def test_missing_raw_file_fails_with_a_clear_message(
    db: Database, storage: LocalStorage, make_billing_csv: Callable[..., Path]
) -> None:
    org, aid = queued(db, storage, make_billing_csv(days=5))
    with db.session() as s:
        found = repo.get_analysis(s, org, aid)
        assert found is not None
        storage.delete(found.dataset.storage_key)
    tasks.process_analysis(db, storage, org, aid)
    assert status_of(db, org, aid).error_message == tasks.MISSING_FILE


def test_unexpected_errors_are_generic(
    db: Database,
    storage: LocalStorage,
    make_billing_csv: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "analyze", lambda _p: 1 / 0)
    org, aid = queued(db, storage, make_billing_csv(days=5))
    tasks.process_analysis(db, storage, org, aid)
    assert status_of(db, org, aid).error_message == tasks.GENERIC_FAILURE


def test_a_finished_job_is_not_run_twice(
    db: Database,
    storage: LocalStorage,
    make_billing_csv: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, aid = queued(db, storage, make_billing_csv(days=5))
    tasks.process_analysis(db, storage, org, aid)
    monkeypatch.setattr(tasks, "analyze", lambda _p: pytest.fail("ran twice"))
    tasks.process_analysis(db, storage, org, aid)
    assert status_of(db, org, aid).status == "succeeded"


def test_wrong_org_cannot_run_a_job(
    db: Database, storage: LocalStorage, make_billing_csv: Callable[..., Path]
) -> None:
    _org, aid = queued(db, storage, make_billing_csv(days=5))
    tasks.process_analysis(db, storage, "someone-else", aid)
    assert status_of(db, _org, aid).status == "queued"


def test_thread_queue_runs_jobs_in_the_background(
    db: Database, storage: LocalStorage, make_billing_csv: Callable[..., Path]
) -> None:
    org, aid = queued(db, storage, make_billing_csv(days=5))
    queue = jobs.ThreadQueue(db, storage)
    queue.enqueue(org, aid)
    queue.shutdown()
    assert status_of(db, org, aid).status == "succeeded"


def test_restart_requeues_interrupted_jobs(
    db: Database, storage: LocalStorage, make_billing_csv: Callable[..., Path]
) -> None:
    org, aid = queued(db, storage, make_billing_csv(days=5))
    with db.session() as s:
        found = repo.get_analysis(s, org, aid)
        assert found is not None
        repo.mark_running(s, found)  # the process died mid-job

    seen: list[tuple[str, str]] = []

    class Recorder:
        def enqueue(self, org_id: str, analysis_id: str) -> None:
            seen.append((org_id, analysis_id))

    assert jobs.requeue_interrupted(db, Recorder()) == 1
    assert seen == [(org, aid)]
    assert status_of(db, org, aid).status == "queued"


def test_rq_queue_enqueues_the_task_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    server = fakeredis.FakeServer()
    monkeypatch.setattr("redis.Redis.from_url", lambda _url: fakeredis.FakeRedis(server=server))
    queue = jobs.RQQueue("redis://example.invalid:6379/0")
    queue.enqueue("org1", "abc")

    from rq import Queue

    rq_queue = Queue(jobs.QUEUE_NAME, connection=fakeredis.FakeRedis(server=server))
    (job,) = rq_queue.jobs
    assert job.func_name == "finops_app.tasks.run_job"
    assert job.args == ("org1", "abc")
    assert job.id == "analysis-abc"


def test_run_job_builds_resources_from_the_environment(
    tmp_path: Path, make_billing_csv: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'worker.db'}"
    upgrade(url)
    monkeypatch.setenv("FINOPS_DATABASE_URL", url)
    monkeypatch.setenv("FINOPS_UPLOAD_DIR", str(tmp_path / "store"))
    tasks._worker_resources.cache_clear()
    db, storage = tasks._worker_resources()
    assert isinstance(storage, LocalStorage)
    org, aid = queued(db, storage, make_billing_csv(days=5))

    tasks.run_job(org, aid)

    assert status_of(db, org, aid).status == "succeeded"
    tasks._worker_resources.cache_clear()


def test_cleanup_deletes_old_raw_files_and_keeps_results(
    db: Database, storage: LocalStorage, make_billing_csv: Callable[..., Path]
) -> None:
    org, old = queued(db, storage, make_billing_csv(days=5))
    _org, fresh = queued(db, storage, make_billing_csv(days=5))
    tasks.process_analysis(db, storage, org, old)
    with db.session() as s:
        found = repo.get_analysis(s, org, old)
        assert found is not None
        found.dataset.created_at = utcnow() - timedelta(days=91)
        old_key = found.dataset.storage_key

    assert cli.delete_expired_uploads(db, storage, retention_days=90) == 1
    assert not storage.exists(old_key)
    kept = status_of(db, org, old)
    assert kept.status == "succeeded"
    with db.session() as s:
        assert s.scalars(
            select(AuditLog.action).where(AuditLog.target_type == "dataset")
        ).all() == ["dataset.raw_deleted"]
    assert cli.delete_expired_uploads(db, storage, retention_days=90) == 0
    assert fresh


def test_cleanup_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("FINOPS_DATABASE_URL", url)
    monkeypatch.setenv("FINOPS_UPLOAD_DIR", str(tmp_path / "store"))
    assert cli.db_main(["upgrade"]) == 0
    assert cli.cleanup_main(["--days", "30"]) == 0
    assert "Deleted 0 raw upload(s) older than 30 days." in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.cleanup_main(["--days", "0"])


def test_worker_refuses_to_start_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINOPS_REDIS_URL", raising=False)
    assert cli.worker_main([]) == 2
