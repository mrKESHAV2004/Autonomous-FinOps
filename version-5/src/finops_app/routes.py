"""HTTP routes: landing, upload, analysis status and results, history, sample CSV.

Everything but the landing page and the sample CSV needs sign-in; data is
always read for :func:`~finops_app.auth.current_org_id`.
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from finops_app import analysis as dashboard
from finops_app import finding_queries as fq
from finops_app import repository as repo
from finops_app import serializers as ser
from finops_app import triage
from finops_app.accounts import can
from finops_app.auth import current_org_id, current_role, role_required
from finops_app.config import Config
from finops_app.db import get_session
from finops_app.jobs import JobQueue
from finops_app.models import Analysis, ShareLink
from finops_app.sample_data import sample_csv
from finops_app.security import STATUS_LIMIT, UPLOAD_LIMIT, limiter
from finops_app.storage import Storage, make_key
from finops_app.uploads import UploadRejected, check_contents, check_filename

logger = logging.getLogger(__name__)

bp = Blueprint("web", __name__)

INCOMING_DIR = ".incoming"
OVERVIEW_TOP = 5


def _config() -> Config:
    cfg: Config = current_app.extensions["finops_config"]
    return cfg


def _storage() -> Storage:
    storage: Storage = current_app.extensions["finops_storage"]
    return storage


def _queue() -> JobQueue:
    queue: JobQueue = current_app.extensions["finops_queue"]
    return queue


@bp.get("/")
def home() -> str:
    return render_template("finOps.html")


@bp.route("/upload", methods=["GET", "POST"])
@role_required("analyst")
@limiter.limit(UPLOAD_LIMIT, methods=["POST"])
def index() -> str | Response:
    if request.method == "GET":
        return render_template("index.html")

    file = request.files.get("file")
    if file is None:
        flash("No file selected", "danger")
        return redirect(request.url)  # type: ignore[return-value]
    try:
        analysis_id = _accept_upload(file)
    except UploadRejected as exc:
        flash(str(exc), "warning")
        return redirect(request.url)  # type: ignore[return-value]
    return redirect(url_for("web.show_analysis", analysis_id=analysis_id))  # type: ignore[return-value]


def _accept_upload(file: FileStorage) -> str:
    """Check, store and queue one upload; returns the new analysis id."""
    filename = check_filename(file.filename)
    incoming = Path(_config().upload_dir) / INCOMING_DIR
    incoming.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=incoming, suffix=".csv", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        file.save(tmp_path)
        check = check_contents(tmp_path, _config().max_rows)
        session = get_session()
        org_id = current_org_id()
        key = make_key(org_id)
        _storage().put_file(key, tmp_path)
        analysis = repo.create_upload(
            session,
            org_id,
            original_filename=secure_filename(filename) or "upload.csv",
            storage_key=key,
            size_bytes=check.size_bytes,
            row_count=check.row_count,
            uploaded_by=current_user.id,
        )
        session.commit()
    finally:
        tmp_path.unlink(missing_ok=True)
    _queue().enqueue(org_id, analysis.id)
    logger.info("Upload queued", extra={"analysis": analysis.id, "rows": check.row_count})
    return analysis.id


def _analysis_or_404(analysis_id: str) -> Analysis:
    found = repo.get_analysis(get_session(), current_org_id(), analysis_id)
    if found is None:
        abort(404)
    return found


@bp.get("/analyses/<analysis_id>")
@role_required("viewer")
def show_analysis(analysis_id: str) -> str:
    found = _analysis_or_404(analysis_id)
    if found.status != "succeeded":
        return render_template("analysis_status.html", analysis=found)
    session = get_session()
    if triage.wake_expired_snoozes(session, found.org_id, found.id):
        session.commit()
    results = dashboard.build_dashboard(repo.load_result(found), found.finished_at)
    top = fq.list_page(
        session, found.org_id, found.id, fq.FindingQuery(status="active", per_page=OVERVIEW_TOP)
    )
    return render_template(
        "dashboard.html",
        results=results,
        analysis=found,
        summary=fq.status_summary(session, found.org_id, found.id),
        top=[ser.finding_dict(f) for f in top.items],
        series=ser.series_dict(found),
        active_total=top.total,
        status_labels=triage.STATUS_LABELS,
        share_links=_share_links(session, found),
    )


def _share_links(session: Session, found: Analysis) -> list[ShareLink] | None:
    """Live share links, for admins (who can manage them) only."""
    from finops_app.sharing import live_links  # sharing imports this module

    return live_links(session, found.org_id, found.id) if can(current_role(), "admin") else None


@bp.get("/analyses/<analysis_id>/status")
@role_required("viewer")
@limiter.limit(STATUS_LIMIT)
def analysis_status(analysis_id: str) -> Response:
    found = _analysis_or_404(analysis_id)
    return jsonify(
        id=found.id,
        status=found.status,
        error=found.error_message if found.status == "failed" else None,
        url=url_for("web.show_analysis", analysis_id=found.id),
    )


@bp.get("/analyses")
@role_required("viewer")
def history() -> str:
    analyses = repo.list_analyses(get_session(), current_org_id())
    return render_template("history.html", analyses=analyses)


@bp.post("/sample")
@role_required("analyst")
@limiter.limit(UPLOAD_LIMIT)
def analyse_sample() -> Response:
    """First-run shortcut: analyse the sample file without downloading it."""
    sample = FileStorage(io.BytesIO(sample_csv().encode()), filename="sample-billing.csv")
    analysis_id = _accept_upload(sample)
    return redirect(url_for("web.show_analysis", analysis_id=analysis_id))  # type: ignore[return-value]


@bp.get("/sample")
def sample_data() -> Response:
    return Response(
        sample_csv(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_finops_data.csv"},
    )
