# ADR 0001: RQ for background analysis jobs

**Status:** accepted, 2026-11-26 (Phase 2)

## Context

Analyses ran inside the upload request. A 10,000-row file takes about 1.5 s,
but files with 100k+ rows would time out, and a slow request ties up a web
worker. The product plan calls for "upload → job id → page polls status".

## Options

1. **RQ (Redis Queue).** One dependency (Redis), plain functions as jobs,
   a `Worker` in a few lines, job ids we choose. No scheduling, routing or
   result backends beyond Redis.
2. **Celery.** Scheduling (beat), routing, retries, many brokers. More
   configuration, more moving parts, and its features are not needed yet.
3. **A thread pool in the web process only.** No new services, but jobs die
   with the web process and cannot scale past one machine.

## Decision

RQ when `FINOPS_REDIS_URL` is set (production and the Docker stack), with a
thread pool fallback for local development when it is not, and an inline
queue in tests. All three call the same `tasks.process_analysis`, which is
idempotent (it only runs an analysis whose status is `queued`). The thread
fallback re-queues interrupted analyses when the app starts.

## Consequences

- Production needs Redis and at least one `finops-worker` process.
- Retention (`finops-cleanup`) runs from cron, not from the queue. If more
  scheduled work appears (alerts in Phase 5), revisit: `rq-scheduler` first,
  Celery if routing or complex retries become necessary.
- Analysis status lives in the database, not in Redis, so it survives a
  Redis restart. A job lost from Redis stays `queued` in the database;
  a command to re-queue such jobs is a small follow-up.
