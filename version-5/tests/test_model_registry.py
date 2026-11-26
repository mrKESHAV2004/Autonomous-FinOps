from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from finops_app.db import Database, upgrade
from finops_app.model_registry import (
    RegistryError,
    get_active_version,
    models_cli_main,
    promote_version,
    register_version,
    rollback_version,
)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    db_path = tmp_path / "registry_test.db"
    db_url = f"sqlite:///{db_path}"
    upgrade(db_url)
    db = Database(db_url)
    sess = db.new_session()
    try:
        yield sess
    finally:
        sess.close()
        db.dispose()


def test_register_and_promote(session: Session) -> None:
    m1 = register_version(
        session,
        "detector",
        "v1.0.0",
        "IsolationForest",
        metrics={"precision": 0.85},
        deploy_now=True,
    )
    session.commit()
    assert m1.is_active is True
    assert m1.deployed_at is not None

    # Register v1.1.0 without deploy
    m2 = register_version(
        session,
        "detector",
        "v1.1.0",
        "IsolationForest+Rules",
        metrics={"precision": 0.92},
        deploy_now=False,
    )
    session.commit()
    assert m2.is_active is False
    assert get_active_version(session, "detector").version == "v1.0.0"

    # Promote v1.1.0
    promoted = promote_version(session, "detector", "v1.1.0")
    session.commit()
    assert promoted.version == "v1.1.0"
    assert promoted.is_active is True
    assert get_active_version(session, "detector").version == "v1.1.0"


def test_duplicate_version_rejected(session: Session) -> None:
    register_version(session, "forecaster", "v1.0.0", "MovingAverage")
    session.commit()
    with pytest.raises(RegistryError, match="already exists"):
        register_version(session, "forecaster", "v1.0.0", "MovingAverage")


def test_rollback_version(session: Session) -> None:
    register_version(session, "detector", "v1.0.0", "Baseline", deploy_now=True)
    session.commit()
    register_version(session, "detector", "v1.1.0", "Experimental", deploy_now=True)
    session.commit()

    assert get_active_version(session, "detector").version == "v1.1.0"

    # Rollback to v1.0.0
    rolled = rollback_version(session, "detector")
    session.commit()
    assert rolled.version == "v1.0.0"
    assert rolled.is_active is True
    assert get_active_version(session, "detector").version == "v1.0.0"


def test_rollback_without_previous_raises(session: Session) -> None:
    register_version(session, "detector", "v1.0.0", "Baseline", deploy_now=True)
    session.commit()
    with pytest.raises(RegistryError, match="No previous version available"):
        rollback_version(session, "detector")


def test_models_cli(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from finops_app.config import Config

    db_path = tmp_path / "cli_registry.db"
    db_url = f"sqlite:///{db_path}"
    upgrade(db_url)
    monkeypatch.setattr(Config, "from_env", lambda: Config(database_url=db_url))

    # Register
    ret = models_cli_main(
        [
            "register",
            "--name",
            "detector",
            "--version",
            "v1.0.0",
            "--algorithm",
            "IsoForest",
            "--promote",
        ]
    )
    assert ret == 0
    capsys.readouterr()

    # List JSON
    ret = models_cli_main(["list", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data) == 1
    assert data[0]["version"] == "v1.0.0"
    assert data[0]["is_active"] is True


def test_models_api(client: FlaskClient) -> None:
    # List models via API
    res = client.get("/api/v1/models")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert isinstance(data["data"], list)
