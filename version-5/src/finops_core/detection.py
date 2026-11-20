"""Zombie (wasteful resource) detection with an Isolation Forest ensemble.

Moved from ``ml.py`` (``OptimizedZombieDetector``) with behaviour preserved.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

logger = logging.getLogger(__name__)

BASE_FEATURE_CANDIDATES = (
    "LogCost",
    "LogUsage",
    "CostPerUnit",
    "LogCostPerUnit",
    "CostZScore",
    "UsageZScore",
    "CostUsageInteraction",
    "CostUsageRatio",
    "UsageCostRatio",
    "CostPercentile",
    "UsagePercentile",
    "CostUsageDiff",
    "CostUsageSum",
    "IsCostOutlier",
    "IsUsageOutlier",
    "ServiceFrequency",
    "IsStartOfMonth",
    "IsEndOfMonth",
    "CostSquared",
    "UsageSquared",
    "LogCostRatio",
)
TEMPORAL_FEATURES = ("DayOfWeekSin", "DayOfWeekCos", "MonthSin", "MonthCos")
SERVICE_FEATURES = ("CostVsServiceMean", "UsageVsServiceMean")
FALLBACK_FEATURES = ["LogCost", "LogUsage"]

MAX_SELECTED_FEATURES = 15
MIN_FEATURE_VARIANCE = 1e-6
MIN_CONTAMINATION = 0.02
MAX_CONTAMINATION = 0.15
HIGH_CONFIDENCE = 0.65
MEDIUM_CONFIDENCE = 0.45
CONFIDENCE_LEVELS = ("High", "Medium", "Low")


class OptimizedZombieDetector:
    """Ensemble of three Isolation Forests (balanced, aggressive, conservative)."""

    def __init__(self) -> None:
        self.model: IsolationForest | None = None
        self.scaler: RobustScaler | None = None
        self.feature_importance: dict[str, float] | None = None

    def _select_best_features(
        self, df: pd.DataFrame, target_col: str = "EffectiveCost"
    ) -> list[str]:
        candidates = list(BASE_FEATURE_CANDIDATES)
        if "DayOfWeekSin" in df.columns:
            candidates.extend(TEMPORAL_FEATURES)
        if "CostVsServiceMean" in df.columns:
            candidates.extend(SERVICE_FEATURES)
        if "CostVsRollingMean" in df.columns:
            candidates.append("CostVsRollingMean")

        available = [f for f in candidates if f in df.columns]

        if len(available) > 5:
            variances = df[available].var()
            high_var = variances[variances > MIN_FEATURE_VARIANCE].index.tolist()
            if target_col in df.columns:
                correlations = df[high_var].corrwith(df[target_col]).abs()
                available = correlations.nlargest(
                    min(MAX_SELECTED_FEATURES, len(high_var))
                ).index.tolist()

        if len(available) < 2:
            available = list(FALLBACK_FEATURES)
        return available

    def detect_anomalies(self, df: pd.DataFrame) -> dict[str, Any]:
        """Score rows in ``df`` (adds score columns in place) and return the zombies."""
        features = self._select_best_features(df)
        logger.info("Selected %d features: %s", len(features), features[:5])

        self.scaler = RobustScaler()
        x_scaled = self.scaler.fit_transform(df[features].fillna(0).values)

        contamination = estimate_contamination(df["EffectiveCost"])
        logger.info("Adaptive contamination: %.4f", contamination)

        models, predictions, decisions = _fit_ensemble(x_scaled, contamination)
        self.model = models[0]

        ensemble_pred = np.array(predictions).sum(axis=0)
        df["anomaly_score"] = np.where(ensemble_pred <= -1, -1, 1)  # >= 2 of 3 agree
        ensemble_decision = np.array(decisions).mean(axis=0)
        df["decision_function"] = ensemble_decision
        df["anomaly_probability"] = _decision_to_probability(ensemble_decision)

        zombies = df[df["anomaly_score"] == -1].copy()
        if len(zombies) > 0:
            zombies["confidence"] = _confidence_levels(zombies)
            df.loc[df["anomaly_score"] == -1, "confidence"] = zombies["confidence"].values

        total_waste = zombies["EffectiveCost"].sum() if len(zombies) > 0 else 0
        total_spend = df["EffectiveCost"].sum()
        waste_percentage = (total_waste / total_spend * 100) if total_spend > 0 else 0

        if hasattr(self.model, "feature_importances_"):
            self.feature_importance = dict(
                zip(features, self.model.feature_importances_, strict=False)
            )

        logger.info(
            "Zombies: %d, waste: $%.2f (%.2f%%)", len(zombies), total_waste, waste_percentage
        )
        return {
            "zombies": zombies,
            "df_with_scores": df,
            "total_waste": total_waste,
            "waste_percentage": waste_percentage,
            "zombie_count": len(zombies),
            "feature_importance": self.feature_importance,
        }


def estimate_contamination(costs: pd.Series) -> float:
    """Expected anomaly share, adapted to dataset size and the cost tail."""
    n = len(costs)
    base = min(MAX_CONTAMINATION, max(MIN_CONTAMINATION, 50 / n))
    if n <= 100:
        return base
    p95, p99 = costs.quantile(0.95), costs.quantile(0.99)
    high_cost_ratio = (costs > p95).sum() / n
    very_high_cost_ratio = (costs > p99).sum() / n
    return float(
        min(MAX_CONTAMINATION, max(base, high_cost_ratio * 0.5 + very_high_cost_ratio * 2))
    )


def _fit_ensemble(
    x_scaled: np.ndarray, contamination: float
) -> tuple[list[IsolationForest], list[np.ndarray], list[np.ndarray]]:
    configs = [
        # balanced
        {"n_estimators": 300, "contamination": contamination, "max_features": 1.0,
         "random_state": 42, "bootstrap": False},
        # aggressive
        {"n_estimators": 300, "contamination": min(contamination * 1.5, 0.2),
         "max_features": 0.8, "random_state": 43, "bootstrap": True},
        # conservative
        {"n_estimators": 200, "contamination": max(contamination * 0.7, 0.01),
         "max_features": 1.0, "random_state": 44, "bootstrap": False},
    ]  # fmt: skip
    models, predictions, decisions = [], [], []
    for params in configs:
        model = IsolationForest(n_jobs=-1, verbose=0, **params)
        predictions.append(model.fit_predict(x_scaled))
        decisions.append(model.decision_function(x_scaled))
        models.append(model)
    return models, predictions, decisions


def _decision_to_probability(decision: np.ndarray) -> np.ndarray:
    """Blend a z-score sigmoid with rank percentile to avoid 'all low' outputs."""
    dec_z = (decision - np.mean(decision)) / (np.std(decision) + 1e-6)
    prob_sigmoid = 1 / (1 + np.exp(-dec_z))
    prob_rank = pd.Series(decision).rank(pct=True).to_numpy()
    return 0.6 * prob_sigmoid + 0.4 * prob_rank


def _confidence_levels(zombies: pd.DataFrame) -> np.ndarray:
    """High/Medium/Low per zombie, boosted for high cost and low usage."""
    scores = zombies["anomaly_probability"].copy()
    if "EffectiveCost" in zombies.columns:
        scores = scores * (0.6 + 0.4 * zombies["EffectiveCost"].rank(pct=True))
    if "ConsumedQuantity" in zombies.columns:
        scores = scores * (0.6 + 0.4 * (1 - zombies["ConsumedQuantity"].rank(pct=True)))

    lo, hi = scores.min(), scores.max()
    if hi > lo:
        scores = (scores - lo) / (hi - lo)

    conditions = [
        scores >= HIGH_CONFIDENCE,
        scores >= MEDIUM_CONFIDENCE,
        scores < MEDIUM_CONFIDENCE,
    ]
    return np.select(conditions, list(CONFIDENCE_LEVELS), default="Medium")


def confidence_summary(zombies: pd.DataFrame) -> dict[str, int]:
    """Count zombies per confidence level (always returns all three keys)."""
    summary = dict.fromkeys(CONFIDENCE_LEVELS, 0)
    if len(zombies) > 0 and "confidence" in zombies.columns:
        counts = zombies["confidence"].value_counts()
        for level in CONFIDENCE_LEVELS:
            summary[level] = int(counts.get(level, 0))
    return summary
