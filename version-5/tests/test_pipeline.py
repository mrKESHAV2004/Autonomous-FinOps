from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from conftest import billing_frame
from finops_core.errors import DataValidationError
from finops_core.pipeline import analyze, main, to_dict
from finops_core.schema import normalize_columns


def test_analyze_is_deterministic(make_billing_csv: Callable[..., Path]) -> None:
    path = str(make_billing_csv(days=21, rows_per_day=20))
    assert to_dict(analyze(path)) == to_dict(analyze(path))


def test_analyze_reports_period_and_totals(make_billing_csv: Callable[..., Path]) -> None:
    r = analyze(str(make_billing_csv(days=14, rows_per_day=10)))

    assert r.period_start == "2024-01-01"
    assert r.period_end == "2024-01-14"
    assert r.period_days == 14
    assert r.records == 140
    assert r.resources == 140  # no identifier columns -> one resource per line item
    assert r.total_spend == pytest.approx(sum(r.daily_costs), rel=1e-9)
    assert len(r.forecast.values) == 7


def test_injected_idle_resource_is_found(tmp_path: Path) -> None:
    df = billing_frame(days=10, rows_per_day=10).assign(
        ResourceId=lambda d: [f"r{i % 20}" for i in range(len(d))], ConsumedUnit="Hours"
    )
    idle = {"UsageDate": "2024-01-03", "ServiceCategory": "Storage", "EffectiveCost": 75.0,
            "ConsumedQuantity": 0.0, "ResourceId": "vol-idle", "ConsumedUnit": "GB"}  # fmt: skip
    path = tmp_path / "b.csv"
    pd.concat([df, pd.DataFrame([idle])]).to_csv(path, index=False)

    findings = {f.resource_key: f for f in analyze(str(path)).findings}

    assert findings["vol-idle"].confidence == "High"
    assert findings["vol-idle"].estimated_waste == pytest.approx(75.0)


def test_aliases_are_accepted(tmp_path: Path) -> None:
    path = tmp_path / "aws.csv"
    billing_frame(days=5).rename(
        columns={"EffectiveCost": "UnblendedCost", "ConsumedQuantity": "UsageQuantity"}
    ).to_csv(path, index=False)
    assert analyze(str(path)).records == 100


def test_schema_error_lists_accepted_names() -> None:
    with pytest.raises(DataValidationError, match="UnblendedCost"):
        normalize_columns(pd.DataFrame({"UsageQuantity": [1]}))


def test_cli_writes_json(make_billing_csv: Callable[..., Path], tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    assert main([str(make_billing_csv(days=10)), "--out", str(out)]) == 0

    data = json.loads(out.read_text())
    assert data["records"] == 200
    assert {"findings", "forecast", "total_waste", "confidence_summary"} <= set(data)


def test_cli_prints_to_stdout(
    make_billing_csv: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(make_billing_csv(days=10))]) == 0
    assert json.loads(capsys.readouterr().out)["period_days"] == 10


def test_cli_rejects_bad_data(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n")
    assert main([str(bad)]) == 1


def test_cli_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main([str(tmp_path / "nope.csv")])
