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
        )


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
