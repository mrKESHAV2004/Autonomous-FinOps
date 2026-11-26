# Autonomous-FinOps — Product Plan (version-5)

**Created:** 2026-11-20
**Starting point:** `version-5/` (copy of version-4, including the hardening edits to `interface.py` — env-based secret key, upload size limit, debug/host from env)
**Architecture notes & diagrams:** [ARCHITECTURE.md](ARCHITECTURE.md)
**Goal:** turn the single-file Flask research prototype into a deployable, multi-user FinOps product that ingests real cloud billing data, finds waste at the *resource* level, forecasts spend, and tracks savings over time.

---

## 1. Where version-5 stands today

| Area | Current state | Gap for a product |
|---|---|---|
| App structure | `interface.py` (674 lines) mixes routes, fallback ML, plotting and recommendation logic | No package layout, no app factory, no config objects |
| ML | `ml.py` (886 lines): `DataPreprocessor`, `OptimizedZombieDetector` (3× IsolationForest ensemble), `AdvancedForecaster` (LSTM) | Models are **re-trained on every upload** inside the HTTP request; saved artifacts in `finops_artifacts/` are never loaded by the web app |
| Duplicate logic | `interface.py` carries a full fallback copy of preprocessing / detection / forecasting | Two implementations that drift apart |
| Detection granularity | Anomalies scored per billing *row* | FOCUS data has `ResourceId`, `SubAccountId`, `RegionId`, `Tags` — users need "this resource is a zombie", not "this row is odd" |
| Persistence | CSV saved to `uploads/`, results rendered once and discarded | No history, no trends, no "savings realised" |
| Users | None (no auth, single global upload folder) | Need accounts, organisations, isolation between tenants |
| Data ingestion | Manual CSV upload only | Need AWS CUR / Azure / GCP billing export connectors |
| Charts | Matplotlib PNGs base64-encoded server-side | Slow, non-interactive |
| Quality | No tests, no CI, `print()` logging | Need tests, lint, typed code, structured logs |
| Deployment | `python interface.py` on port 5000 | Need container, WSGI server, worker queue, managed DB |

---

## 2. Product definition

**Who it's for:** engineering leads and FinOps/finance owners at small-to-mid companies spending $5k–$500k/month on cloud who don't have a dedicated FinOps team.

**Core jobs:**
1. *Connect my billing data* (upload FOCUS CSV now; AWS/Azure/GCP exports later).
2. *Show me where money is wasted* — ranked list of zombie/idle resources with confidence and explanation.
3. *Tell me what next month will cost* — BAU vs. optimised forecast.
4. *Help me act and prove it* — assign, snooze, mark-fixed, and track realised savings.
5. *Alert me* when spend or waste jumps.

**Out of scope for v1:** automatically deleting/stopping cloud resources (the README's "autonomous" action layer). Ship read-only + recommendations first; add remediation behind explicit approval in a later phase.

---

## 3. Target architecture

```
                ┌──────────────┐
  Browser ─────►│ Web frontend  │  (Jinja + HTMX/Alpine first; React later only if needed)
                └──────┬───────┘
                       │ REST/JSON
                ┌──────▼───────┐        ┌────────────────┐
                │  API (Flask)  │──────►│  PostgreSQL     │  users, orgs, datasets,
                │  app factory  │       │                 │  analyses, findings, forecasts
                └──────┬───────┘        └────────────────┘
                       │ enqueue job
                ┌──────▼───────┐        ┌────────────────┐
                │ Worker (RQ /  │──────►│ Object storage  │  raw uploads (S3 / local),
                │ Celery)       │       │                 │  model artifacts
                └──────┬───────┘        └────────────────┘
                       │
                ┌──────▼───────┐
                │ finops_core   │  pure-Python ML package (no Flask imports)
                │ ingest/detect │
                │ forecast/recs │
                └──────────────┘
```

Key decisions:
- **Stay on Flask** (already in use) but adopt an app factory + blueprints. Re-evaluate FastAPI only if the JSON API becomes the main surface.
- **ML runs in a background worker**, never in the request. Upload → job id → page polls status.
- **`finops_core` is a standalone package** so it can be unit-tested and reused from a CLI, the worker, or notebooks.
- **PostgreSQL** via SQLAlchemy 2 + Alembic migrations. SQLite allowed for local dev.

### Proposed layout for `version-5/`

```
version-5/
├── pyproject.toml
├── .env.example
├── Dockerfile
├── docker-compose.yml          # web, worker, postgres, redis
├── src/
│   ├── finops_core/            # no web deps
│   │   ├── schema.py           # FOCUS column contract + validation
│   │   ├── ingest.py           # was DataPreprocessor
│   │   ├── features.py
│   │   ├── detection.py        # was OptimizedZombieDetector
│   │   ├── forecasting.py      # was AdvancedForecaster
│   │   ├── recommendations.py  # was generate_recommendations
│   │   └── models.py           # frozen dataclasses: Finding, Forecast, AnalysisResult
│   └── finops_app/
│       ├── __init__.py         # create_app()
│       ├── config.py
│       ├── db.py / models.py   # SQLAlchemy models
│       ├── auth/               # blueprint
│       ├── datasets/           # upload + connectors blueprint
│       ├── analyses/           # results, findings, forecasts
│       ├── api/                # JSON API v1
│       ├── tasks.py            # worker jobs
│       └── templates/ static/
├── migrations/                 # Alembic
└── tests/
    ├── unit/  integration/  e2e/
    └── fixtures/               # small FOCUS CSVs
```

---

## 4. Phased roadmap

Each phase ends in something runnable. Sizing assumes one developer.

### Phase 0 — Foundation (≈1 week) — ✅ done 2026-11-20
- [x] `pyproject.toml` + `uv.lock` (pinned). *The `[ml]` extra is deferred to Phase 2: the web process still runs the LSTM until the worker exists.*
- [x] Tooling: `ruff` (incl. isort rules), `black`, `mypy`, `pytest`, `pytest-cov`, `bandit`, pre-commit; CI in `.github/workflows/ci.yml` with an 80% coverage gate.
- [x] Replace all `print()` with `logging` (structured JSON in prod).
- [x] `src/` layout (`finops_core`, `finops_app`); `create_app()` and `config.py` (fails fast on missing `FINOPS_SECRET_KEY` or debug in prod).
- [x] **Fallback ML path deleted**; `ml.py` split one-module-per-class into `finops_core` (behaviour unchanged).
- [x] Golden-file tests against the version-4 output for `focus_sample.csv`, `focus_sample_10000.csv` and `sample_cloud_data.csv`.

**Result:** 69 tests pass, 1 strict xfail (bug below), 94.6% coverage; dashboard verified in the browser. See `version-5/README.md`.

**Found during Phase 0 — carried into Phase 1:**
- **Confidence scores are inverted (version-4 bug).** `IsolationForest.decision_function` is *lower* for more anomalous rows, but `_decision_to_probability` maps higher scores to higher probability, so the most extreme zombies are labelled Low. Kept for parity; pinned by `test_most_extreme_zombies_get_high_confidence` (strict xfail).
- **LSTM forecasts are not reproducible on short histories, even in version 4:** repeated runs spread 12% (`focus_sample`, 25 days) and 24% (`focus_sample_10000`, 30 days), vs 0.3% on 100 days. Strengthens the case for a statistical baseline below.
- Features are computed before zero/negative-cost rows (credits) are dropped, causing harmless `log1p` warnings; filter first.

### Phase 1 — Core engine refactor (≈1–2 weeks) — ✅ done 2026-11-25
- [x] Results are frozen dataclasses (`finops_core/models.py`: `Finding`, `ForecastResult`, `AnalysisResult`).
- [x] Inverted confidence score fixed; regression test added; golden files deliberately re-baselined.
- [x] **Schema contract** (`schema.py`): required columns with common aliases (`UnblendedCost`, `UsageQuantity`, …) and a user-facing error listing accepted names. Zero/negative-cost rows are dropped *before* feature engineering.
- [x] **Resource-level detection** (`resources.py`): rows grouped by `ResourceId` → `ServiceName|RegionId|SubAccountId` → line item. Signals: *idle* (zero usage), *overpriced* (≥3× the peer median cost-per-unit **and** modified z-score ≥ 3.5 within service + unit), *ml_outlier* (row ensemble, supporting only). Waste = full cost if idle, else cost above the peer median — not the whole bill.
- [x] **Explainability:** every finding has plain-English reasons and the signals that fired.
- [x] **Forecast:** statistical baseline (`forecast_baseline.py`: 7-day moving average vs weekly-seasonal, picked by last-week backtest) in every analysis; the LSTM is offline-only (`finops-train`), and `training_metadata.json` records whether it beat the baseline. TensorFlow moved to the optional `[ml]` extra.
- [x] Deterministic results; `analysis_version` recorded with every result.
- [x] CLI: `finops-analyze file.csv --out result.json`.

**Result:** `focus_sample_10000.csv` analyses in ~1.5 s (was ~17 s); estimated waste 11.7% of spend across 11 resources (version 4 reported ~48% of rows' cost). 106 tests, 96% coverage.

**Deferred** (needs data with longer per-resource history than the samples have): cost/usage *trend* features and "days since last usage"; per-tenant caching of forecasts (comes with the database in Phase 2).

### Phase 2 — Persistence & async jobs (≈1–2 weeks) — ✅ done 2026-11-26
- [x] SQLAlchemy 2 models (`finops_app/models.py`): `Organization`, `User`, `Membership(role)`, `Dataset`, `Analysis(status, analysis_version, started/finished, error, headline totals, daily series)`, `Finding(one row per resource, confidence, signals, reasons, status)`, `ForecastPoint`, `AuditLog`. Random hex ids, so URLs can't be enumerated.
- [x] Alembic migrations (`finops_app/migrations`, applied by `finops-db upgrade` or at start-up outside production); a test fails if models drift from the migrations. Every customer-data query starts from `repository.scoped(Model, org_id)`; isolation is tested, and the database tests also run on PostgreSQL in CI.
- [x] Redis + RQ worker (`finops-worker`); with no Redis the web app runs jobs on a thread and re-queues interrupted ones at start-up (ADR `version-5/docs/adr/0001-job-queue.md`). Upload creates a `Dataset` and a queued `Analysis` and redirects; the page polls `/analyses/<id>/status`.
- [x] Raw files under org-prefixed keys (`<org>/<yyyy>/<mm>/<id>.csv`) via a `Storage` interface (local directory now); uploads are checked before anything is stored: extension, UTF-8 CSV sniff (no binary data, a comma-separated header), size (`FINOPS_MAX_UPLOAD_MB`) and row cap (`FINOPS_MAX_ROWS`).
- [x] Retention: `finops-cleanup` deletes raw uploads older than `FINOPS_RETENTION_DAYS` (90); results are kept and each deletion is audited.
- [x] `docker-compose.yml`: web, worker, PostgreSQL, Redis and a one-shot migration.

**Result:** the upload request returns in about 0.1 s; on the Docker stack the RQ worker analysed `focus_sample_10000.csv` in 1.8 s, and the result survived a web restart. 163 tests locally (173 in CI, where the database tests also run on PostgreSQL), 96% coverage.

**Deferred:** the S3 storage backend (Phase 6, with deployment); a command to re-queue jobs lost from Redis; `Finding.status` changes (fix, snooze) arrive with the Phase 4 workflow.

### Phase 3 — Accounts, tenancy & security (≈1 week) — ✅ done 2026-11-26
- [x] Auth: Flask-Login + email/password (argon2id, hashes upgraded on sign-in, equal timing for unknown emails). Sign-up creates the user and a new organisation they own. CSRF on every form (Flask-WTF, global), HttpOnly/SameSite cookies (Secure in production), 8-hour idle timeout (`FINOPS_SESSION_HOURS`), a fresh session at sign-in, POST-only sign-out. OAuth deferred.
- [x] Organisations with roles: Owner, Admin, Analyst, Viewer (`accounts.py`). The active org is re-checked against memberships on every request, so removal is immediate; admins manage only analysts and viewers; an org always keeps an owner (the check locks the org row). Members page and an org switcher; `finops-users` for operators.
- [x] Rate limiting (Flask-Limiter): login 10/min per IP and 20 failed/hour per email and client, sign-up 5/hour, upload 20/hour, status 120/min, 300/min otherwise; Redis-backed when configured. `FINOPS_TRUSTED_PROXIES` for running behind a proxy.
- [x] Security headers written in `security.py` instead of Flask-Talisman (barely maintained): CSP with a per-request script nonce, HSTS in production, `nosniff`, `X-Frame-Options`, referrer and permissions policies, `no-store` on signed-in pages. No `|safe` left in templates.
- [x] `bandit` in CI (since Phase 0); a security review pass (no critical or high findings; the medium ones are fixed, see below); tenant-isolation, role, CSRF and rate-limit tests. Audit log for sign-ins, org creation and every membership change. ADR `version-5/docs/adr/0002-accounts-and-sessions.md`.

**Result:** two organisations use the app side by side; tests show one can't read, poll, list, switch into or change the other's analyses or members, even with a guessed id or a tampered session. 226 tests locally (the database tests also pass on PostgreSQL), 96% coverage.

**Accepted / deferred:** sign-up says when an email is already registered (rate-limited); no password reset or email invites until there is an email service; OAuth and API tokens come with the Phase 4 JSON API. In production, set `FINOPS_REDIS_URL` so rate-limit counters are shared (the app warns otherwise).

### Phase 4 — Product UX (≈2 weeks) — ✅ done 2026-11-26 (4a triage, 4b savings and polish)
- [x] Replace matplotlib PNGs with client-side charts fed by the JSON API: Chart.js 4.4.7, vendored under `static/vendor` (checksum-checked against npm), so the CSP still allows only this site's scripts. Each chart has the same numbers in a table. matplotlib and seaborn left the dependencies.
- [x] JSON API `/api/v1`: analyses, analysis summary (status and confidence counts, waste by service), daily and forecast series, findings (filter, sort, page) and finding detail; status changes by POST with the CSRF header. Same sign-in, roles and org scoping as the pages; one `{success, data, error, meta}` envelope; 401/403/404/409 as JSON.
- [x] Screens: Overview (stats, triage strip by status, the biggest open findings, spend and forecast chart, waste by service) and Findings (filters for service, region, account, confidence, status and search; sort; pages) as tabs of an analysis, plus a Finding detail page (reasons, what each signal means, recommended action, status form, history). The forecast lives on the Overview rather than its own page. Tags as a filter wait for tag columns in the engine.
- [x] Finding workflow: Open → Acknowledged → Fixed / Snoozed (until a date, up to 365 days) / False positive, analysts and above, with an optional note; every change is a `FindingEvent` and an audit entry. False-positive notes are kept for model tuning. **Decisions carry over** to the next upload by resource: false positives, acknowledgements and live snoozes stay; a resource marked fixed that shows up again is reopened with a note. Expired snoozes reopen.
- [x] **Savings tracker (4b):** when a finding is marked fixed, compare later datasets to confirm spend actually dropped; show realised vs. estimated savings. Done as `/savings`: each resource marked Fixed is checked against the org's latest upload. Not flagged there → counted as realised; still flagged → "still wasting"; fixed in the latest upload → "waiting". *Limit:* the engine stores spend only for flagged resources, so this confirms the waste stopped being flagged, not by how much spend dropped; measuring the drop needs per-resource spend for every resource.
- [x] Export findings to CSV (the current filters, UTF-8 with BOM, cells starting with `= + - @` prefixed so spreadsheets don't run them).
- [x] Shareable read-only report link (4b): owners and admins create 7- or 30-day links to an analysis overview and can revoke them; only a SHA-256 of the token is stored; the shared page has no links into the app and is sent `no-store`, `no-referrer`, `noindex`.
- [x] Accessibility pass (4b): every app page checked in the browser for WCAG AA text contrast in both themes (no failures), a skip link, visible focus on every control, charts backed by tables.
- [x] Dark/light theme (4b): follows the system setting, with a switch in the top bar (remembered per browser); charts redraw in the new colours. App pages only; the landing page stays light.
- [x] First-run guidance (4b): an empty history and the upload page offer "Analyse the sample", a generated 30-day FOCUS file with idle and unusual resources; `/sample` downloads the same file.

**4a result:** 270 tests locally, 96% coverage.

**4b result:** 277 tests locally, 97% coverage; share links, savings, the sample and both themes checked in the browser. In the browser, a false positive marked on February's upload stayed a false positive on March's.

**Done when:** a new user can sign up, upload, triage findings and see savings without reading docs.

### Phase 5 — Data connectors & automation (≈2–3 weeks) — ✅ done 2026-11-26
- [x] AWS: read CUR 2.0 / FOCUS export from the customer's S3 bucket via a cross-account read-only IAM role with external ID (`AwsConnector`). CloudFormation template and quick-create URL generator. No long-lived customer keys stored.
- [x] Azure Cost Management FOCUS export and GCP BigQuery billing export connector architecture and stubs (`AzureConnector`, `GcpConnector`).
- [x] Scheduled daily ingestion + analysis per org (`finops_app/connectors/sync.py` and `finops-sync` CLI command).
- [x] Alerts: email + Slack webhook for new high-confidence findings, forecast over budget, day-over-day spend spikes (`finops_app/alerts.py`, wired into worker task on analysis completion).
- [x] Budgets per account/service/total with a forecast-vs-budget view (`finops_app/budgets.py`, `/budgets` page, and overview progress cards).
- [x] UI & JSON API: `/connectors`, `/budgets`, and `/alerts` web pages and `/api/v1` REST endpoints.

**Result:** 302 tests pass, 0 lints, strict mypy type safety, 0 bandit security issues. Organizations can connect AWS once, sync billing data, receive Slack and email alerts, and track spend against budgets.

### Phase 6 — Production deployment & operations (≈1 week, can overlap Phases 4–5)
- [x] Multi-stage, non-root Dockerfile; `docker-compose.yml` for the full local stack with Gunicorn WSGI.
- [x] Gunicorn for web (`gunicorn>=22.0` with 4 workers, 2 threads); worker runs `finops-worker`.
- [x] S3 storage backend: `S3Storage` implementing `Storage` Protocol with local caching, 90-day retention lifecycle, configured via `FINOPS_STORAGE_BACKEND=s3` and `FINOPS_S3_BUCKET`.
- [x] Deploy target: AWS ECS Fargate (web + worker) + RDS Postgres + ElastiCache Redis + S3 defined in Terraform (`deploy/terraform/`).
- [x] CI/CD (GitHub Actions): lint (`ruff`) → format (`black`) → type-check (`mypy`) → security (`bandit`) → unit/integration tests with coverage (`pytest`) → Docker build test → Terraform fmt & validate.
- [x] Observability: structured JSON logs, optional Sentry integration (`FINOPS_SENTRY_DSN`), liveness (`/healthz`), readiness (`/readyz` / `/health`), and metrics (`/metrics`).
- [x] Postgres backups + restore drill documented in `deploy/terraform/README.md`; secrets managed in AWS Secrets Manager.

**Result:** 309 tests pass, 92% coverage, 0 lints, strict mypy type safety, 0 bandit security issues. Validated Terraform IaC for AWS ECS Fargate + RDS Postgres + Redis + S3.

### Phase 7 — Model quality loop (ongoing) — ✅ done 2026-11-26
- [x] Labelled evaluation set from Phase 4 feedback (false positive / fixed); track precision@k of findings (`finops_core/evaluation.py`, `finops_app/model_quality.py`, `finops-eval` CLI, and `/api/v1/model-quality/precision`).
- [x] Forecast backtesting (MAPE vs. naive baseline) per tenant; auto-fallback to the baseline when the model is worse or diverges (`finops_core/forecast_baseline.py`).
- [x] Model registry: version, training window, metrics; roll back on regression (`finops_app/models.py`, `0006_model_registry.py` migration, `finops_app/model_registry.py`, `finops-models` CLI, and `/api/v1/models` API endpoints).
- [x] Rule-based detectors next to ML for known zombie patterns (unattached EBS volumes, idle load balancers, stopped-but-billed instances, old snapshots, idle Elastic IPs) — high precision and easy to explain (`finops_core/rules.py` and `finops_core/resources.py`).

**Result:** 329 tests pass, 0 lints, strict mypy type safety, 0 bandit security issues. Automated feedback-to-eval loop and safe fallback protections.

### Phase 8 — Commercialisation (once there are users)
- [ ] Plans: Free (manual upload, 1 account), Pro (connectors, alerts), Team (SSO, roles). Stripe billing.
- [ ] Landing page (reuse `templates/finOps.html`), docs site, privacy policy / ToS, data processing terms.
- [ ] Optional remediation layer: generate IaC/CLI snippets or open tickets; any automated stop/delete requires explicit per-action human approval and is audit-logged.

---

## 5. Cross-cutting standards

- **Testing:** TDD for new code; unit + integration + e2e (Playwright on the upload → findings flow); ≥ 80% coverage gate in CI.
- **Code style:** PEP 8, type hints throughout, frozen dataclasses for results, files < 800 lines, functions < 50 lines, no mutation of input DataFrames.
- **Security:** no secrets in code, input validated at the boundary, ORM-only DB access, per-org scoping enforced in one place.
- **Errors:** friendly messages in the UI, full context in logs, no swallowed exceptions.
- **Docs:** README updated each phase; ADRs in `docs/adr/` for major decisions (Flask vs FastAPI, RQ vs Celery, LSTM vs baseline).

---

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Unsupervised detector flags too much spend as waste (`training_metadata.json` reports 51% on the large dataset) and users lose trust | Resource-level scoring, rule-based detectors, conservative default threshold, an explanation per finding, feedback loop |
| LSTM is slow/expensive and may not beat a simple baseline | Benchmark against naive/seasonal baselines first; keep the LSTM optional |
| Large CSVs (100k+ rows) time out | Async worker, chunked reads, row caps per plan |
| Handling customer billing data | Encryption at rest, tenant-isolation tests, retention limits, read-only cloud roles |
| Scope creep into auto-remediation | Explicitly out of v1; gated behind approvals later |

---

## 7. Immediate next steps

1. Phase 0 tooling + golden-file test on `version-5`.
2. Remove the fallback ML duplicate from `version-5/interface.py`.
3. Start the `finops_core` split with `schema.py` + `ingest.py` and their tests.

> **Note:** the earlier clean-up changes (root `.gitignore`, `requirements.txt`, `COMB_REPORT.md`, interface hardening in versions 1–4, and removal of committed uploads/pyc/checkpoint files) are saved in `git stash@{0}` ("comb cleanup (pre-version-5)"). Restore them with `git stash pop`. `version-5/` already contains the hardened `interface.py` and its own `requirements.txt`.
