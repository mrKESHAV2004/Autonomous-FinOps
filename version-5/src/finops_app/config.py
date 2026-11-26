"""Application configuration loaded from environment variables.

| Variable                 | Default                | Notes                                         |
|--------------------------|------------------------|-----------------------------------------------|
| ``FINOPS_ENV``           | ``development``        | ``development`` / ``production`` / ``testing`` |
| ``FINOPS_SECRET_KEY``    | random (non-prod)      | **required** in production                    |
| ``FINOPS_MAX_UPLOAD_MB`` | ``50``                 | max request body size                         |
| ``FINOPS_UPLOAD_DIR``    | ``./uploads``          | where uploaded CSVs are written               |
| ``FINOPS_ARTIFACT_DIR``  | ``./finops_artifacts`` | trained model output                          |
| ``FINOPS_HOST``          | ``127.0.0.1``          | dev server bind address                       |
| ``FINOPS_PORT``          | ``5000``               | dev server port                               |
| ``FINOPS_DEBUG``         | ``0``                  | ``1`` enables Flask debug (refused in prod)   |
| ``FINOPS_LOG_LEVEL``     | ``INFO``               |                                               |
| ``FINOPS_LOG_JSON``      | ``1`` in prod          | structured JSON logs                          |
| ``FINOPS_DATABASE_URL``  | ``sqlite:///finops.db``| SQLAlchemy URL; PostgreSQL in production      |
| ``FINOPS_REDIS_URL``     | unset                  | set to run jobs on an RQ worker; unset runs   |
|                          |                        | them on a background thread in the web app    |
| ``FINOPS_MAX_ROWS``      | ``2000000``            | uploads with more data rows are rejected      |
| ``FINOPS_RETENTION_DAYS``| ``90``                 | raw uploads older than this are deleted       |
| ``FINOPS_AUTO_MIGRATE``  | ``1`` outside prod     | apply database migrations when the app starts |
| ``FINOPS_SESSION_HOURS`` | ``8``                  | sign-in ends after this long without activity |
| ``FINOPS_RATE_LIMITS``   | ``1``                  | ``0`` turns rate limiting off (tests only)    |
| ``FINOPS_TRUSTED_PROXIES``| ``0``                 | proxies in front of the app (X-Forwarded-For) |
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

VALID_ENVS = ("development", "production", "testing")
DEFAULT_MAX_UPLOAD_MB = 50
DEFAULT_PORT = 5000
DEFAULT_DATABASE_URL = "sqlite:///finops.db"
DEFAULT_MAX_ROWS = 2_000_000
DEFAULT_RETENTION_DAYS = 90
DEFAULT_SESSION_HOURS = 8


class ConfigError(RuntimeError):
    """Configuration is missing or invalid; the app must not start."""


@dataclass(frozen=True)
class Config:
    env: str = "development"
    secret_key: str = field(default_factory=lambda: secrets.token_hex(32), repr=False)
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB
    upload_dir: Path = Path("uploads")
    artifact_dir: Path = Path("finops_artifacts")
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = False
    database_url: str = field(default=DEFAULT_DATABASE_URL, repr=False)
    redis_url: str | None = field(default=None, repr=False)
    max_rows: int = DEFAULT_MAX_ROWS
    retention_days: int = DEFAULT_RETENTION_DAYS
    auto_migrate: bool = True
    session_hours: int = DEFAULT_SESSION_HOURS
    rate_limits: bool = True
    csrf: bool = True
    trusted_proxies: int = 0

    @property
    def testing(self) -> bool:
        return self.env == "testing"

    @property
    def max_content_length(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Config:
        """Build config from environment variables, failing fast on bad values."""
        env_vars = os.environ if environ is None else environ
        env = env_vars.get("FINOPS_ENV", "development").strip().lower()
        if env not in VALID_ENVS:
            raise ConfigError(f"FINOPS_ENV must be one of {VALID_ENVS}, got {env!r}")

        is_prod = env == "production"
        secret_key = env_vars.get("FINOPS_SECRET_KEY", "").strip()
        if is_prod and not secret_key:
            raise ConfigError("FINOPS_SECRET_KEY must be set when FINOPS_ENV=production")

        debug = _bool(env_vars.get("FINOPS_DEBUG"), default=False)
        if is_prod and debug:
            raise ConfigError("FINOPS_DEBUG must not be enabled in production")

        return cls(
            env=env,
            secret_key=secret_key or secrets.token_hex(32),
            max_upload_mb=_positive_int(env_vars, "FINOPS_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB),
            upload_dir=Path(env_vars.get("FINOPS_UPLOAD_DIR", "uploads")),
            artifact_dir=Path(env_vars.get("FINOPS_ARTIFACT_DIR", "finops_artifacts")),
            host=env_vars.get("FINOPS_HOST", "127.0.0.1"),
            port=_positive_int(env_vars, "FINOPS_PORT", DEFAULT_PORT),
            debug=debug,
            log_level=env_vars.get("FINOPS_LOG_LEVEL", "INFO").upper(),
            log_json=_bool(env_vars.get("FINOPS_LOG_JSON"), default=is_prod),
            database_url=env_vars.get("FINOPS_DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL,
            redis_url=env_vars.get("FINOPS_REDIS_URL", "").strip() or None,
            max_rows=_positive_int(env_vars, "FINOPS_MAX_ROWS", DEFAULT_MAX_ROWS),
            retention_days=_positive_int(env_vars, "FINOPS_RETENTION_DAYS", DEFAULT_RETENTION_DAYS),
            auto_migrate=_bool(env_vars.get("FINOPS_AUTO_MIGRATE"), default=not is_prod),
            session_hours=_positive_int(env_vars, "FINOPS_SESSION_HOURS", DEFAULT_SESSION_HOURS),
            rate_limits=_rate_limits(env_vars, is_prod),
            trusted_proxies=_non_negative_int(env_vars, "FINOPS_TRUSTED_PROXIES"),
        )


def _rate_limits(env_vars: Mapping[str, str], is_prod: bool) -> bool:
    enabled = _bool(env_vars.get("FINOPS_RATE_LIMITS"), default=True)
    if is_prod and not enabled:
        raise ConfigError("FINOPS_RATE_LIMITS must not be turned off in production")
    return enabled


def _non_negative_int(env_vars: Mapping[str, str], name: str) -> int:
    raw = env_vars.get(name, "").strip()
    if not raw:
        return 0
    if not raw.isdigit():
        raise ConfigError(f"{name} must be a whole number, got {raw!r}")
    return int(raw)


def _bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _positive_int(env_vars: Mapping[str, str], name: str, default: int) -> int:
    raw = env_vars.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive, got {value}")
    return value
