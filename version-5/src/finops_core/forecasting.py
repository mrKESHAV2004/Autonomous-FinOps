"""Experimental LSTM neural network forecasting code (moved to research).

Production pipelines exclusively use the deterministic statistical forecaster
in ``finops_core.forecast_baseline``. AdvancedForecaster has been relocated
to ``finops_core.research.forecasting``.
"""

from __future__ import annotations

from finops_core.research.forecasting import (  # noqa: F401
    AdvancedForecaster,
    build_daily_features,
)
