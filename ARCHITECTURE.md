# Autonomous-FinOps — Architecture Notes

**Updated:** 2026-11-20
**Scope:** how `version-5/` works today, and the target architecture it is moving to.
**Companion doc:** [PRODUCT_PLAN.md](PRODUCT_PLAN.md) (phases, tasks, risks).

Diagrams are written in [Mermaid](https://mermaid.js.org/), which renders on GitHub, GitLab and in VS Code (with the Markdown Preview Mermaid extension).

---

## Contents

**Part A — Current system (version-5 as copied from version-4)**
1. [System context](#1-system-context-today)
2. [Components](#2-components-today)
3. [Request lifecycle: upload → dashboard](#3-request-lifecycle-today)
4. [Data preprocessing & features](#4-data-preprocessing--feature-engineering)
5. [Zombie detection ensemble](#5-zombie-detection-ensemble)
6. [Forecasting (LSTM)](#6-forecasting-lstm)
7. [Savings & recommendations](#7-savings--recommendations)
8. [Known architectural problems](#8-known-architectural-problems)

**Part B — Target product architecture**

9. [Target system context](#9-target-system-context)
10. [Target containers](#10-target-containers)
11. [Code layering](#11-code-layering)
12. [Async analysis flow](#12-async-analysis-flow)
13. [Data model](#13-data-model)
14. [Finding lifecycle](#14-finding-lifecycle)
15. [Cloud connectors](#15-cloud-connectors)
16. [Multi-tenancy & security](#16-multi-tenancy--security)
17. [Deployment on AWS](#17-deployment-on-aws)
18. [CI/CD](#18-cicd)
19. [Migration path from version-5](#19-migration-path)

---

# Part A — Current system

> **Status (2026-11-25):** Part A describes the version-4 design that version-5
> started from. Phase 1 has since changed the engine: findings are per
> **resource** (`finops_core/resources.py`: idle / overpriced / ml_outlier
> signals, waste = cost above the peer median), the row ensemble in §5 is only a
> supporting signal with its confidence bug fixed, and the request path uses the
> statistical forecast in `forecast_baseline.py` instead of training the LSTM in
> §6 (now offline-only). Problems 1–4 in §8 are resolved; see
> [PRODUCT_PLAN.md](PRODUCT_PLAN.md) Phase 1 for details.

## 1. System context (today)

One user, one machine, a manual CSV upload. Nothing is stored except the uploaded file.

```mermaid
flowchart LR
    user([FinOps / DevOps user])
    export[(Cloud billing export<br/>FOCUS CSV)]
    app["Autonomous-FinOps<br/>Flask app on localhost:5000"]
    disk[(Local disk<br/>uploads/)]

    export -- downloaded manually --> user
    user -- uploads CSV via browser --> app
    app -- saves raw file --> disk
    app -- renders HTML dashboard --> user
```

## 2. Components (today)

| File | Lines | Responsibility |
|---|---|---|
| `version-5/interface.py` | 674 | Flask app, routes, **fallback copy** of preprocessing/detection/forecasting, matplotlib plotting, recommendation rules, result formatting |
| `version-5/ml.py` | 886 | `DataPreprocessor`, `OptimizedZombieDetector`, `AdvancedForecaster`, and `main_training_pipeline()` (offline script that writes `finops_artifacts/`) |
| `version-5/templates/` | — | `finOps.html` (landing), `index.html` (upload), `dashboard.html` (results) — Bootstrap 5, dark theme |
| `version-5/finops_artifacts/` | — | Saved models from an offline run: `zombie_model.pkl`, `zombie_scaler.pkl`, `forecast_lstm.keras`, `forecast_scalers.pkl`, `training_metadata.json` — **not loaded by the web app** |

```mermaid
flowchart TB
    subgraph Browser
        landing["/ (finOps.html)"]
        upload["/upload (index.html)"]
        dash["dashboard.html"]
    end

    subgraph iface ["interface.py"]
        routes["Flask routes<br/>home · index · sample_data"]
        wrap["Wrappers<br/>load_and_prep_data · detect_zombies · train_and_forecast"]
        fallback["Fallback ML<br/>(used only if ml.py import fails)"]
        plots["generate_plots<br/>matplotlib → base64 PNG"]
        recs["generate_recommendations<br/>rule-based"]
    end

    subgraph mlpy ["ml.py"]
        prep["DataPreprocessor"]
        det["OptimizedZombieDetector"]
        fc["AdvancedForecaster"]
        train["main_training_pipeline<br/>(offline)"]
    end

    artifacts[(finops_artifacts/)]
    uploads[(uploads/)]

    upload --> routes
    routes --> uploads
    routes --> wrap
    wrap --> prep & det & fc
    wrap -.-> fallback
    routes --> plots & recs
    routes --> dash
    train --> prep & det & fc
    train --> artifacts
```

## 3. Request lifecycle (today)

Everything happens **synchronously inside one HTTP POST**, including training three Isolation Forests and an LSTM.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant F as Flask /upload
    participant D as uploads/
    participant P as DataPreprocessor
    participant Z as ZombieDetector
    participant L as AdvancedForecaster
    participant V as Plots + Recs
    participant T as dashboard.html

    U->>F: POST CSV (≤ FINOPS_MAX_UPLOAD_MB)
    F->>F: check extension is .csv
    F->>D: save as {timestamp}_{name}.csv
    F->>P: load_and_preprocess(path)
    P-->>F: df (EffectiveCost > 0, ~40 features)
    alt fewer than 10 rows
        F-->>U: flash warning, redirect
    end
    F->>Z: detect_anomalies(df)
    Note over Z: fits 3 IsolationForests<br/>on this upload
    Z-->>F: zombies + confidence
    F->>L: forecast(df)
    Note over L: builds & trains LSTM<br/>up to 150 epochs
    L-->>F: 7-day forecast + intervals
    F->>V: generate_plots / generate_recommendations
    V-->>F: base64 PNGs, rec cards
    F->>T: render_template(results)
    T-->>U: HTML dashboard (nothing persisted)
```

## 4. Data preprocessing & feature engineering

`DataPreprocessor.load_and_preprocess()` in `ml.py`:

```mermaid
flowchart LR
    csv[(CSV / CSV.gz)] --> read["read_csv<br/>(optional sampling)"]
    read --> dates["_process_dates<br/>first of: ChargePeriodStart,<br/>UsageDateTime, BillingPeriodStart,<br/>UsageDate → UsageDate<br/>(synthetic dates if none)"]
    dates --> nums["_clean_numeric_columns<br/>EffectiveCost NaN→0<br/>ConsumedQuantity NaN→median"]
    nums --> feats["_engineer_features"]
    feats --> filt{"EffectiveCost > 0"}
    filt --> out[(df_analysis)]
```

Feature groups produced by `_engineer_features`:

| Group | Features |
|---|---|
| Log / ratio | `LogCost`, `LogUsage`, `CostPerUnit`, `LogCostPerUnit`, `CostUsageRatio`, `UsageCostRatio`, `LogCostRatio` |
| Statistical | `CostZScore`, `UsageZScore`, `CostPercentile`, `UsagePercentile`, `IsCostOutlier`, `IsUsageOutlier` (IQR) |
| Interaction / polynomial | `CostUsageInteraction`, `CostUsageDiff`, `CostUsageSum`, `CostSquared`, `UsageSquared` |
| Temporal | `DayOfWeek`, `DayOfMonth`, `Month`, `Quarter`, `IsWeekend`, `DayOfWeekSin/Cos`, `MonthSin/Cos`, `IsStartOfMonth`, `IsEndOfMonth` |
| Service context | `ServiceCategoryEncoded`, `ServiceFrequency`, `CostVsServiceMean`, `UsageVsServiceMean` |
| Rolling | `CostVsRollingMean` (when > 7 rows) |

> Only `UsageDate`, `ServiceCategory`, `EffectiveCost`, `ConsumedQuantity` are used. Rich FOCUS columns such as `ResourceId`, `SubAccountId`, `RegionId`, `Tags`, `ChargeCategory` are ignored.

## 5. Zombie detection ensemble

`OptimizedZombieDetector.detect_anomalies()`:

```mermaid
flowchart TB
    df[(df_analysis)] --> sel["_select_best_features<br/>drop var ≤ 1e-6 →<br/>top 15 by abs corr with EffectiveCost"]
    sel --> scale["RobustScaler"]
    df --> cont["Adaptive contamination c<br/>base = clamp(50/n, 0.02, 0.15)<br/>refined from P95/P99 cost ratios"]

    scale --> m1["IsoForest #1 Balanced<br/>300 trees · c · seed 42"]
    scale --> m2["IsoForest #2 Aggressive<br/>300 trees · min(1.5c, 0.2)<br/>max_features 0.8 · bootstrap"]
    scale --> m3["IsoForest #3 Conservative<br/>200 trees · max(0.7c, 0.01)"]
    cont -.-> m1 & m2 & m3

    m1 & m2 & m3 --> vote{"Majority vote<br/>≥ 2 of 3 say anomaly"}
    m1 & m2 & m3 --> avg["Mean decision_function"]
    avg --> prob["anomaly_probability =<br/>0.6·sigmoid(z) + 0.4·rank"]

    vote --> zombies[(zombie rows)]
    prob --> conf["Confidence score<br/>× (0.6 + 0.4·cost pct)<br/>× (0.6 + 0.4·(1 − usage pct))<br/>min-max normalised"]
    zombies --> conf
    conf --> bands{"≥ 0.65 High<br/>≥ 0.45 Medium<br/>else Low"}
```

**Waste definition today:** `total_waste = Σ EffectiveCost of zombie rows`. Because each flagged row counts in full, waste can be very high (51% on the 229k-row dataset in `training_metadata.json`).

## 6. Forecasting (LSTM)

`AdvancedForecaster(lookback_window=14, forecast_days=7)`:

```mermaid
flowchart LR
    df[(df_analysis)] --> agg["groupby UsageDate<br/>Σ EffectiveCost"]
    agg --> fe["Daily features<br/>rolling mean 7/14/30<br/>rolling std 7/14<br/>lag 1/7/14<br/>calendar + sin/cos"]
    fe --> sc["RobustScaler per column"]
    sc --> seq["Sliding windows<br/>14 days in → 7 days out"]
    seq --> split["80 / 20 time split"]
    split --> lstm
    subgraph lstm ["LSTM model"]
        direction TB
        a["LSTM 128 → Dropout 0.3"] --> b["LSTM 64 → Dropout 0.25"]
        b --> c["LSTM 32 → Dropout 0.2"]
        c --> d["Dense 64 (L1/L2) → Dropout 0.15"]
        d --> e["Dense 32 → Dense 7"]
    end
    lstm --> train["Huber loss · ≤150 epochs<br/>EarlyStopping(10) · ReduceLROnPlateau(5)"]
    train --> pred["Predict next 7 days<br/>inverse-scale · clip ≥ 0"]
    train --> ci["Asymmetric intervals<br/>from validation error percentiles"]
```

Short histories fall back to simpler outputs (e.g. average daily cost) when there aren't enough days to build sequences.

## 7. Savings & recommendations

In `interface.py`, after detection and forecast:

```mermaid
flowchart LR
    W["total_waste"] --> dw["daily_waste_avg =<br/>total_waste / period_days"]
    F["forecast (7 days, BAU)"] --> opt["forecast_opt =<br/>Σ max(forecast − daily_waste_avg, 0)"]
    dw --> opt
    F --> sav["potential_savings =<br/>Σ forecast − forecast_opt"]
    opt --> sav
    sav --> rec["generate_recommendations"]
    W --> rec
    rec --> r1["Severity card<br/>waste% > 10 CRITICAL · > 5 HIGH"]
    rec --> r2["Top wasteful ServiceCategory"]
    rec --> r3["Savings card<br/>monthly ≈ 7-day × 30/7"]
    rec --> r4["Count of High-confidence items"]
```

## 8. Known architectural problems

| # | Problem | Effect | Fixed in (target) |
|---|---|---|---|
| 1 | ML training runs inside the HTTP request | Slow uploads, timeouts on big files, one user blocks a worker | §12 async worker |
| 2 | Saved artifacts never used by the app | Every upload re-trains from scratch; no consistent model version | §12, model registry |
| 3 | Fallback ML duplicated in `interface.py` | Two implementations drift | §11 single `finops_core` |
| 4 | Row-level anomalies, waste = full row cost | Inflated waste %, findings aren't actionable resources | §13 resource-level `Finding` |
| 5 | No persistence | No history, trends, or savings tracking | §13 data model |
| 6 | No auth / tenancy | Single user only, shared `uploads/` dir | §16 |
| 7 | Server-side matplotlib PNGs | Heavy responses, no interactivity | JSON API + client charts |
| 8 | `print()` logging, no tests | Hard to operate and change safely | §18 CI |

---

# Part B — Target product architecture

## 9. Target system context

```mermaid
flowchart LR
    owner([Org owner / FinOps lead])
    eng([Engineer / analyst])
    aws[(AWS CUR 2.0 /<br/>FOCUS export in S3)]
    az[(Azure FOCUS export)]
    gcp[(GCP BigQuery<br/>billing export)]
    product["Autonomous-FinOps SaaS"]
    slack([Slack / Email])
    stripe([Stripe])
    sso([Google / GitHub OAuth])

    owner & eng -- web UI / API --> product
    product -- read-only cross-account role --> aws
    product -- read-only access --> az & gcp
    product -- alerts --> slack
    product -- billing --> stripe
    product -- sign-in --> sso
```

## 10. Target containers

```mermaid
flowchart TB
    browser["Browser<br/>Jinja + HTMX + Chart.js"]

    subgraph platform ["Autonomous-FinOps platform"]
        web["Web/API service<br/>Flask app factory · Gunicorn"]
        worker["Analysis worker<br/>RQ/Celery · finops_core · TensorFlow"]
        sched["Scheduler<br/>daily ingest + analyse per org"]
        queue[("Redis<br/>job queue + cache")]
        db[("PostgreSQL<br/>orgs, users, datasets,<br/>analyses, findings, forecasts")]
        store[("Object storage S3<br/>raw files · model artifacts")]
    end

    browser -- HTTPS --> web
    web -- enqueue jobs --> queue
    sched -- enqueue jobs --> queue
    queue --> worker
    web <--> db
    worker <--> db
    web -- presigned upload --> store
    worker <--> store
    worker -- assume role, read exports --> cloud[(Customer billing exports)]
    worker -- notify --> alerts([Slack / Email])
```

| Container | Scales by | Notes |
|---|---|---|
| Web/API | request rate | Stateless; no ML imports, so a small image |
| Worker | queue depth | Heavy image with pandas/sklearn/TensorFlow; concurrency limited per org |
| Scheduler | single instance | Could be EventBridge Scheduler on AWS instead of a process |
| PostgreSQL | vertical, read replica later | Every table carries `org_id` |
| Redis | small | Queue and short-lived caches only, not a source of truth |
| S3 | — | Keys prefixed `org/{org_id}/…`, SSE encryption, lifecycle rules |

## 11. Code layering

Dependencies point **inwards only**. `finops_core` knows nothing about Flask, the DB or S3.

```mermaid
flowchart TB
    subgraph app ["finops_app — delivery"]
        bp["Blueprints<br/>auth · datasets · analyses · api"]
        tasks["tasks.py<br/>worker jobs"]
        repo["Repositories<br/>SQLAlchemy, org-scoped"]
        storage["Storage adapter<br/>local / S3"]
        conn["Connectors<br/>aws · azure · gcp"]
    end

    subgraph core ["finops_core — pure domain"]
        schema["schema.py<br/>FOCUS contract"]
        ingest["ingest.py"]
        features["features.py"]
        detection["detection.py<br/>rules + ensemble"]
        forecasting["forecasting.py<br/>baseline + LSTM"]
        recs["recommendations.py"]
        models["models.py<br/>frozen dataclasses"]
    end

    bp --> repo & storage
    bp --> tasks
    tasks --> repo & storage & conn
    tasks --> ingest
    ingest --> schema --> models
    ingest --> features --> detection & forecasting
    detection & forecasting --> recs
    detection & forecasting & recs --> models
```

Where today's code goes:

| Today | Target |
|---|---|
| `DataPreprocessor._process_dates / _clean_numeric_columns` | `finops_core/ingest.py` + `schema.py` |
| `DataPreprocessor._engineer_features` | `finops_core/features.py` |
| `OptimizedZombieDetector` | `finops_core/detection.py` (plus new rule-based detectors) |
| `AdvancedForecaster` | `finops_core/forecasting.py` (behind a `Forecaster` protocol, with a naive baseline) |
| `generate_recommendations` | `finops_core/recommendations.py` |
| `generate_plots` | removed; the API returns JSON and charts render in the browser |
| fallback ML in `interface.py` | deleted |
| routes in `interface.py` | `finops_app/*` blueprints |

## 12. Async analysis flow

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant W as Web/API
    participant S as S3
    participant DB as Postgres
    participant Q as Redis queue
    participant K as Worker
    participant C as finops_core

    U->>W: Request upload URL
    W->>DB: insert Dataset(status=pending)
    W-->>U: presigned S3 URL + dataset_id
    U->>S: PUT CSV directly
    U->>W: POST /datasets/{id}/complete
    W->>DB: insert Analysis(status=queued)
    W->>Q: enqueue analyse(analysis_id)
    W-->>U: 202 Accepted + analysis_id

    loop poll every few seconds (HTMX)
        U->>W: GET /analyses/{id}/status
        W->>DB: read status
        W-->>U: queued / running / done / failed
    end

    Q->>K: deliver job
    K->>DB: status = running
    K->>S: stream file
    K->>C: validate schema → features
    C-->>K: typed frame or ValidationError
    K->>C: detect (rules + ensemble, per resource)
    K->>C: forecast (load model or baseline)
    C-->>K: AnalysisResult (findings, forecast, metrics)
    K->>DB: bulk insert Findings + ForecastPoints, status = done
    K-->>U: (optional) Slack/email if new High findings
```

Failure handling: the worker catches exceptions, stores a user-safe message on `Analysis.error`, logs full context, and retries transient errors (S3/DB) with backoff. Validation errors are not retried.

## 13. Data model

```mermaid
erDiagram
    ORGANIZATION ||--o{ MEMBERSHIP : has
    USER ||--o{ MEMBERSHIP : has
    ORGANIZATION ||--o{ CLOUD_CONNECTION : configures
    ORGANIZATION ||--o{ DATASET : owns
    CLOUD_CONNECTION ||--o{ DATASET : produces
    DATASET ||--o{ ANALYSIS : analysed_by
    ANALYSIS ||--o{ FINDING : yields
    ANALYSIS ||--o{ FORECAST_POINT : yields
    FINDING ||--o{ FINDING_EVENT : history
    USER ||--o{ FINDING_EVENT : acts
    ORGANIZATION ||--o{ BUDGET : sets
    ORGANIZATION ||--o{ AUDIT_LOG : records

    ORGANIZATION {
        uuid id PK
        string name
        string plan
        timestamp created_at
    }
    USER {
        uuid id PK
        string email UK
        string password_hash
        timestamp last_login_at
    }
    MEMBERSHIP {
        uuid org_id FK
        uuid user_id FK
        string role "owner, admin, analyst, viewer"
    }
    CLOUD_CONNECTION {
        uuid id PK
        uuid org_id FK
        string provider "aws, azure, gcp"
        string role_arn
        string external_id
        string export_location
        string status
    }
    DATASET {
        uuid id PK
        uuid org_id FK
        uuid connection_id FK "null for manual upload"
        string storage_key
        date period_start
        date period_end
        int row_count
        string status
    }
    ANALYSIS {
        uuid id PK
        uuid org_id FK
        uuid dataset_id FK
        string status "queued, running, done, failed"
        string model_version
        json metrics
        string error
        timestamp started_at
        timestamp finished_at
    }
    FINDING {
        uuid id PK
        uuid org_id FK
        uuid analysis_id FK
        string resource_id
        string service
        string region
        string account_id
        string detector "rule name or ml ensemble"
        decimal est_monthly_waste
        string confidence "high, medium, low"
        string reason
        string status
    }
    FINDING_EVENT {
        uuid id PK
        uuid finding_id FK
        uuid user_id FK
        string from_status
        string to_status
        string note
        timestamp at
    }
    FORECAST_POINT {
        uuid analysis_id FK
        date day
        decimal bau
        decimal optimised
        decimal lower
        decimal upper
    }
    BUDGET {
        uuid id PK
        uuid org_id FK
        string scope "account, tag, service"
        string scope_value
        decimal monthly_amount
    }
    AUDIT_LOG {
        uuid id PK
        uuid org_id FK
        uuid user_id FK
        string action
        json details
        timestamp at
    }
```

Findings are de-duplicated across analyses by `(org_id, resource_id, detector)` so a resource that stays idle shows as one open finding with history, not a new row every day.

## 14. Finding lifecycle

```mermaid
stateDiagram-v2
    [*] --> Open: detected
    Open --> Acknowledged: user triages
    Open --> FalsePositive: user rejects
    Open --> Snoozed: snooze N days
    Acknowledged --> Fixed: user marks fixed
    Acknowledged --> Snoozed: snooze N days
    Snoozed --> Open: snooze expires and still detected
    Fixed --> Verified: later data shows spend dropped
    Fixed --> Open: still detected after grace period
    FalsePositive --> [*]: stored as label for model tuning
    Verified --> [*]: counted in realised savings
```

## 15. Cloud connectors

AWS is first. The customer creates a read-only role; we never store their access keys.

```mermaid
sequenceDiagram
    autonumber
    actor A as Customer admin
    participant UI as Web UI
    participant CF as Customer AWS account
    participant K as Worker
    participant STS as AWS STS
    participant S3 as Customer S3 (CUR/FOCUS export)

    A->>UI: Connect AWS
    UI-->>A: CloudFormation quick-create link<br/>(role + external_id + read-only S3 policy)
    A->>CF: Launch stack
    CF-->>A: Role ARN
    A->>UI: Paste Role ARN
    UI->>K: verify connection job
    K->>STS: AssumeRole(role_arn, external_id)
    STS-->>K: temp credentials (1h)
    K->>S3: List / Get latest export
    K-->>UI: connection OK

    Note over K,S3: Daily: scheduler → AssumeRole → fetch new<br/>partitions → Dataset → Analysis (same flow as §12)
```

## 16. Multi-tenancy & security

```mermaid
flowchart LR
    req["HTTP request"] --> tls["TLS (ALB)"]
    tls --> rate["Rate limit<br/>Flask-Limiter"]
    rate --> authn["Session / OAuth<br/>Flask-Login"]
    authn --> csrf["CSRF check<br/>(form POSTs)"]
    csrf --> authz["Role check<br/>owner / admin / analyst / viewer"]
    authz --> scope["org_id scoping<br/>in repository layer"]
    scope --> db[(Postgres)]
    scope --> s3[("S3 org/{org_id}/…")]
```

Rules:
- `org_id` comes from the session, never from request parameters.
- Every repository method requires `org_id`; there is no unscoped query helper.
- Uploaded files: size cap, `.csv`/`.csv.gz` only, sniffed content, row cap per plan, parsed only in the worker.
- Secrets (`FINOPS_SECRET_KEY`, DB URL, Stripe keys) come from env / AWS Secrets Manager; the app refuses to start in prod without them.
- Security headers via Flask-Talisman (CSP, HSTS); no server-built HTML passed through `|safe`.
- Audit log for logins, role changes, connection changes and finding status changes.

## 17. Deployment on AWS

```mermaid
flowchart TB
    users([Users]) --> cf["CloudFront + WAF"]
    cf --> alb

    subgraph vpc ["VPC"]
        subgraph public ["Public subnets"]
            alb["Application Load Balancer"]
            nat["NAT gateway"]
        end
        subgraph private ["Private subnets"]
            web["ECS Fargate<br/>web service (2+ tasks)"]
            worker["ECS Fargate<br/>worker service (autoscale on queue)"]
            rds[("RDS PostgreSQL<br/>Multi-AZ")]
            redis[("ElastiCache Redis")]
        end
    end

    alb --> web
    web --> rds & redis
    worker --> rds & redis
    web & worker --> s3[("S3 buckets<br/>uploads · artifacts")]
    worker --> nat --> ext["Customer AWS (STS/S3)<br/>Slack · email"]
    sched["EventBridge Scheduler"] --> worker
    sm["Secrets Manager"] -.-> web & worker
    logs["CloudWatch Logs + Sentry"] -.-> web & worker
```

For early users a cheaper single-region setup also works: one small Fargate service per role, a db.t4g Postgres, and no CloudFront. Fly.io/Render with managed Postgres + Redis is the low-ops alternative.

## 18. CI/CD

```mermaid
flowchart LR
    pr["Pull request"] --> lint["ruff · black --check · isort · mypy"]
    lint --> sec["bandit · pip-audit"]
    sec --> test["pytest unit + integration<br/>coverage ≥ 80%"]
    test --> e2e["Playwright e2e<br/>(docker-compose stack)"]
    e2e --> merge{"merge to main"}
    merge --> build["Build web + worker images<br/>push to ECR"]
    build --> stg["Deploy to staging<br/>run migrations · smoke tests"]
    stg --> gate{"Manual approval"}
    gate --> prod["Deploy to prod<br/>rolling, auto-rollback on health check"]
```

## 19. Migration path

How version-5 gets from Part A to Part B without a big-bang rewrite. Each step keeps the app runnable.

```mermaid
flowchart LR
    s0["Step 0<br/>golden-file test on<br/>focus_sample.csv"] --> s1["Step 1<br/>delete fallback ML<br/>from interface.py"]
    s1 --> s2["Step 2<br/>split ml.py →<br/>finops_core"]
    s2 --> s3["Step 3<br/>app factory +<br/>blueprints"]
    s3 --> s4["Step 4<br/>Postgres + worker<br/>(async uploads)"]
    s4 --> s5["Step 5<br/>auth + orgs"]
    s5 --> s6["Step 6<br/>resource-level findings<br/>+ JSON API + charts"]
    s6 --> s7["Step 7<br/>AWS connector<br/>+ scheduler + alerts"]
    s7 --> s8["Step 8<br/>containerise +<br/>deploy"]
```

Mapping to the plan: steps 0–1 are Phase 0, step 2 is Phase 1, steps 3–4 are Phase 2, step 5 is Phase 3, step 6 is Phases 1 and 4, step 7 is Phase 5, and step 8 is Phase 6 in [PRODUCT_PLAN.md](PRODUCT_PLAN.md).
