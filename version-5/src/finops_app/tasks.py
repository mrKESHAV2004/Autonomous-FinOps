"""The analysis job: read the stored upload, run the engine, store the result.

:func:`process_analysis` does the work for any queue. :func:`run_job` is the
entry point an RQ worker imports; it builds its own database and storage from
the environment, once per worker process.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from finops_app import repository as repo
from finops_app import triage
from finops_app.config import Config
from finops_app.db import Database
from finops_app.storage import LocalStorage, Storage
from finops_core.errors import DataValidationError
from finops_core.models import AnalysisResult
from finops_core.pipeline import analyze

logger = logging.getLogger(__name__)

GENERIC_FAILURE = "Analysis failed due to an internal error. Please check the file and try again."
MISSING_FILE = "The uploaded file is no longer available. Please upload it again."


def process_analysis(db: Database, storage: Storage, org_id: str, analysis_id: str) -> None:
    """Run one queued analysis to completion. Safe to call twice."""
    with db.session() as session:
        analysis = repo.get_analysis(session, org_id, analysis_id)
        if analysis is None or analysis.status != "queued":
            logger.warning(
                "Skipping analysis",
                extra={"analysis": analysis_id, "status": getattr(analysis, "status", None)},
            )
            return
        repo.mark_running(session, analysis)
        storage_key = analysis.dataset.storage_key

    outcome = _run_engine(storage, storage_key, analysis_id)

    with db.session() as session:
        analysis = repo.get_analysis(session, org_id, analysis_id)
        if analysis is None:  # deleted while running
            return
        if isinstance(outcome, AnalysisResult):
            repo.save_result(session, analysis, outcome)
            session.flush()
            carried = triage.carry_over(session, analysis)
            if carried:
                logger.info("Carried over decisions", extra={"analysis": analysis_id, "n": carried})
        else:
            repo.mark_failed(session, analysis, outcome)
    logger.info(
        "Analysis finished", extra={"analysis": analysis_id, "ok": not isinstance(outcome, str)}
    )


def _run_engine(storage: Storage, storage_key: str, analysis_id: str) -> AnalysisResult | str:
    """The engine's result, or a message that is safe to show the user."""
    try:
        return analyze(str(storage.local_path(storage_key)))
    except DataValidationError as exc:
        logger.info("Upload rejected: %s", exc, extra={"analysis": analysis_id})
        return str(exc)
    except FileNotFoundError:
        logger.warning("Raw upload missing", extra={"analysis": analysis_id})
        return MISSING_FILE
    except Exception:
        logger.exception("Analysis failed", extra={"analysis": analysis_id})
        return GENERIC_FAILURE


@lru_cache(maxsize=1)
def _worker_resources() -> tuple[Database, Storage]:
    cfg = Config.from_env()
    return Database(cfg.database_url), LocalStorage(cfg.upload_dir)


def run_job(org_id: str, analysis_id: str) -> None:
    """RQ entry point (``finops_app.tasks.run_job``)."""
    db, storage = _worker_resources()
    process_analysis(db, storage, org_id, analysis_id)
