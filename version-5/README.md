# Autonomous-FinOps — version 5

Version 5 is the start of turning the prototype into a product.
See [../PRODUCT_PLAN.md](../PRODUCT_PLAN.md) for the roadmap and
[../ARCHITECTURE.md](../ARCHITECTURE.md) for diagrams.

**Status:** Phase 0 (foundation) — same analysis results as version 4, now as an
installable, tested package.

## Layout

```
version-5/
├── pyproject.toml          # dependencies + ruff/black/mypy/pytest config
├── uv.lock                 # pinned versions
├── .env.example            # all FINOPS_* settings
├── src/
│   ├── finops_core/        # analysis engine, no web code
│   │   ├── preprocessing.py   # load CSV, clean, ~40 features
│   │   ├── detection.py       # 3× IsolationForest ensemble + confidence
│   │   ├── forecasting.py     # 3-layer LSTM, 7-day forecast + intervals
│   │   ├── recommendations.py # dashboard recommendation cards
│   │   └── training.py        # offline training CLI (finops-train)
│   └── finops_app/         # Flask app
│       ├── __init__.py        # create_app()
│       ├── config.py          # Config.from_env()
│       ├── logging_config.py  # text logs (dev) / JSON logs (prod)
│       ├── analysis.py        # run_analysis(): file → dashboard data
│       ├── plots.py           # matplotlib charts
│       ├── routes.py          # /, /upload, /sample
│       └── templates/
├── tests/                  # pytest (unit, route, golden-file)
├── finops_artifacts/       # models from an offline training run
└── sample_cloud_data.csv   # 100-day synthetic dataset
```

## Setup

Needs Python 3.11 or 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd version-5
uv sync --extra dev
```

## Run the web app

```bash
uv run finops-web
```

Open http://127.0.0.1:5000 and upload a FOCUS billing CSV
(e.g. `../focus_sample_10000.csv`). Settings come from `FINOPS_*` environment
variables — see `.env.example`. In production set `FINOPS_ENV=production` and
`FINOPS_SECRET_KEY`, and serve with a WSGI server:

```bash
uv run --with gunicorn gunicorn 'finops_app.wsgi:app'
```

`python interface.py` still works as a shortcut for `finops-web`.

## Train models offline

```bash
uv run finops-train ../focus_data_table.csv.gz --output-dir finops_artifacts
uv run finops-train --demo   # synthetic data
```

## Checks

```bash
uv run pytest                      # all tests
uv run pytest -m "not slow"        # skip LSTM training tests
uv run pytest --cov                # with coverage
uv run ruff check . && uv run black --check . && uv run mypy
uv run bandit -c pyproject.toml -r src
```

The same checks run in GitHub Actions (`.github/workflows/ci.yml`).
Optional git hook, from the repo root: `version-5/.venv/bin/pre-commit install`.

## What changed from version 4

- Code split into `finops_core` (engine) and `finops_app` (web), one module per job.
- The duplicate "fallback" ML code in `interface.py` is gone.
- `print()` replaced by `logging`; JSON logs in production.
- Config in one place with fail-fast checks (production refuses to start without a secret key or with debug on).
- Upload errors: validation problems show a clear message; internal errors are logged and shown as a generic message (no stack details leak to the browser). Over-size uploads get a friendly message.
- LSTM seeds are set per run, and its checkpoint file goes to a private temp directory (no clashes between concurrent uploads).
- Golden-file tests pin the version-4 results so later refactors can't silently change them.
