"""Billing data loading, cleaning and feature engineering.

Moved from ``ml.py`` (``DataPreprocessor``) with behaviour preserved. The order
of operations matters: row order after the rolling-window sort feeds the
Isolation Forests, so helpers run in exactly the original sequence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

from finops_core.errors import DataValidationError

logger = logging.getLogger(__name__)

DATE_COLUMNS = ("ChargePeriodStart", "UsageDateTime", "BillingPeriodStart", "UsageDate")
REQUIRED_COLUMNS = ("EffectiveCost", "ConsumedQuantity")
EPSILON = 1e-6
ROLLING_WINDOW_DAYS = 7
START_OF_MONTH_LAST_DAY = 5
END_OF_MONTH_FIRST_DAY = 25


class DataPreprocessor:
    """Load a billing CSV and engineer features for anomaly detection."""

    def load_and_preprocess(
        self, file_path: str, sample_size: int | None = None
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return ``(all_rows, rows_with_positive_cost)`` with engineered features."""
        compression: Literal["gzip"] | None = "gzip" if str(file_path).endswith(".gz") else None
        try:
            df = pd.read_csv(file_path, compression=compression, low_memory=False)
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
            raise DataValidationError("The file could not be read as CSV.") from exc

        validate_columns(df)

        if sample_size and sample_size < len(df):
            df = df.sample(sample_size, random_state=42)
            logger.info("Sampled %s records", f"{sample_size:,}")
        logger.info("Loaded %s records from %s", f"{len(df):,}", file_path)

        df = self._process_dates(df)
        df = self._clean_numeric_columns(df)
        df = self._engineer_features(df)

        # Positive costs only: zero-cost rows skew anomaly detection.
        df_analysis = df[df["EffectiveCost"] > 0].copy()
        logger.info("%s records with positive cost kept for analysis", f"{len(df_analysis):,}")
        return df, df_analysis

    def _process_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        for date_col in DATE_COLUMNS:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df["UsageDate"] = df[date_col].dt.date
                logger.info("Using %s as the usage date", date_col)
                break

        if "UsageDate" not in df.columns:
            logger.warning("No date column found; generating synthetic dates")
            base_date = datetime.now().date() - timedelta(days=len(df))
            df["UsageDate"] = [base_date + timedelta(days=i) for i in range(len(df))]
        return df

    def _clean_numeric_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df["EffectiveCost"] = pd.to_numeric(df["EffectiveCost"], errors="coerce")
        df["ConsumedQuantity"] = pd.to_numeric(df["ConsumedQuantity"], errors="coerce")

        df["EffectiveCost"] = df["EffectiveCost"].fillna(0)
        has_usage = df["ConsumedQuantity"].notna().any()
        median_usage = df["ConsumedQuantity"].median() if has_usage else 1
        df["ConsumedQuantity"] = df["ConsumedQuantity"].fillna(median_usage)
        return df

    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = _add_cost_usage_features(df)
        df = _add_temporal_features(df)
        df = _add_service_features(df)
        df = _add_rolling_features(df)
        df = _add_outlier_flags(df)
        df = _add_extra_features(df)

        base_cols = {"UsageDate", "ServiceCategory", "EffectiveCost", "ConsumedQuantity"}
        feature_count = len([col for col in df.columns if col not in base_cols])
        logger.info("Engineered %d features", feature_count)
        return df


def validate_columns(df: pd.DataFrame) -> None:
    """Raise :class:`DataValidationError` if required billing columns are missing."""
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise DataValidationError(
            "Missing required column(s): "
            + ", ".join(missing)
            + ". Expected FOCUS-style billing data."
        )


def _add_cost_usage_features(df: pd.DataFrame) -> pd.DataFrame:
    cost, usage = df["EffectiveCost"], df["ConsumedQuantity"]
    df["LogCost"] = np.log1p(cost)
    df["LogUsage"] = np.log1p(usage)

    df["CostPerUnit"] = cost / (usage + EPSILON)
    df["LogCostPerUnit"] = np.log1p(df["CostPerUnit"])
    df["CostUsageRatio"] = cost / (usage + EPSILON)
    df["UsageCostRatio"] = usage / (cost + EPSILON)

    df["CostZScore"] = (cost - cost.mean()) / (cost.std() + EPSILON)
    df["UsageZScore"] = (usage - usage.mean()) / (usage.std() + EPSILON)
    df["CostPercentile"] = cost.rank(pct=True)
    df["UsagePercentile"] = usage.rank(pct=True)

    df["CostUsageInteraction"] = df["LogCost"] * df["LogUsage"]
    df["CostUsageDiff"] = df["LogCost"] - df["LogUsage"]
    df["CostUsageSum"] = df["LogCost"] + df["LogUsage"]
    return df


def _add_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    if "UsageDate" not in df.columns:
        return df
    df["UsageDate"] = pd.to_datetime(df["UsageDate"])
    df["DayOfWeek"] = df["UsageDate"].dt.dayofweek
    df["DayOfMonth"] = df["UsageDate"].dt.day
    df["Month"] = df["UsageDate"].dt.month
    df["Quarter"] = df["UsageDate"].dt.quarter
    df["IsWeekend"] = (df["DayOfWeek"] >= 5).astype(int)

    df["DayOfWeekSin"] = np.sin(2 * np.pi * df["DayOfWeek"] / 7)
    df["DayOfWeekCos"] = np.cos(2 * np.pi * df["DayOfWeek"] / 7)
    df["MonthSin"] = np.sin(2 * np.pi * df["Month"] / 12)
    df["MonthCos"] = np.cos(2 * np.pi * df["Month"] / 12)
    return df


def _add_service_features(df: pd.DataFrame) -> pd.DataFrame:
    if "ServiceCategory" not in df.columns:
        return df
    df["ServiceCategoryEncoded"] = LabelEncoder().fit_transform(df["ServiceCategory"].astype(str))
    service_stats = (
        df.groupby("ServiceCategory")
        .agg({"EffectiveCost": ["mean", "std"], "ConsumedQuantity": ["mean", "std"]})
        .reset_index()
    )
    service_stats.columns = [
        "ServiceCategory",
        "ServiceCostMean",
        "ServiceCostStd",
        "ServiceUsageMean",
        "ServiceUsageStd",
    ]
    df = df.merge(service_stats, on="ServiceCategory", how="left")
    df["CostVsServiceMean"] = df["EffectiveCost"] / (df["ServiceCostMean"] + EPSILON)
    df["UsageVsServiceMean"] = df["ConsumedQuantity"] / (df["ServiceUsageMean"] + EPSILON)
    return df


def _add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    if "UsageDate" not in df.columns or len(df) <= ROLLING_WINDOW_DAYS:
        return df
    window = ROLLING_WINDOW_DAYS
    df_sorted = df.sort_values("UsageDate")
    df_sorted["RollingCostMean7"] = (
        df_sorted["EffectiveCost"].rolling(window=window, min_periods=1).mean()
    )
    df_sorted["RollingCostStd7"] = (
        df_sorted["EffectiveCost"].rolling(window=window, min_periods=1).std()
    )
    df_sorted["RollingUsageMean7"] = (
        df_sorted["ConsumedQuantity"].rolling(window=window, min_periods=1).mean()
    )
    df_sorted["CostVsRollingMean"] = df_sorted["EffectiveCost"] / (
        df_sorted["RollingCostMean7"] + EPSILON
    )
    return df_sorted.copy()


def _iqr_outlier_flag(series: pd.Series) -> pd.Series:
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    return ((series < (q1 - 1.5 * iqr)) | (series > (q3 + 1.5 * iqr))).astype(int)


def _add_outlier_flags(df: pd.DataFrame) -> pd.DataFrame:
    df["IsCostOutlier"] = _iqr_outlier_flag(df["EffectiveCost"])
    df["IsUsageOutlier"] = _iqr_outlier_flag(df["ConsumedQuantity"])
    return df


def _add_extra_features(df: pd.DataFrame) -> pd.DataFrame:
    if "ServiceCategory" in df.columns:
        service_freq = df["ServiceCategory"].value_counts(normalize=True)
        df["ServiceFrequency"] = df["ServiceCategory"].map(service_freq)

    if "DayOfMonth" in df.columns:
        df["IsStartOfMonth"] = (df["DayOfMonth"] <= START_OF_MONTH_LAST_DAY).astype(int)
        df["IsEndOfMonth"] = (df["DayOfMonth"] >= END_OF_MONTH_FIRST_DAY).astype(int)

    df["CostSquared"] = df["EffectiveCost"] ** 2
    df["UsageSquared"] = df["ConsumedQuantity"] ** 2
    df["LogCostRatio"] = df["LogCost"] / (df["LogUsage"] + EPSILON)
    return df
