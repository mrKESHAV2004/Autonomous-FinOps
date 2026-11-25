"""Where analysis jobs run.

* ``FINOPS_REDIS_URL`` set: :class:`RQQueue`; a separate ``finops-worker``
  process runs the jobs and they survive web restarts.
* Unset (local development): :class:`ThreadQueue`, a small thread pool in the
  web process. Jobs interrupted by a restart are re-queued at start-up.
* Tests: :class:`InlineQueue` runs the job before ``enqueue`` returns.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

from sqlalchemy import select

from finops_app.db import Database
from finops_app.models import Analysis
from finops_app.storage import Storage
from finops_app.tasks import process_analysis

logger = logging.getLogger(__name__)

QUEUE_NAME = "analyses"
JOB_TIMEOUT_SECONDS = 30 * 60
THREAD_WORKERS = 2


class JobQueue(Protocol):
    def enqueue(self, org_id: str, analysis_id: str) -> None: ...


class InlineQueue:
    def __init__(self, db: Database, storage: Storage) -> None:
        self.db, self.storage = db, storage

    def enqueue(self, org_id: str, analysis_id: str) -> None:
        process_analysis(self.db, self.storage, org_id, analysis_id)


class ThreadQueue:
    def __init__(self, db: Database, storage: Storage, workers: int = THREAD_WORKERS) -> None:
        self.db, self.storage = db, storage
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="finops-job")

    def enqueue(self, org_id: str, analysis_id: str) -> None:
        future = self._pool.submit(process_analysis, self.db, self.storage, org_id, analysis_id)
        future.add_done_callback(_log_crash)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)


def _log_crash(future: Future[None]) -> None:
    exc = future.exception()
    if exc is not None:
        logger.error("Analysis job crashed", exc_info=exc)


class RQQueue:
    def __init__(self, redis_url: str) -> None:
        from redis import Redis
        from rq import Queue

        self._queue = Queue(QUEUE_NAME, connection=Redis.from_url(redis_url))

    def enqueue(self, org_id: str, analysis_id: str) -> None:
        self._queue.enqueue(
            "finops_app.tasks.run_job",
            org_id,
            analysis_id,
            job_timeout=JOB_TIMEOUT_SECONDS,
            job_id=f"analysis-{analysis_id}",
        )


def requeue_interrupted(db: Database, queue: JobQueue) -> int:
    """Re-queue analyses a restart left queued or running (in-process queues only).

    Runs across all orgs at start-up: it only reads ids and resets status.
    """
    with db.session() as session:
        stuck = list(
            session.scalars(select(Analysis).where(Analysis.status.in_(("queued", "running"))))
        )
        pending = [(a.org_id, a.id) for a in stuck]
        for analysis in stuck:
            analysis.status = "queued"
    for org_id, analysis_id in pending:
        queue.enqueue(org_id, analysis_id)
    if pending:
        logger.info("Re-queued interrupted analyses", extra={"count": len(pending)})
    return len(pending)
