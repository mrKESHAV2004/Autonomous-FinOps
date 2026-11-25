# Autonomous-FinOps — version 5

Version 5 is the start of turning the prototype into a product.
See [../PRODUCT_PLAN.md](../PRODUCT_PLAN.md) for the roadmap and
[../ARCHITECTURE.md](../ARCHITECTURE.md) for diagrams.

**Status:** Phase 2 (persistence and background jobs) done. Uploads return at
once, analyses run on a worker, results are stored in a database, and a history
page lists past analyses. See the plan for details.

## Layout

```
version-5/
├── pyproject.toml          # dependencies + ruff/black/mypy/pytest config
├── uv.lock                 # pinned versions
├── .env.example            # all FINOPS_* settings
├── alembic.ini             # for `alembic revision --autogenerate` during development
├── Dockerfile, docker-compose.yml  # local stack: web, worker, PostgreSQL, Redis
├── docs/adr/               # architecture decision records
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
│       ├── models.py          # SQLAlchemy tables (org-scoped)
│       ├── db.py              # engine, sessions, migrations
│       ├── repository.py      # every query, always filtered by org_id
│       ├── migrations/        # Alembic revisions
│       ├── storage.py         # raw uploads under org-prefixed keys
│       ├── uploads.py         # name, CSV sniff and row-cap checks
│       ├── jobs.py            # job queue: RQ (Redis), thread, or inline
│       ├── tasks.py           # the analysis job
│       ├── cli.py             # finops-db / finops-worker / finops-cleanup
│       ├── analysis.py        # result → dashboard data
│       ├── plots.py           # matplotlib charts
│       ├── routes.py          # /, /upload, /analyses, /analyses/<id>[/status], /sample
│       ├── static/            # Coral theme CSS, textures, product captures
│       └── templates/
├── tests/                  # pytest (unit, route, golden-file)
├── finops_artifacts/       # models from an offline training run
└── sample_cloud_data.csv   # 100-day synthetic dataset
```

## Setup

Needs Python 3.11 or 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd version-5
uv sync --extra dev                  # web app, CLI, tests
uv sync --extra dev --extra ml       # + TensorFlow, for finops-train's LSTM
uv sync --extra dev --extra postgres # + the PostgreSQL driver
```

## Run the web app

```bash
uv run finops-web
```

Open http://127.0.0.1:5000 and upload a FOCUS billing CSV
(e.g. `../focus_sample_10000.csv`). The upload returns at once and the page
updates itself when the analysis is done; past analyses are under **History**.
Settings come from `FINOPS_*` environment variables (see `.env.example`).

With no `FINOPS_REDIS_URL`, the web app stores data in `finops.db` (SQLite),
applies migrations at start-up and runs analyses on a background thread. Jobs a
restart interrupts are re-queued when the app starts again.

In production set `FINOPS_ENV=production`, `FINOPS_SECRET_KEY`,
`FINOPS_DATABASE_URL` (PostgreSQL) and `FINOPS_REDIS_URL`, apply migrations with
`finops-db upgrade`, run at least one `finops-worker`, and serve with a WSGI server:

```bash
uv run --with gunicorn gunicorn 'finops_app.wsgi:app'
```

`python interface.py` still works as a shortcut for `finops-web`.

## The full local stack (PostgreSQL + Redis + worker)

```bash
docker compose up --build    # http://127.0.0.1:5000
docker compose down          # add -v to delete the database and uploads
```

`migrate` applies the schema, then `web` and `worker` start. Credentials in
`docker-compose.yml` are for local use only; override them in `.env`.

## Database, worker and retention commands

```bash
uv run finops-db upgrade           # apply migrations (FINOPS_DATABASE_URL)
uv run finops-worker               # process jobs from FINOPS_REDIS_URL
uv run finops-cleanup              # delete raw uploads older than FINOPS_RETENTION_DAYS (90)
uv run finops-cleanup --days 30    # override the period
uv run alembic revision --autogenerate -m "describe the change"   # after changing models.py
```

Run `finops-cleanup` daily (cron or a scheduler). It deletes only the raw CSVs;
the results stay. A test fails if `models.py` changes without a new migration.

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
FINOPS_TEST_POSTGRES_URL=postgresql+psycopg://user:pass@localhost:5432/db \
  uv run pytest tests/test_repository.py   # also run the database tests on PostgreSQL
uv run ruff check . && uv run black --check . && uv run mypy
uv run bandit -c pyproject.toml -r src
```

The same checks run in GitHub Actions (`.github/workflows/ci.yml`).
Optional git hook, from the repo root: `version-5/.venv/bin/pre-commit install`.

## Phase 2 changes

- **Uploads return immediately** (about 0.1 s): the file is checked (name, that it is UTF-8 CSV text, row cap), stored under an org-prefixed key, and an analysis job is queued. The analysis page polls `/analyses/<id>/status` and shows the dashboard when the job is done, or the reason it failed.
- **Results are stored** (SQLAlchemy 2, Alembic): datasets, analyses, one row per finding (with a status for the Phase 4 workflow), forecast points and an audit log. Tables for organisations, users and memberships exist; until sign-in arrives in Phase 3 everything belongs to one default organisation.
- **Every query is scoped by organisation** through `repository.scoped()`; tests check one org cannot read another's analyses.
- **History page** at `/analyses`.
- **Jobs run on RQ workers** when `FINOPS_REDIS_URL` is set; otherwise on a thread in the web app. See `docs/adr/0001-job-queue.md`.
- **Retention:** `finops-cleanup` deletes raw uploads after 90 days.

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
