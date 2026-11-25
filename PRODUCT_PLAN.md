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

### Phase 2 — Persistence & async jobs (≈1–2 weeks)
- [ ] SQLAlchemy models: `Organization`, `User`, `Membership(role)`, `Dataset`, `Analysis(status, model_version, started/finished)`, `Finding(resource_id, service, region, account, est_monthly_waste, confidence, reason, status)`, `ForecastPoint`, `AuditLog`.
- [ ] Alembic migrations; ORM-only queries; every query scoped by `org_id` through one helper.
- [ ] Redis + RQ (or Celery) worker; upload creates a `Dataset` and enqueues an `Analysis`; UI polls `/analyses/<id>/status`.
- [ ] Raw files in object storage (local dir in dev, S3 in prod) with org-prefixed keys; uploads validated (extension, MIME sniff, size, row cap) before enqueue.
- [ ] Retention policy for raw uploads (e.g. 90 days).

**Done when:** uploading returns immediately, results survive restarts, and a history page lists past analyses.

### Phase 3 — Accounts, tenancy & security (≈1 week)
- [ ] Auth: Flask-Login + email/password (argon2) to start; OAuth (Google/GitHub) next. CSRF on all forms (Flask-WTF), secure cookies, session timeout.
- [ ] Organisations with roles: Owner, Admin, Analyst, Viewer.
- [ ] Rate limiting (Flask-Limiter) on login, upload and API.
- [ ] Security headers (CSP, HSTS) via Flask-Talisman; stop passing server-built HTML tables through `|safe`.
- [ ] `bandit` in CI, a security review pass, and tenant-isolation integration tests (user in org A can never read org B's data).

**Done when:** two orgs can use the app side by side with no data leakage.

### Phase 4 — Product UX (≈2 weeks)
- [ ] Replace matplotlib PNGs with client-side charts (Chart.js / ECharts) fed by the JSON API.
- [ ] Screens: Onboarding/upload → Overview (spend, waste, forecast, trend) → Findings table (filter by account/service/region/tag/confidence, sort by $ impact) → Finding detail (history, explanation, recommended action) → Forecast → History.
- [ ] Finding workflow: Open → Acknowledged → Fixed / Snoozed / False positive. False-positive feedback is stored for model tuning.
- [ ] **Savings tracker:** when a finding is marked fixed, compare later datasets to confirm spend actually dropped; show realised vs. estimated savings.
- [ ] Export findings to CSV; shareable read-only report link.
- [ ] Accessibility (WCAG 2.2 AA), responsive layout, dark/light theme.

**Done when:** a new user can sign up, upload, triage findings and see savings without reading docs.

### Phase 5 — Data connectors & automation (≈2–3 weeks)
- [ ] AWS: read CUR 2.0 / FOCUS export from the customer's S3 bucket via a cross-account read-only IAM role with external ID. No long-lived customer keys stored.
- [ ] Azure Cost Management FOCUS export; GCP BigQuery billing export later.
- [ ] Scheduled daily ingestion + analysis per org.
- [ ] Alerts: email + Slack webhook for new high-confidence findings, forecast over budget, day-over-day spend spikes.
- [ ] Budgets per account/tag with a forecast-vs-budget view.

**Done when:** an org connects AWS once and gets a daily-refreshed dashboard and alerts with no manual uploads.

### Phase 6 — Production deployment & operations (≈1 week, can overlap Phases 4–5)
- [ ] Multi-stage, non-root Dockerfile; `docker-compose.yml` for the full local stack.
- [ ] Gunicorn for web; separate worker image carrying TensorFlow/ML deps.
- [ ] Deploy target: AWS ECS Fargate (web + worker) + RDS Postgres + ElastiCache Redis + S3, defined in CDK or Terraform. Cheaper early option: Fly.io / Render.
- [ ] CI/CD (GitHub Actions): lint → type-check → tests → build image → deploy to staging → manual promote to prod.
- [ ] Observability: structured logs, Sentry, health/readiness endpoints, metrics (job duration, failures, queue depth).
- [ ] Postgres backups + a restore drill; secrets in AWS Secrets Manager.

**Done when:** merges to `main` deploy to staging automatically, prod deploy is one click, and errors alert someone.

### Phase 7 — Model quality loop (ongoing)
- [ ] Labelled evaluation set from Phase 4 feedback (false positive / fixed); track precision@k of findings.
- [ ] Forecast backtesting (MAPE vs. naive baseline) per tenant; auto-fallback to the baseline when the model is worse.
- [ ] Model registry: version, training window, metrics; roll back on regression.
- [ ] Rule-based detectors next to ML for known zombie patterns (unattached EBS volumes, idle load balancers, stopped-but-billed instances, old snapshots) — high precision and easy to explain.

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
