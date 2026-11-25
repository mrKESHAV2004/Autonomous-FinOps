"""Flask web application (app factory)."""

from __future__ import annotations

import logging

from flask import Flask, flash, redirect, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response

from finops_app.config import Config
from finops_app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> Flask:
    """Build and configure the Flask app. Reads env vars when ``config`` is None."""
    cfg = config or Config.from_env()
    configure_logging(cfg.log_level, json_logs=cfg.log_json)

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

    cfg.upload_dir.mkdir(parents=True, exist_ok=True)
    cfg.artifact_dir.mkdir(parents=True, exist_ok=True)

    _init_services(app, cfg)

    from finops_app.routes import bp

    app.register_blueprint(bp)
    _register_error_handlers(app, cfg)
    logger.info("App created", extra={"env": cfg.env, "max_upload_mb": cfg.max_upload_mb})
    return app


def _init_services(app: Flask, cfg: Config) -> None:
    """Database, raw-file storage and the job queue, kept on ``app.extensions``."""
    from finops_app import db as dbmod
    from finops_app import jobs
    from finops_app.storage import LocalStorage

    if cfg.auto_migrate:
        dbmod.upgrade(cfg.database_url)
    database = dbmod.Database(cfg.database_url)
    dbmod.init_app(app, database)
    storage = LocalStorage(cfg.upload_dir)
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


def _register_error_handlers(app: Flask, cfg: Config) -> None:
    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_exc: RequestEntityTooLarge) -> Response:
        flash(f"File is too large. The limit is {cfg.max_upload_mb} MB.", "danger")
        return redirect(request.url)
