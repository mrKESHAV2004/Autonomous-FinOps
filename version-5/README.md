# Autonomous-FinOps — version 5

Version 5 is the start of turning the prototype into a product.
See [../PRODUCT_PLAN.md](../PRODUCT_PLAN.md) for the roadmap and
[../ARCHITECTURE.md](../ARCHITECTURE.md) for diagrams.

**Status:** Phase 3 (accounts, tenancy and security) done. People sign up into
their own organisation, roles control who can upload and manage members, and
one organisation can never see another's data. Uploads return at once, analyses
run on a worker and results are kept in a database. See the plan for details.

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
│       ├── users_cli.py       # finops-users
│       ├── accounts.py        # users, orgs, memberships, role rules, argon2
│       ├── auth.py            # sign-up / sign-in / sign-out, active org, role_required
│       ├── members.py         # /members: add, change role, remove
│       ├── forms.py           # Flask-WTF forms (CSRF)
│       ├── security.py        # CSP + headers, CSRF, rate limits
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

Open http://127.0.0.1:5000, create an account (which also creates your
organisation), and upload a FOCUS billing CSV (e.g. `../focus_sample_10000.csv`).
The upload returns at once and the page updates itself when the analysis is
done; past analyses are under **History**, and people under **Members**.
Settings come from `FINOPS_*` environment variables (see `.env.example`).

With no `FINOPS_REDIS_URL`, the web app stores data in `finops.db` (SQLite),
applies migrations at start-up and runs analyses on a background thread. Jobs a
restart interrupts are re-queued when the app starts again.

Without `FINOPS_SECRET_KEY` a random key is used, so a restart signs everyone
out; set one if that bothers you during development.

In production set `FINOPS_ENV=production`, `FINOPS_SECRET_KEY`,
`FINOPS_DATABASE_URL` (PostgreSQL) and `FINOPS_REDIS_URL` (it also holds the
rate-limit counters, so every web process shares them), apply migrations with
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
uv run finops-users create --email you@example.com --org default --role owner
uv run alembic revision --autogenerate -m "describe the change"   # after changing models.py
```

`finops-users create` makes an account (asking for its password) if the email
is new, and gives it a role in an organisation (by slug). Use it once to reach
analyses uploaded before Phase 3, which live in the `default` organisation.

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

## Accounts and roles

| Role | Can |
|---|---|
| Viewer | see analyses and history |
| Analyst | also upload billing files |
| Admin | also add, re-role and remove analysts and viewers |
| Owner | everything, including admins and other owners |

Sign-up creates a user and a new organisation with that user as owner. Others
sign up first and are then added by email under **Members**. Someone in several
organisations switches between them from the organisation name in the top bar.
An organisation always keeps at least one owner.

## Phase 3 changes

- **Sign-in** (Flask-Login): email and password, hashed with argon2. Sessions expire after `FINOPS_SESSION_HOURS` (8) without activity; signing in starts a fresh session; signing out is a POST.
- **Organisations and roles**: the active organisation lives in the session and is re-checked against the user's memberships on every request, so removal takes effect at once. No route takes an org id from the URL or a form.
- **CSRF tokens** on every form (Flask-WTF). A POST without a valid token gets a 400.
- **Rate limits** (Flask-Limiter): login 10/min per IP and 20/hour per email, sign-up 5/hour, upload 20/hour, status checks 120/min, everything else 300/min. Counters live in Redis when `FINOPS_REDIS_URL` is set. Behind a proxy, set `FINOPS_TRUSTED_PROXIES` so limits apply per client, not per proxy.
- **Security headers** on every response: a Content Security Policy with a per-request script nonce (no inline handlers), `X-Frame-Options`, `nosniff`, a referrer policy, and HSTS in production. Signed-in pages are sent with `Cache-Control: no-store`.
- **No more `|safe`**: the findings and waste tables are rendered (and escaped) by Jinja from plain data.
- **Audit log** entries for sign-ins (and failed ones for real accounts), new organisations and every membership change.
- See `docs/adr/0002-accounts-and-sessions.md`.

## Phase 2 changes

- **Uploads return immediately** (about 0.1 s): the file is checked (name, that it is UTF-8 CSV text, row cap), stored under an org-prefixed key, and an analysis job is queued. The analysis page polls `/analyses/<id>/status` and shows the dashboard when the job is done, or the reason it failed.
- **Results are stored** (SQLAlchemy 2, Alembic): datasets, analyses, one row per finding (with a status for the Phase 4 workflow), forecast points and an audit log. Tables for organisations, users and memberships exist; before Phase 3 everything belonged to one default organisation.
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
