"""Exceptions raised by the core engine.

Messages on these exceptions are safe to show to end users.
"""


class DataValidationError(ValueError):
    """The uploaded billing data cannot be analysed (missing columns, no rows, ...)."""
