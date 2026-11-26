"""Flask web application (app factory)."""

from __future__ import annotations

import logging

from flask import Flask, flash, jsonify, redirect, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.wrappers import Response

from finops_app.config import Config
from finops_app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> Flask:
    """Build and configure the Flask app. Reads env vars when ``config`` is None."""
    cfg = config or Config.from_env()
    configure_logging(cfg.log_level, json_logs=cfg.log_json)

    if cfg.sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration

            sentry_sdk.init(
                dsn=cfg.sentry_dsn,
                environment=cfg.env,
                integrations=[FlaskIntegration()],
                traces_sample_rate=0.1 if cfg.env == "production" else 1.0,
            )
            logger.info("Sentry initialized")
        except ImportError:
            logger.warning("FINOPS_SENTRY_DSN set but sentry_sdk is not installed")

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=cfg.secret_key,
        MAX_CONTENT_LENGTH=cfg.max_content_length,
        UPLOAD_FOLDER=str(cfg.upload_dir),
        ARTIFACT_DIR=str(cfg.artifact_dir),
        TESTING=cfg.testing,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cfg.env == "production",
    )
    app.extensions["finops_config"] = cfg
    app.jinja_env.filters["zip"] = lambda first, *rest: zip(first, *rest, strict=False)

    cfg.upload_dir.mkdir(parents=True, exist_ok=True)
    cfg.artifact_dir.mkdir(parents=True, exist_ok=True)

    _init_services(app, cfg)

    from finops_app import (  # noqa: F401
        alerts_views,
        api,
        auth,
        budgets_views,
        connectors_views,
        findings_views,
        health,
        members,
        security,
        sharing,
    )
    from finops_app.routes import bp

    security.init_app(app, cfg)
    auth.init_app(app, cfg)
    app.register_blueprint(bp)
    app.register_blueprint(health.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(members.bp)
    app.register_blueprint(connectors_views.bp)
    app.register_blueprint(budgets_views.bp)
    app.register_blueprint(alerts_views.bp)
    _register_error_handlers(app, cfg)
    logger.info("App created", extra={"env": cfg.env, "max_upload_mb": cfg.max_upload_mb})
    return app


def _init_services(app: Flask, cfg: Config) -> None:
    """Database, raw-file storage and the job queue, kept on ``app.extensions``."""
    from finops_app import db as dbmod
    from finops_app import jobs
    from finops_app.storage import build_storage

    if cfg.auto_migrate:
        dbmod.upgrade(cfg.database_url)
    database = dbmod.Database(cfg.database_url)
    dbmod.init_app(app, database)
    storage = build_storage(cfg)
    queue: jobs.JobQueue
    if cfg.redis_url:
        queue = jobs.RQQueue(cfg.redis_url)
    elif cfg.testing:
        queue = jobs.InlineQueue(database, storage)
    else:
        queue = jobs.ThreadQueue(database, storage)
        jobs.requeue_interrupted(database, queue)
    app.extensions["finops_storage"] = storage
    app.extensions["finops_queue"] = queue


ERROR_MESSAGES = {
    400: ("Something in that request wasn't right", "Go back and try again."),
    403: (
        "You don't have access to this",
        "Ask an owner or admin of your organisation for access.",
    ),
    404: ("Not found", "This page doesn't exist, or it belongs to another organisation."),
    405: ("Not allowed", "That action isn't available here."),
    409: ("Not ready", "This analysis hasn't finished yet."),
    429: ("Too many requests", "Please wait a minute, then try again."),
}


def _register_error_handlers(app: Flask, cfg: Config) -> None:
    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc: RequestEntityTooLarge) -> Response:
        flash(f"File is too large. The limit is {cfg.max_upload_mb} MB.", "danger")
        return redirect(request.url)

    @app.errorhandler(CSRFError)
    def csrf_failed(_exc: CSRFError) -> tuple[str | Response, int]:
        return _error_page(400, "This form has expired", "Reload the page and try again.")

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException) -> tuple[str | Response, int] | HTTPException:
        code = exc.code or 500
        if code not in ERROR_MESSAGES:
            return exc
        return _error_page(code, *ERROR_MESSAGES[code])


def _error_page(code: int, title: str, detail: str) -> tuple[str | Response, int]:
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "data": None, "error": title}), code
    return render_template("error.html", code=code, title=title, detail=detail), code
