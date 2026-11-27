"""Offline training pipeline: ``finops-train`` / ``python -m finops_core.training``.

Trains the row-level detector and (if TensorFlow is installed, ``.[ml]``) the
LSTM forecaster on a billing file, and writes the models plus a
``training_metadata.json`` to an output directory. The metadata's
``forecast_comparison`` says whether the LSTM beat the statistical baseline
on the most recent week; the web app only uses the baseline.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from finops_core.detection import OptimizedZombieDetector
from finops_core.errors import DataValidationError
from finops_core.forecast_baseline import HORIZON_DAYS, daily_series, forecast_daily
from finops_core.research.forecasting import AdvancedForecaster
from finops_core.preprocessing import DataPreprocessor

logger = logging.getLogger(__name__)

MODEL_VERSION = "optimized_v4"
LOOKBACK_DAYS = 14
# The LSTM needs lookback + horizon days to train, plus a held-out week.
MIN_DAYS_FOR_LSTM_BACKTEST = LOOKBACK_DAYS + 2 * HORIZON_DAYS
DEMO_DAYS = 100
DEMO_ROWS_PER_DAY = 100
DEMO_ANOMALY_RATE = 0.05


def main_training_pipeline(
    data_path: str, output_dir: str = "./finops_artifacts"
) -> dict[str, Any]:
    """Train models on ``data_path`` and save them to ``output_dir``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        _, df_analysis = DataPreprocessor().load_and_preprocess(data_path, sample_size=None)
        detector = OptimizedZombieDetector()
        zombie_results = detector.detect_anomalies(df_analysis.copy())
        baseline = forecast_daily(daily_series(df_analysis))
        forecast_results = _train_lstm(df_analysis)
        comparison = compare_with_baseline(df_analysis, baseline.method, baseline.backtest_mae)
    except DataValidationError as exc:
        logger.error("Training data rejected: %s", exc)
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("Training failed")
        return {"success": False, "error": str(exc)}

    _save_models(out, detector, forecast_results)
    forecast_values = forecast_results["forecast"] if forecast_results else baseline.values
    metadata = {
        "training_date": datetime.now().isoformat(),
        "data_source": str(data_path),
        "records_analyzed": len(df_analysis),
        "zombie_count": zombie_results["zombie_count"],
        "total_waste": float(zombie_results["total_waste"]),
        "waste_percentage": float(zombie_results["waste_percentage"]),
        "forecast_total": float(sum(forecast_values)),
        "forecast_metrics": (forecast_results or {}).get("metrics", {}),
        "forecast_comparison": comparison,
        "feature_importance": zombie_results.get("feature_importance"),
        "model_version": MODEL_VERSION,
    }
    (out / "training_metadata.json").write_text(json.dumps(metadata, indent=2))
    logger.info("Training complete; models saved to %s", out)

    return {
        "success": True,
        "zombie_count": zombie_results["zombie_count"],
        "total_waste": zombie_results["total_waste"],
        "forecast_total": float(sum(forecast_values)),
        "lstm_trained": forecast_results is not None and forecast_results.get("model") is not None,
        "output_dir": str(out),
    }


def tensorflow_available() -> bool:
    return importlib.util.find_spec("tensorflow") is not None


def _train_lstm(df: pd.DataFrame) -> dict[str, Any] | None:
    if not tensorflow_available():
        logger.warning("TensorFlow not installed (pip install '.[ml]'); skipping the LSTM")
        return None
    return AdvancedForecaster(lookback_window=LOOKBACK_DAYS, forecast_days=HORIZON_DAYS).forecast(
        df
    )


def compare_with_baseline(
    df: pd.DataFrame, baseline_method: str, baseline_mae: float | None
) -> dict[str, Any]:
    """Backtest the LSTM on the last week (in dollars) against the statistical baseline."""
    comparison: dict[str, Any] = {
        "baseline_method": baseline_method,
        "baseline_backtest_mae": baseline_mae,
        "lstm_backtest_mae": None,
        "lstm_beats_baseline": None,
    }
    daily = daily_series(df)
    if not tensorflow_available() or len(daily) < MIN_DAYS_FOR_LSTM_BACKTEST:
        return comparison

    cutoff = daily.index[-HORIZON_DAYS]
    history = df[pd.to_datetime(df["UsageDate"]) < cutoff]
    predicted = AdvancedForecaster(LOOKBACK_DAYS, HORIZON_DAYS).forecast(history)["forecast"]
    actual = daily.to_numpy()[-HORIZON_DAYS:]
    lstm_mae = float(np.mean(np.abs(actual - np.asarray(predicted))))
    comparison["lstm_backtest_mae"] = round(lstm_mae, 6)
    if baseline_mae is not None:
        comparison["lstm_beats_baseline"] = lstm_mae < baseline_mae
    logger.info("Backtest MAE: LSTM %.2f vs baseline %s", lstm_mae, baseline_mae)
    return comparison


def _save_models(
    out: Path, detector: OptimizedZombieDetector, forecast_results: dict[str, Any] | None
) -> None:
    if detector.model is not None:
        joblib.dump(detector.model, out / "zombie_model.pkl")
        joblib.dump(detector.scaler, out / "zombie_scaler.pkl")
        logger.info("Saved zombie detection model")

    if forecast_results and forecast_results.get("model") is not None:
        forecast_results["model"].save(out / "forecast_lstm.keras")
        scalers = forecast_results["scaler"]
        joblib.dump(
            {"feature_scalers": scalers, "feature_names": list(scalers.keys())},
            out / "forecast_scalers.pkl",
        )
        logger.info("Saved forecasting model")


def generate_demo_data(path: Path, seed: int = 42) -> Path:
    """Write a synthetic 100-day dataset with ~5% expensive, low-usage rows."""
    rng = np.random.default_rng(seed)
    services = ["Compute", "Database", "Storage", "Network"]
    rows = []
    for date in pd.date_range(start="2024-01-01", periods=DEMO_DAYS, freq="D"):
        for _ in range(DEMO_ROWS_PER_DAY):
            cost = rng.exponential(50)
            usage = rng.uniform(1, 100)
            if rng.random() < DEMO_ANOMALY_RATE:
                cost, usage = cost * 5, usage * 0.2
            rows.append(
                {
                    "UsageDate": date.date(),
                    "ServiceCategory": rng.choice(services),
                    "EffectiveCost": cost,
                    "ConsumedQuantity": usage,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train Autonomous-FinOps models.")
    parser.add_argument("data_path", nargs="?", help="Billing CSV or CSV.gz (FOCUS format)")
    parser.add_argument("--output-dir", default="./finops_artifacts")
    parser.add_argument(
        "--demo", action="store_true", help="Generate synthetic data and train on it"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.demo:
        demo_dir = Path(args.output_dir)
        demo_dir.mkdir(parents=True, exist_ok=True)
        data_path = str(generate_demo_data(demo_dir / "demo_cloud_data.csv"))
    elif args.data_path and Path(args.data_path).exists():
        data_path = args.data_path
    else:
        parser.error("data file not found (pass a path, or --demo for synthetic data)")

    result = main_training_pipeline(data_path, args.output_dir)
    if not result["success"]:
        logger.error("Training failed: %s", result.get("error", "unknown error"))
        return 1
    logger.info(
        "Zombies: %s, waste: $%.2f, 7-day forecast: $%.2f",
        f"{result['zombie_count']:,}", result["total_waste"], result["forecast_total"],
    )  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
