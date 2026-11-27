"""Daily spend forecasting with a stacked LSTM (experimental research code).

This model is intended for offline research and backtesting only. Production
pipelines use the deterministic baseline forecaster in finops_core.forecast_baseline.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler

logger = logging.getLogger(__name__)

RANDOM_SEED = 42
MAX_EPOCHS = 150
EARLY_STOP_PATIENCE = 10
LR_PATIENCE = 5
MAX_BATCH_SIZE = 32
RECENT_SEQUENCES = 5
INTERVAL_PERCENTILE = 95


def _keras() -> Any:
    """Import TensorFlow lazily so the rest of the package loads quickly."""
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    import tensorflow as tf

    return tf.keras


class AdvancedForecaster:
    """Forecast the next ``forecast_days`` of total daily cost."""

    def __init__(self, lookback_window: int = 14, forecast_days: int = 7) -> None:
        self.lookback = lookback_window
        self.forecast_days = forecast_days
        self.model: Any = None
        self.scaler: dict[str, RobustScaler] | None = None

    def prepare_sequences(self, daily_costs: pd.Series) -> tuple[np.ndarray, np.ndarray, list[str]]:
        """Build scaled sliding windows: ``lookback`` days in, ``forecast_days`` out."""
        df_features = build_daily_features(daily_costs)

        self.scaler = {}
        scaled_columns = []
        for col in df_features.columns:
            scaler = RobustScaler()
            scaled_columns.append(scaler.fit_transform(df_features[[col]].values))
            self.scaler[col] = scaler
        x_scaled = np.concatenate(scaled_columns, axis=1)

        x, y = [], []
        for i in range(len(x_scaled) - self.lookback - self.forecast_days + 1):
            x.append(x_scaled[i : i + self.lookback])
            y.append(x_scaled[i + self.lookback : i + self.lookback + self.forecast_days, 0])
        return np.array(x), np.array(y), df_features.columns.tolist()

    def build_optimized_lstm(self, input_shape: tuple[int, int]) -> Any:
        keras = _keras()
        layers, reg = keras.layers, keras.regularizers.l1_l2
        model = keras.Sequential(
            [
                keras.Input(shape=input_shape),
                layers.LSTM(128, return_sequences=True,
                            kernel_regularizer=reg(l1=1e-5, l2=1e-4),
                            recurrent_regularizer=reg(l1=1e-5, l2=1e-4)),
                layers.Dropout(0.3),
                layers.LSTM(64, return_sequences=True,
                            kernel_regularizer=reg(l1=1e-5, l2=1e-4),
                            recurrent_regularizer=reg(l1=1e-5, l2=1e-4)),
                layers.Dropout(0.25),
                layers.LSTM(32, return_sequences=False, kernel_regularizer=reg(l1=1e-5, l2=1e-4)),
                layers.Dropout(0.2),
                layers.Dense(64, activation="relu", kernel_regularizer=reg(l1=1e-5, l2=1e-4)),
                layers.Dropout(0.15),
                layers.Dense(32, activation="relu"),
                layers.Dense(self.forecast_days),
            ]
        )  # fmt: skip
        optimizer = keras.optimizers.Adam(
            learning_rate=0.001, beta_1=0.9, beta_2=0.999, epsilon=1e-7
        )
        model.compile(optimizer=optimizer, loss="huber", metrics=["mae", "mse"])
        return model

    def forecast(self, df: pd.DataFrame) -> dict[str, Any]:
        """Forecast from row-level data (needs ``UsageDate`` and ``EffectiveCost``)."""
        daily_costs = df.groupby("UsageDate")["EffectiveCost"].sum().sort_index()

        if len(daily_costs) < self.lookback + self.forecast_days:
            logger.warning("Only %d days of data; using average-cost forecast", len(daily_costs))
            avg_cost = daily_costs.mean() if len(daily_costs) > 0 else 0
            return {
                "forecast": (np.ones(self.forecast_days) * avg_cost).tolist(),
                "confidence_intervals": None,
                "method": "average",
                "model": None,
                "scaler": None,
            }

        keras = _keras()
        keras.utils.set_random_seed(RANDOM_SEED)

        x, y, feature_names = self.prepare_sequences(daily_costs)
        self.model = self.build_optimized_lstm((self.lookback, len(feature_names)))

        train_idx, val_idx = list(TimeSeriesSplit(n_splits=3).split(x))[-1]
        x_train, x_val, y_train, y_val = x[train_idx], x[val_idx], y[train_idx], y[val_idx]

        self._train(x_train, y_train, x_val, y_val)
        metrics = self._fit_metrics(x_train, y_train, x_val, y_val)

        forecast = self._predict_forecast(x)
        lower, upper = self._intervals(forecast, x_val, y_val)
        metrics.update(_forecast_stats(forecast))
        logger.info(
            "%d-day forecast total $%.2f (val MAE %.4f)",
            self.forecast_days, forecast.sum(), metrics["val_mae"],
        )  # fmt: skip

        scalers = self._fitted_scalers()
        return {
            "forecast": forecast.tolist(),
            "confidence_intervals": {"upper": upper.tolist(), "lower": lower.tolist()},
            "method": "advanced_lstm_optimized",
            "model": self.model,
            "scaler": scalers,
            "historical_data": daily_costs.tolist(),
            "metrics": metrics,
            "feature_names": list(scalers.keys()),
        }

    def _fitted_scalers(self) -> dict[str, RobustScaler]:
        if self.scaler is None:
            raise RuntimeError("prepare_sequences() must run before predicting")
        return self.scaler

    def _train(
        self, x_train: np.ndarray, y_train: np.ndarray, x_val: np.ndarray, y_val: np.ndarray
    ) -> None:
        keras = _keras()
        callbacks = keras.callbacks
        batch_size = max(1, min(MAX_BATCH_SIZE, len(x_train) // 4 if len(x_train) > 0 else 1))
        with tempfile.TemporaryDirectory(prefix="finops-lstm-") as tmp:
            checkpoint_path = os.path.join(tmp, "best_lstm_model.keras")
            history = self.model.fit(
                x_train,
                y_train,
                validation_data=(x_val, y_val),
                epochs=MAX_EPOCHS,
                batch_size=batch_size,
                callbacks=[
                    callbacks.EarlyStopping(
                        monitor="val_loss", patience=EARLY_STOP_PATIENCE, restore_best_weights=True
                    ),
                    callbacks.ReduceLROnPlateau(
                        monitor="val_loss", factor=0.5, patience=LR_PATIENCE, min_lr=1e-6
                    ),
                    callbacks.ModelCheckpoint(
                        checkpoint_path, monitor="val_loss", save_best_only=True, mode="min"
                    ),
                ],
                verbose=0,
            )
            if os.path.exists(checkpoint_path):
                self.model.load_weights(checkpoint_path)
        logger.info("LSTM trained; best val loss %.4f", min(history.history["val_loss"]))

    def _fit_metrics(
        self, x_train: np.ndarray, y_train: np.ndarray, x_val: np.ndarray, y_val: np.ndarray
    ) -> dict[str, float]:
        train_pred = self.model.predict(x_train, verbose=0)
        val_pred = self.model.predict(x_val, verbose=0)
        return {
            "train_mae": float(mean_absolute_error(y_train, train_pred)),
            "val_mae": float(mean_absolute_error(y_val, val_pred)),
            "train_rmse": float(np.sqrt(mean_squared_error(y_train, train_pred))),
            "val_rmse": float(np.sqrt(mean_squared_error(y_val, val_pred))),
        }

    def _predict_forecast(self, x: np.ndarray) -> np.ndarray:
        """Average the predictions from the most recent windows, then unscale."""
        cost_scaler = self._fitted_scalers()["cost"]
        start = max(0, len(x) - min(RECENT_SEQUENCES, len(x)))
        preds = [self.model.predict(x[i : i + 1], verbose=0)[0] for i in range(start, len(x))]
        forecast_scaled = (
            np.mean(preds, axis=0) if preds else self.model.predict(x[-1:], verbose=0)[0]
        )
        forecast = cost_scaler.inverse_transform(forecast_scaled.reshape(-1, 1)).flatten()
        return np.maximum(forecast, 0)

    def _intervals(
        self, forecast: np.ndarray, x_val: np.ndarray, y_val: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Per-day band from the 95th percentile of absolute validation error."""
        errors = y_val - self.model.predict(x_val, verbose=0)
        lower, upper = [], []
        for day in range(self.forecast_days):
            day_errors = errors[:, day] if errors.ndim > 1 else errors
            margin = np.percentile(np.abs(day_errors), INTERVAL_PERCENTILE)
            upper.append(forecast[day] + margin)
            lower.append(np.maximum(forecast[day] - margin, 0))
        return np.array(lower), np.array(upper)


def build_daily_features(daily_costs: pd.Series) -> pd.DataFrame:
    """Rolling, lag, rate-of-change and calendar features for each day."""
    data = pd.Series(daily_costs.to_numpy().flatten())
    dates = pd.to_datetime(daily_costs.index)
    features = pd.DataFrame(
        {
            "cost": data.values,
            "rolling_mean_7": data.rolling(7, min_periods=1).mean(),
            "rolling_mean_14": data.rolling(14, min_periods=1).mean(),
            "rolling_mean_30": data.rolling(30, min_periods=1).mean(),
            "rolling_std_7": data.rolling(7, min_periods=1).std(),
            "rolling_std_14": data.rolling(14, min_periods=1).std(),
            "lag_1": data.shift(1),
            "lag_7": data.shift(7),
            "lag_14": data.shift(14),
            "pct_change_1": data.pct_change(1),
            "pct_change_7": data.pct_change(7),
            "ema_7": data.ewm(span=7, adjust=False).mean(),
            "ema_14": data.ewm(span=14, adjust=False).mean(),
        }
    )
    features["day_of_week"] = dates.dayofweek
    features["day_of_month"] = dates.day
    features["month"] = dates.month
    features["is_weekend"] = (dates.dayofweek >= 5).astype(int)
    features["day_of_week_sin"] = np.sin(2 * np.pi * features["day_of_week"] / 7)
    features["day_of_week_cos"] = np.cos(2 * np.pi * features["day_of_week"] / 7)
    features["month_sin"] = np.sin(2 * np.pi * features["month"] / 12)
    features["month_cos"] = np.cos(2 * np.pi * features["month"] / 12)

    # pct_change on zero cost gives inf; then back/forward fill, then zeros.
    features = features.replace([np.inf, -np.inf], np.nan)
    return features.bfill().ffill().fillna(0)


def _forecast_stats(forecast: np.ndarray) -> dict[str, float]:
    mean = float(forecast.mean())
    std = float(forecast.std())
    return {
        "forecast_mean": mean,
        "forecast_std": std,
        "forecast_cv": std / mean if mean > 0 else 0.0,
    }
