"""Backwards-compatible entry point: ``python interface.py``.

The app now lives in ``src/finops_app`` (see README.md). Prefer
``uv run finops-web``; this shim only exists so the old command keeps working.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from finops_app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
