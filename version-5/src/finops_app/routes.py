"""HTTP routes: landing page, upload + dashboard, sample CSV download."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
)
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from finops_app import analysis
from finops_core.errors import DataValidationError

logger = logging.getLogger(__name__)

bp = Blueprint("web", __name__)

ALLOWED_EXTENSIONS = (".csv",)
GENERIC_FAILURE = "Analysis failed due to an internal error. Please check the file and try again."
SAMPLE_CSV = """UsageDate,ServiceCategory,EffectiveCost,ConsumedQuantity
2024-01-01,Compute,125.50,100
2024-01-01,Storage,45.25,50
2024-01-02,Compute,130.75,105
2024-01-02,Storage,46.80,52
2024-01-03,Compute,28.00,5
2024-01-03,Storage,48.10,55
2024-01-04,Database,85.30,20
2024-01-04,Network,12.40,15"""


@bp.get("/")
def home() -> str:
    return render_template("finOps.html")


@bp.route("/upload", methods=["GET", "POST"])
def index() -> str | Response:
    if request.method == "GET":
        return render_template("index.html")

    file = request.files.get("file")
    error = _validate_upload(file)
    if error or file is None:
        flash(error or "No file selected", "danger")
        return redirect(request.url)  # type: ignore[return-value]

    filepath = _save_upload(file)
    try:
        results = analysis.run_analysis(str(filepath))
    except DataValidationError as exc:
        logger.info("Upload rejected: %s", exc, extra={"upload": filepath.name})
        flash(str(exc), "warning")
        return redirect(request.url)  # type: ignore[return-value]
    except Exception:
        logger.exception("Analysis failed", extra={"upload": filepath.name})
        flash(GENERIC_FAILURE, "danger")
        return redirect(request.url)  # type: ignore[return-value]

    return render_template("dashboard.html", results=results)


@bp.get("/sample")
def sample_data() -> Response:
    return Response(
        SAMPLE_CSV,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_finops_data.csv"},
    )


def _validate_upload(file: FileStorage | None) -> str | None:
    """Return a user-facing error message, or ``None`` if the upload looks valid."""
    if file is None:
        return "No file selected"
    if not file.filename:
        return "Please select a file"
    if not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        return "Only CSV files are supported"
    return None


def _save_upload(file: FileStorage) -> Path:
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = upload_dir / f"{timestamp}_{secure_filename(file.filename or 'upload.csv')}"
    file.save(filepath)
    return filepath
