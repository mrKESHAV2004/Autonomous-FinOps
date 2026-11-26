from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from finops_app.model_quality import compute_quality_scorecard, eval_main
from finops_app.models import Analysis, Dataset, Organization
from finops_app.models import Finding as DbFinding
from finops_core.evaluation import (
    LabelledFinding,
    confusion_metrics,
    evaluate_ranking,
    precision_at_k,
    waste_realization,
)
from finops_core.models import Finding


def make_finding(key: str, waste: float) -> Finding:
    return Finding(
        resource_key=key,
        resource_id=key,
        resource_name=key,
        service="Compute",
        region="us-east-1",
        account="acc-1",
        unit="hours",
        total_cost=waste,
        total_usage=10.0,
        days_active=30,
        estimated_waste=waste,
        estimated_monthly_waste=waste,
        confidence="High",
        signals=("idle",),
        reasons=("Test",),
    )


def test_precision_at_k() -> None:
    items = [
        LabelledFinding(make_finding("f1", 100.0), label=1),
        LabelledFinding(make_finding("f2", 80.0), label=0),
        LabelledFinding(make_finding("f3", 50.0), label=1),
        LabelledFinding(make_finding("f4", 20.0), label=1),
    ]
    # top 1: f1 (label 1) -> 1/1 = 1.0
    assert precision_at_k(items, 1) == 1.0
    # top 2: f1 (1), f2 (0) -> 1/2 = 0.5
    assert precision_at_k(items, 2) == 0.5
    # top 3: f1 (1), f2 (0), f3 (1) -> 2/3 = 0.6667
    assert precision_at_k(items, 3) == pytest.approx(0.6667, rel=1e-3)
    # empty
    assert precision_at_k([], 5) == 0.0


def test_evaluate_ranking_and_confusion() -> None:
    items = [
        LabelledFinding(make_finding("f1", 100.0), label=1),
        LabelledFinding(make_finding("f2", 80.0), label=0),
        LabelledFinding(make_finding("f3", 60.0), label=1),
    ]
    ranking = evaluate_ranking(items, cutoffs=(1, 2, 3))
    assert ranking["precision@1"] == 1.0
    assert ranking["precision@2"] == 0.5
    assert ranking["precision@3"] == pytest.approx(0.6667, rel=1e-3)

    conf = confusion_metrics(items)
    assert conf["total_evaluated"] == 3
    assert conf["true_positives"] == 2
    assert conf["false_positives"] == 1
    assert conf["precision"] == pytest.approx(0.6667, rel=1e-3)
    assert conf["false_positive_rate"] == pytest.approx(0.3333, rel=1e-3)

    real = waste_realization(items)
    assert real["total_flagged_waste"] == 240.0
    assert real["confirmed_real_waste"] == 160.0
    assert real["rejected_false_waste"] == 80.0
    assert real["waste_realization_rate_pct"] == pytest.approx(66.67, rel=1e-2)


def test_compute_quality_scorecard_from_db(tmp_path: Path) -> None:
    from finops_app.db import Database

    db = Database(f"sqlite:///{tmp_path / 'eval_test.db'}")
    from finops_app.db import upgrade

    upgrade(db.url)

    with db.session() as session:
        org = Organization(id="org_eval", name="Eval Org", slug="eval-org")
        session.add(org)
        session.flush()

        dataset = Dataset(
            id="ds_1",
            org_id="org_eval",
            storage_key="key1",
            original_filename="a.csv",
            size_bytes=10,
            row_count=1,
        )
        session.add(dataset)
        session.flush()

        analysis = Analysis(id="an_1", org_id="org_eval", dataset_id="ds_1", status="succeeded")
        session.add(analysis)
        session.flush()

        # Add 1 fixed (positive) and 1 false_positive (negative)
        f1 = DbFinding(
            org_id="org_eval",
            analysis_id="an_1",
            rank=1,
            resource_key="res-1",
            service="Compute",
            total_cost=100.0,
            total_usage=0.0,
            days_active=10,
            est_waste=100.0,
            est_monthly_waste=100.0,
            confidence="High",
            signals=["idle"],
            reasons=["Billed with zero usage"],
            status="fixed",
        )
        f2 = DbFinding(
            org_id="org_eval",
            analysis_id="an_1",
            rank=2,
            resource_key="res-2",
            service="Compute",
            total_cost=50.0,
            total_usage=5.0,
            days_active=10,
            est_waste=50.0,
            est_monthly_waste=50.0,
            confidence="Medium",
            signals=["overpriced"],
            reasons=["Overpriced"],
            status="false_positive",
        )
        session.add_all([f1, f2])
        session.commit()

        scorecard = compute_quality_scorecard(session, "org_eval")
        assert scorecard["org_id"] == "org_eval"
        assert scorecard["confusion"]["total_evaluated"] == 2
        assert scorecard["confusion"]["true_positives"] == 1
        assert scorecard["confusion"]["false_positives"] == 1
        assert scorecard["confusion"]["precision"] == 0.5


def test_model_quality_api(client: FlaskClient) -> None:
    res = client.get("/api/v1/model-quality/precision")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "ranking_precision" in data["data"]
    assert "confusion" in data["data"]
    assert "financial_impact" in data["data"]


def test_eval_cli(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from finops_app.config import Config
    from finops_app.db import Database, upgrade

    db_path = tmp_path / "cli_eval.db"
    db_url = f"sqlite:///{db_path}"
    upgrade(db_url)
    db = Database(db_url)
    with db.session() as session:
        org = Organization(id="org_cli", name="Cli Org", slug="cli-org")
        session.add(org)

    monkeypatch.setattr(Config, "from_env", lambda: Config(database_url=db_url))

    ret = eval_main(["--org-id", "org_cli", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["org_id"] == "org_cli"
    assert "ranking_precision" in data
