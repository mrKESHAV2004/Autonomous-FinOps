"""Core FinOps analysis engine: preprocessing, zombie detection, forecasting.

This package has no web dependencies so it can be used from the Flask app,
a CLI, a background worker or a notebook.
"""

from finops_core.errors import DataValidationError

__all__ = ["DataValidationError"]
__version__ = "0.5.0"
