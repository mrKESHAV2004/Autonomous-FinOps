"""Golden-file tests: version-5 must reproduce the version-4 dashboard numbers.

The JSON files in ``tests/fixtures/golden/`` were captured by uploading each
dataset through the *original* ``interface.py`` + ``ml.py`` (before the Phase 0
refactor) and saving the ``results`` dict passed to ``dashboard.html``, minus
the PNG data and the timestamp.

What is compared, and how strictly:

* Everything derived from zombie detection (counts, waste, confidence, tables,
  recommendation cards) is deterministic and must match **exactly**.
* ``savings`` is capped by daily waste, so it barely depends on the LSTM: 5%.
* ``forecast_bau`` comes from LSTM training, which is not reproducible even in
  the original code. Repeated baseline runs on 2026-11-20 spread by 12%
  (focus_sample), 24% (focus_sample_10000) and 0.3% (sample_cloud_data,
  100 days), so the tolerance is per dataset.
* ``forecast_opt`` and ``savings_pct_vs_bau`` are checked for consistency with
  the two values above rather than against fixed numbers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from finops_app.analysis import run_analysis

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
PROJECT = Path(__file__).parent.parent
REPO = PROJECT.parent

FORECAST_KEYS = {"forecast_bau", "forecast_opt", "savings", "savings_pct_vs_bau"}
SAVINGS_RTOL = 0.05
SAVINGS_CARD = "Significant Savings Potential"

CASES = [
    pytest.param(REPO / "focus_sample.csv", "focus_sample", 0.35, id="focus_sample"),
    pytest.param(
        REPO / "focus_sample_10000.csv", "focus_sample_10000", 0.35, id="focus_sample_10000"
    ),
    pytest.param(
        PROJECT / "sample_cloud_data.csv",
        "sample_cloud_data",
        0.05,
        id="sample_cloud_data",
        marks=pytest.mark.slow,
    ),
]


def _number(text: str) -> float:
    return float(re.sub(r"[$,%]", "", text))


def _comparable(results: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in results.items() if k not in ("plots", "analysis_time")}
    out["plot_keys"] = sorted(results["plots"].keys())
    return out


def _without_savings_card(results: dict[str, Any]) -> list[dict[str, str]]:
    return [r for r in results["recommendations"] if r["title"] != SAVINGS_CARD]


@pytest.mark.parametrize(("csv_path", "name", "bau_rtol"), CASES)
def test_matches_version_4_results(csv_path: Path, name: str, bau_rtol: float) -> None:
    if not csv_path.exists():
        pytest.skip(f"dataset not present: {csv_path}")
    expected = json.loads((GOLDEN / f"{name}.json").read_text())
    actual = _comparable(run_analysis(str(csv_path)))

    assert set(actual) == set(expected)

    exact_keys = set(expected) - FORECAST_KEYS - {"insight_detail", "recommendations"}
    for key in sorted(exact_keys):
        assert actual[key] == expected[key], key
    assert actual["insight_detail"][:2] == expected["insight_detail"][:2]
    assert _without_savings_card(actual) == _without_savings_card(expected)

    bau, opt = _number(actual["forecast_bau"]), _number(actual["forecast_opt"])
    savings, pct = _number(actual["savings"]), _number(actual["savings_pct_vs_bau"])

    assert bau == pytest.approx(_number(expected["forecast_bau"]), rel=bau_rtol)
    assert savings == pytest.approx(_number(expected["savings"]), rel=SAVINGS_RTOL, abs=0.05)
    assert opt == pytest.approx(bau - savings, abs=0.02)
    assert pct == pytest.approx(savings / bau * 100, abs=0.1)
