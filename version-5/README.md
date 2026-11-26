# Autonomous-FinOps — version 5

Version 5 is the start of turning the prototype into a product.
See [../PRODUCT_PLAN.md](../PRODUCT_PLAN.md) for the roadmap and
[../ARCHITECTURE.md](../ARCHITECTURE.md) for diagrams.

**Status:** Phase 6 (production deployment & operations) done. Production-ready
container builds with multi-stage non-root Dockerfile and Gunicorn WSGI, S3 object
storage (`S3Storage`), liveness (`/healthz`), readiness (`/readyz` / `/health`),
metrics (`/metrics`), Sentry observability, and full AWS ECS Fargate + RDS PostgreSQL +
ElastiCache Redis + S3 Terraform infrastructure in `deploy/terraform/`. Connect AWS
CUR 2.0 / FOCUS exports via cross-account read-only IAM role with External ID (no
stored secrets), run daily automated ingestion via `finops-sync`, set monthly budgets
with progress tracking on the dashboard, and receive Slack/email alerts. See [../PRODUCT_PLAN.md](../PRODUCT_PLAN.md).

## Layout

```
version-5/
├── pyproject.toml          # dependencies + ruff/black/mypy/pytest config
├── uv.lock                 # pinned versions
├── .env.example            # all FINOPS_* settings
├── alembic.ini             # for `alembic revision --autogenerate` during development
├── Dockerfile, docker-compose.yml  # local stack: gunicorn web, worker, PostgreSQL, Redis
├── deploy/
│   └── terraform/          # production AWS ECS Fargate + RDS + Redis + S3 + ALB
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
│       ├── tasks.py           # the analysis job (with alert dispatch)
│       ├── cli.py             # finops-db / finops-worker / finops-cleanup / finops-sync
│       ├── users_cli.py       # finops-users
│       ├── connectors/        # AWS CUR/FOCUS (STS AssumeRole), Azure, GCP, and sync
│       ├── budgets.py         # monthly budget evaluation per scope
│       ├── alerts.py          # Slack webhook & email alert dispatch
│       ├── connectors_views.py# /connectors: add, verify, sync, delete
│       ├── budgets_views.py   # /budgets: set monthly targets, track spend
│       ├── alerts_views.py    # /alerts: configure Slack/email & test
│       ├── accounts.py        # users, orgs, memberships, role rules, argon2
│       ├── auth.py            # sign-up / sign-in / sign-out, active org, role_required
│       ├── members.py         # /members: add, change role, remove
│       ├── forms.py           # Flask-WTF forms (CSRF)
│       ├── security.py        # CSP + headers, CSRF, rate limits
│       ├── triage.py          # finding statuses, history, carry-over
│       ├── finding_queries.py # filter / sort / page findings
│       ├── findings_views.py  # findings table, CSV export, finding detail
│       ├── finding_text.py    # what each signal means, recommended actions
│       ├── api.py             # JSON API (/api/v1)
│       ├── serializers.py     # rows → dicts for the API and pages
│       ├── sharing.py         # read-only share links, /savings page
│       ├── savings.py         # fixed findings vs the latest upload
│       ├── sample_data.py     # the generated sample billing file
│       ├── analysis.py        # result → dashboard data
│       ├── routes.py          # /, /upload, /analyses, /analyses/<id>[/status], /sample
│       ├── static/            # Coral theme CSS, charts.js, vendor/Chart.js, captures
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

## JSON API

All under `/api/v1`, signed in (the browser session), scoped to your current
organisation. Responses are `{"success": true|false, "data": ..., "error": ...}`,
plus `"meta"` with paging on lists.

| Method | Path | Returns |
|---|---|---|
| GET | `/analyses` | your organisation's analyses, newest first |
| GET | `/analyses/<id>` | status, totals, period, counts by status and confidence, waste by service |
| GET | `/analyses/<id>/series` | daily spend, forecast with its band, forecast after fixes |
| GET | `/analyses/<id>/findings` | findings; `service`, `region`, `account`, `confidence`, `status` (or `active`), `q`, `sort` (`waste`, `monthly`, `cost`, `name`), `page`, `per_page` (25/50/100) |
| GET | `/findings/<id>` | one finding with signal explanations, recommended action and history |
| POST | `/findings/<id>/status` | JSON `{"status", "note", "snoozed_until"}`; analyst or above; needs `X-CSRFToken` |

## Phase 4b changes

- **Savings** (`/savings`): resources marked Fixed, and whether your latest upload still flags them. "Realised" counts the ones it no longer flags. It can't measure how far spend dropped (only flagged resources are stored), and an upload that covers different accounts can make a resource drop out without being fixed.
- **Share links:** owners and admins create a 7- or 30-day read-only link to an analysis overview from the bottom of its page, and revoke it there. Only a hash of the token is stored, so the link is shown once.
- **Dark theme:** follows the system setting; the **Dark mode** switch in the top bar overrides it for that browser.
- **First run:** an empty history and the upload page offer **Analyse the sample**; `/sample` downloads the same file (30 days, 24 resources, FOCUS column names).
- **Accessibility:** a skip link; text contrast checked at WCAG AA on every app page in both themes.

## Phase 6 changes (Production deployment & operations)

- **Production WSGI Server:** Gunicorn (`gunicorn>=22.0`) running 4 workers and 2 threads with non-blocking async IO and standard access/error logging.
- **Multi-Stage Non-Root Docker Image:** Hardened `Dockerfile` with multi-stage `uv` build, running as unprivileged user `finops:finops` with automated Python-based healthcheck.
- **S3 Storage Backend:** Configurable object storage (`FINOPS_STORAGE_BACKEND=s3`, `FINOPS_S3_BUCKET`) via `S3Storage` implementing the `Storage` Protocol with local caching and 90-day retention lifecycles.
- **Health & Readiness Endpoints:**
  - `GET /healthz`: unauthenticated fast liveness probe for load balancers.
  - `GET /readyz` / `GET /health`: readiness probe validating database and Redis connectivity (returns 200 or 503).
  - `GET /metrics`: operational metrics reporting analysis counts, in-flight jobs, and queue depth.
- **Observability:** Structured JSON logs, optional Sentry integration (`FINOPS_SENTRY_DSN`).
- **AWS Infrastructure as Code:** Production Terraform definitions in `deploy/terraform/` for AWS ECS Fargate, RDS PostgreSQL (gp3 encrypted with PITR automated backups), ElastiCache Redis, S3 bucket with 90-day lifecycle, Secrets Manager, and Application Load Balancer.

## Phase 5 changes (Data connectors & automated alerts)

- **Cloud Connectors:** AWS CUR 2.0 / FOCUS connector using cross-account STS `AssumeRole` with External ID and CloudFormation 1-click template. Azure Blob & GCP BigQuery stubs.
- **Scheduled Ingestion:** `finops-sync` CLI and automated background service for continuous billing sync.
- **Budgets:** Monthly spend targets per account, service, or total organization spend with progress bars on the dashboard and `/budgets` view.
- **Alerts:** Slack webhook and email notifications for high-confidence findings, budget overruns, and spend spikes.

## Phase 4a changes

- **Overview and Findings tabs** for each analysis. The overview shows totals, a triage strip (count and waste per status), the biggest open findings, the spend and forecast chart and waste by service. The findings tab filters, searches, sorts and pages, and exports the filtered list as CSV.
- **Finding detail page:** the reasons, what each signal means, a recommended action, a status form and the history.
- **Finding workflow:** Open, Acknowledged, Fixed, Snoozed (until a date) or False positive, with a note. Decisions carry over to the next upload of the same resources; a resource marked fixed that is still there gets reopened.
- **Charts in the browser** with Chart.js (vendored, no CDN) from the JSON API; the numbers are also in tables. matplotlib is no longer a dependency of the web app.

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
