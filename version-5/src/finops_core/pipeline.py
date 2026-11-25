"""End-to-end analysis of one billing file, plus the ``finops-analyze`` CLI.

finops-analyze billing.csv                 # JSON to stdout
finops-analyze billing.csv --out result.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from finops_core.detection import OptimizedZombieDetector
from finops_core.errors import DataValidationError
from finops_core.forecast_baseline import daily_series, forecast_daily
from finops_core.models import ANALYSIS_VERSION, AnalysisResult
from finops_core.preprocessing import DataPreprocessor
from finops_core.resources import find_waste, resource_keys

logger = logging.getLogger(__name__)

MIN_RECORDS = 10


def analyze(filepath: str) -> AnalysisResult:
    """Load, detect waste per resource and forecast. Deterministic for a given file.

    Raises :class:`DataValidationError` with a user-safe message when the data
    cannot be analysed.
    """
    _, df = DataPreprocessor().load_and_preprocess(filepath)
    if len(df) < MIN_RECORDS:
        raise DataValidationError(
            f"Insufficient data. Need at least {MIN_RECORDS} records with positive costs."
        )

    daily = daily_series(df)
    findings = find_waste(df, period_days=len(daily), ml_scores=ml_outlier_scores(df))
    forecast = forecast_daily(daily)
    dates = tuple(d.date().isoformat() for d in daily.index)

    result = AnalysisResult(
        analysis_version=ANALYSIS_VERSION,
        records=len(df),
        resources=int(resource_keys(df).nunique()),
        period_start=dates[0] if dates else None,
        period_end=dates[-1] if dates else None,
        period_days=len(daily),
        total_spend=round(float(df["EffectiveCost"].sum()), 6),
        daily_dates=dates,
        daily_costs=tuple(round(float(v), 6) for v in daily.to_numpy()),
        findings=findings,
        forecast=forecast,
    )
    logger.info(
        "Analysis complete",
        extra={
            "records": result.records,
            "findings": len(findings),
            "waste_pct": round(result.waste_percentage, 2),
            "forecast_method": forecast.method,
        },
    )
    return result


def ml_outlier_scores(df: pd.DataFrame) -> dict[str, float]:
    """resource_key -> highest anomaly probability among its High-confidence rows."""
    zombies = OptimizedZombieDetector().detect_anomalies(df.copy())["zombies"]
    if len(zombies) == 0 or "confidence" not in zombies.columns:
        return {}
    high = zombies[zombies["confidence"] == "High"]
    if len(high) == 0:
        return {}
    scores = high["anomaly_probability"].groupby(resource_keys(high)).max()
    return {str(k): round(float(v), 6) for k, v in scores.items()}


def to_dict(result: AnalysisResult) -> dict[str, Any]:
    """JSON-ready dict, including derived totals."""
    data = asdict(result)
    data["total_waste"] = round(result.total_waste, 6)
    data["waste_percentage"] = round(result.waste_percentage, 6)
    data["confidence_summary"] = result.confidence_summary()
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyse a billing CSV for cloud waste.")
    parser.add_argument("data_path", help="Billing CSV or CSV.gz (FOCUS format)")
    parser.add_argument("--out", help="Write JSON here instead of stdout")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if not Path(args.data_path).exists():
        parser.error(f"file not found: {args.data_path}")
    try:
        result = analyze(args.data_path)
    except DataValidationError as exc:
        logger.error("%s", exc)
        return 1

    payload = json.dumps(to_dict(result), indent=2)
    if args.out:
        Path(args.out).write_text(payload + "\n")
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
