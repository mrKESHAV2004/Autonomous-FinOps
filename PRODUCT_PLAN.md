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

### Phase 0 — Foundation (≈1 week)
- [ ] `pyproject.toml` with pinned deps (start from `version-5/requirements.txt`); split an `[ml]` extra so the web image can stay slim.
- [ ] Tooling: `ruff`, `black`, `isort`, `mypy`, `pytest`, `pytest-cov`, `bandit`, pre-commit.
- [ ] Replace all `print()` with `logging` (structured JSON in prod).
- [ ] Move to `src/` layout; add `create_app()` and `config.py` (Dev/Test/Prod, all secrets from env, fail fast if `FINOPS_SECRET_KEY` is missing in prod).
- [ ] **Delete the fallback ML path** in `interface.py` — `ml.py` becomes the single implementation.
- [ ] Golden-file test: run the current pipeline on `focus_sample.csv`, snapshot key numbers (zombie count, total waste, forecast sum ± tolerance) so refactors can't silently change results.

**Done when:** `pytest` is green in CI and the app renders the same dashboard for `focus_sample.csv`.

### Phase 1 — Core engine refactor (≈1–2 weeks)
- [ ] Split `ml.py` into `finops_core` modules (§3). Functions < 50 lines, typed, returning frozen dataclasses instead of dicts / DataFrames with side columns.
- [ ] **Schema contract** (`schema.py`): required FOCUS columns, type coercion, clear user-facing errors ("missing column `EffectiveCost`").
- [ ] **Resource-level detection:** aggregate rows by `ResourceId` (fallback: `ServiceName` + `RegionId` + `SubAccountId`) over the window, compute utilisation features (cost trend, usage trend, cost/usage ratio, days since last usage), then score resources. Keep the row-level ensemble as a secondary signal.
- [ ] **Explainability:** each finding carries a reason ("cost $X/day, usage ≈0 for 14 days") and its top contributing features.
- [ ] **Fix forecast cost:** stop retraining the LSTM per request. In order of preference: (a) seasonal/statistical baseline per tenant, cached; (b) LSTM trained offline per tenant on a schedule and loaded from the artifact store. Always keep a naive baseline and report whether the model beats it.
- [ ] Deterministic seeds; record model version + feature list with every result.
- [ ] CLI: `finops analyze path/to/file.csv --out result.json`.

**Done when:** the core package has ≥ 80% coverage, `focus_sample_10000.csv` analyses in < 30 s on a laptop, and findings are grouped by resource with explanations.

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
