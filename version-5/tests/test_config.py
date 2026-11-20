from __future__ import annotations

from pathlib import Path

import pytest

from finops_app.config import Config, ConfigError


def test_defaults_are_safe_for_local_development() -> None:
    cfg = Config.from_env({})

    assert cfg.env == "development"
    assert cfg.host == "127.0.0.1"
    assert cfg.debug is False
    assert cfg.max_upload_mb == 50
    assert cfg.max_content_length == 50 * 1024 * 1024
    assert len(cfg.secret_key) == 64


def test_random_secret_differs_between_instances() -> None:
    assert Config.from_env({}).secret_key != Config.from_env({}).secret_key


def test_reads_all_variables() -> None:
    cfg = Config.from_env(
        {
            "FINOPS_ENV": "Testing",
            "FINOPS_SECRET_KEY": "abc",
            "FINOPS_MAX_UPLOAD_MB": "5",
            "FINOPS_UPLOAD_DIR": "/tmp/u",
            "FINOPS_ARTIFACT_DIR": "/tmp/a",
            "FINOPS_HOST": "0.0.0.0",  # noqa: S104 - value under test, not a bind
            "FINOPS_PORT": "8080",
            "FINOPS_DEBUG": "1",
            "FINOPS_LOG_LEVEL": "debug",
        }
    )

    assert cfg.testing
    assert cfg.secret_key == "abc"
    assert cfg.max_upload_mb == 5
    assert cfg.upload_dir == Path("/tmp/u")
    assert cfg.artifact_dir == Path("/tmp/a")
    assert cfg.port == 8080
    assert cfg.debug is True
    assert cfg.log_level == "DEBUG"
    assert cfg.log_json is False


def test_production_requires_secret_key() -> None:
    with pytest.raises(ConfigError, match="FINOPS_SECRET_KEY"):
        Config.from_env({"FINOPS_ENV": "production"})


def test_production_rejects_debug() -> None:
    with pytest.raises(ConfigError, match="FINOPS_DEBUG"):
        Config.from_env(
            {"FINOPS_ENV": "production", "FINOPS_SECRET_KEY": "x", "FINOPS_DEBUG": "true"}
        )


def test_production_defaults_to_json_logs() -> None:
    cfg = Config.from_env({"FINOPS_ENV": "production", "FINOPS_SECRET_KEY": "x"})
    assert cfg.log_json is True


def test_unknown_env_is_rejected() -> None:
    with pytest.raises(ConfigError, match="FINOPS_ENV"):
        Config.from_env({"FINOPS_ENV": "staging"})


@pytest.mark.parametrize("value", ["abc", "0", "-3"])
def test_invalid_upload_limit_is_rejected(value: str) -> None:
    with pytest.raises(ConfigError, match="FINOPS_MAX_UPLOAD_MB"):
        Config.from_env({"FINOPS_MAX_UPLOAD_MB": value})


def test_secret_key_not_in_repr() -> None:
    assert "supersecret" not in repr(Config(secret_key="supersecret"))


def test_config_is_immutable() -> None:
    cfg = Config()
    with pytest.raises(AttributeError):
        cfg.port = 1  # type: ignore[misc]
