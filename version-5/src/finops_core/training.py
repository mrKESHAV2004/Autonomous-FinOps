"""Offline training pipeline: ``finops-train`` / ``python -m finops_core.training``.

Moved from ``ml.py`` (``main_training_pipeline`` and the ``__main__`` block).
Trains the detector and forecaster on a billing file and writes the models and
a ``training_metadata.json`` to an output directory.
"""

from __future__ import annotations

import argparse
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
from finops_core.forecasting import AdvancedForecaster
from finops_core.preprocessing import DataPreprocessor

logger = logging.getLogger(__name__)

MODEL_VERSION = "optimized_v3"
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
        zombie_results = detector.detect_anomalies(df_analysis)
        forecast_results = AdvancedForecaster(lookback_window=14, forecast_days=7).forecast(
            df_analysis
        )
    except DataValidationError as exc:
        logger.error("Training data rejected: %s", exc)
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("Training failed")
        return {"success": False, "error": str(exc)}

    _save_models(out, detector, forecast_results)
    metadata = {
        "training_date": datetime.now().isoformat(),
        "data_source": str(data_path),
        "records_analyzed": len(df_analysis),
        "zombie_count": zombie_results["zombie_count"],
        "total_waste": float(zombie_results["total_waste"]),
        "waste_percentage": float(zombie_results["waste_percentage"]),
        "forecast_total": float(sum(forecast_results["forecast"])),
        "forecast_metrics": forecast_results.get("metrics", {}),
        "feature_importance": zombie_results.get("feature_importance"),
        "model_version": MODEL_VERSION,
    }
    (out / "training_metadata.json").write_text(json.dumps(metadata, indent=2))
    logger.info("Training complete; models saved to %s", out)

    return {
        "success": True,
        "zombie_count": zombie_results["zombie_count"],
        "total_waste": zombie_results["total_waste"],
        "forecast_total": sum(forecast_results["forecast"]),
        "output_dir": str(out),
    }


def _save_models(
    out: Path, detector: OptimizedZombieDetector, forecast_results: dict[str, Any]
) -> None:
    if detector.model is not None:
        joblib.dump(detector.model, out / "zombie_model.pkl")
        joblib.dump(detector.scaler, out / "zombie_scaler.pkl")
        logger.info("Saved zombie detection model")

    if forecast_results.get("model") is not None:
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
