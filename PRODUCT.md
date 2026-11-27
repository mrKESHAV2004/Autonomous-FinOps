# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Engineering Leads, DevOps Engineers, and FinOps practitioners managing $5k–$500k/month in cloud infrastructure who need to systematically discover waste, triage zombie resources, and forecast future run-rates without a dedicated FinOps team.

## Product Purpose
Autonomous-FinOps ingests standardized multi-cloud billing exports (FOCUS specification), detects zombie and idle resources using ML and peer-median heuristics, projects future spending trajectories (BAU vs. Optimized), and provides a high-density triage workflow to track realised savings.

## Positioning
Evaluates cloud spend at the individual *resource* level rather than aggregate billing rows. Combines statistical run-rate forecasting with resource-level peer median waste heuristics and IsolationForest anomaly scoring, built as a precision engineering tool rather than a generic accounting report.

## Operating Context
Used in sprint planning, cloud cost triage standups, and monthly infrastructure budget reviews. Consumes FOCUS-compliant CSV exports and direct cloud connector feeds (AWS CUR).

## Capabilities and Constraints
- Ingestion and schema validation of FOCUS 1.0 datasets (up to hundreds of thousands of rows).
- Multi-dimensional waste detection (idle compute, unattached storage, peer pricing outliers).
- Run-rate forecasting showing Business-As-Usual (BAU) vs. Optimized spend curves.
- Finding triage states: Open, Snoozed (with return date), Resolved, Ignored with audit trail.
- Read-only recommendations; direct cloud modifications remain gated by human approval.
- Pure dark-mode engineering console designed for fast scanning and high data density.

## Brand Commitments
Precision, restraint, and operational clarity. Dark slate palette (`slate-950`), emerald savings accents (`emerald-400`), amber warnings (`amber-400`), and tabular monospaced numbers (`font-mono`). Inspired by modern developer tools like Linear, Datadog, and Grafana.

## Evidence on Hand
- Real FOCUS datasets: `focus_sample_10000.csv`, `focus_sample.csv`, and `version-5/sample_cloud_data.csv`.
- Working machine learning and statistical detection models in `version-5/src/finops_core`.

## Product Principles
1. **Resource Granularity:** Costs must always trace back to an identifiable resource ID and cloud provider service.
2. **Transparent Reasoning:** Every waste finding must state why it was flagged (e.g. "Cost is 2.8x peer median for t3.medium in us-east-1").
3. **High Density & Operator Velocity:** Dense data grids, clear visual hierarchy, zero gratuitous whitespace, and immediate feedback.
4. **Actionable Triage:** Every anomaly has an owner, a status, and a quantified dollar impact.
