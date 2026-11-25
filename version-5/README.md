# Autonomous-FinOps — version 5

Version 5 is the start of turning the prototype into a product.
See [../PRODUCT_PLAN.md](../PRODUCT_PLAN.md) for the roadmap and
[../ARCHITECTURE.md](../ARCHITECTURE.md) for diagrams.

**Status:** Phase 1 (core engine) done — resource-level findings with reasons,
a fast statistical forecast, and a `finops-analyze` CLI. See the plan for details.

## Layout

```
version-5/
├── pyproject.toml          # dependencies + ruff/black/mypy/pytest config
├── uv.lock                 # pinned versions
├── .env.example            # all FINOPS_* settings
├── src/
│   ├── finops_core/        # analysis engine, no web code
│   │   ├── schema.py          # required columns + accepted aliases
│   │   ├── preprocessing.py   # load CSV, clean, ~40 row features
│   │   ├── resources.py       # per-resource findings: idle / overpriced / ml_outlier
│   │   ├── detection.py       # row-level IsolationForest ensemble (supporting signal)
│   │   ├── forecast_baseline.py # moving-average vs weekly forecast, chosen by backtest
│   │   ├── forecasting.py     # LSTM (offline only, needs the [ml] extra)
│   │   ├── models.py          # Finding / ForecastResult / AnalysisResult dataclasses
│   │   ├── pipeline.py        # analyze() + finops-analyze CLI
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
uv sync --extra dev            # web app, CLI, tests
uv sync --extra dev --extra ml # + TensorFlow, for finops-train's LSTM
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

## Analyse a file from the command line

```bash
uv run finops-analyze ../focus_sample_10000.csv --out result.json
```

Prints (or writes) JSON: totals, every finding with its reasons, and the forecast.

## Train models offline

Needs the `[ml]` extra for the LSTM; without it, only the detector is trained.
`training_metadata.json` records whether the LSTM beat the statistical baseline.

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

## Phase 1 changes

- **Findings are per resource**, not per billing row, each with reasons: *idle* (billed, zero usage), *overpriced* (≥3× similar resources' price and a statistical outlier among them), *ml_outlier* (supporting).
- **Waste is an estimate of avoidable cost** (cost above the peer median, or the full cost if idle), not the whole bill of every flagged row.
- **Confidence fixed** (version 4 had it inverted) and now means "how many signals agree".
- **Forecast in ~1 s**, no LSTM training per upload; deterministic results.
- Column aliases accepted (`UnblendedCost`, `UsageQuantity`, …).

## Phase 0 changes (from version 4)

- Code split into `finops_core` (engine) and `finops_app` (web), one module per job.
- The duplicate "fallback" ML code in `interface.py` is gone.
- `print()` replaced by `logging`; JSON logs in production.
- Config in one place with fail-fast checks (production refuses to start without a secret key or with debug on).
- Upload errors: validation problems show a clear message; internal errors are logged and shown as a generic message (no stack details leak to the browser). Over-size uploads get a friendly message.
- LSTM seeds are set per run, and its checkpoint file goes to a private temp directory (no clashes between concurrent uploads).
- Golden-file tests pin the analysis output so later changes can't silently alter it.
