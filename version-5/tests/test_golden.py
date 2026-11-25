"""Golden-file tests: analysis output must not change by accident.

The JSON files in ``tests/fixtures/golden/`` are ``finops-analyze`` output for
three datasets. Phase 1 made the analysis deterministic (no LSTM training in
the request path), so results are compared exactly.

If you change detection or forecasting *on purpose*, regenerate them and
review the diff before committing:

    for f in focus_sample focus_sample_10000; do
        uv run finops-analyze ../$f.csv --out tests/fixtures/golden/$f.json
    done
    uv run finops-analyze sample_cloud_data.csv --out tests/fixtures/golden/sample_cloud_data.json

History: Phase 0 pinned the version-4 numbers; they were deliberately
re-baselined on 2026-11-25 for Phase 1 (confidence fix, resource-level
findings, statistical forecast).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finops_core.pipeline import analyze, to_dict

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
PROJECT = Path(__file__).parent.parent
REPO = PROJECT.parent

CASES = [
    pytest.param(REPO / "focus_sample.csv", "focus_sample", id="focus_sample"),
    pytest.param(REPO / "focus_sample_10000.csv", "focus_sample_10000", id="focus_sample_10000"),
    pytest.param(PROJECT / "sample_cloud_data.csv", "sample_cloud_data", id="sample_cloud_data"),
]


@pytest.mark.parametrize(("csv_path", "name"), CASES)
def test_analysis_matches_golden_file(csv_path: Path, name: str) -> None:
    if not csv_path.exists():
        pytest.skip(f"dataset not present: {csv_path}")
    expected = json.loads((GOLDEN / f"{name}.json").read_text())

    actual = json.loads(json.dumps(to_dict(analyze(str(csv_path)))))

    # Compare headline numbers first for a readable failure, then everything.
    for key in ("records", "resources", "period_days", "total_spend", "total_waste"):
        assert actual[key] == expected[key], key
    assert actual["confidence_summary"] == expected["confidence_summary"]
    assert [f["resource_key"] for f in actual["findings"]] == [
        f["resource_key"] for f in expected["findings"]
    ]
    assert actual == expected
