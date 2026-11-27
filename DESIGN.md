# Design System — Autonomous-FinOps Console

<!-- impeccable:design-schema 1 -->

## Direction
**The Precision FinOps Console** — A high-density, dark-mode engineering environment inspired by Linear, Datadog, and Grafana. Built for engineers and DevOps practitioners who demand instant data comprehension, zero gratuitous whitespace, and frictionless keyboard-friendly triage.

## Mode
**Operate** — The user is on a working screen to complete urgent financial operations tasks: diagnosing cloud spend anomalies, triaging zombie resources, evaluating forecasts, and ingesting billing data. Scanability, native expectations, and high information density take absolute priority over decorative flair.

## Ground & Palette
* **Canvas Ground:** `slate-950` (`#020617`) — deep, neutral dark base that eliminates eye strain during lengthy audit sessions.
* **Elevated Panels / Shells:** `slate-900` (`#0f172a`) with subtle `slate-800/80` (`#1e293b`) borders.
* **Muted / Inactive Surfaces:** `slate-900/50` with `slate-800/40` dividers.
* **Text Hierarchy:**
  * Primary: `slate-100` (`#f1f5f9`) — high contrast (≥12:1 against canvas).
  * Secondary / Meta: `slate-400` (`#94a3b8`) — crisp legibility (≥4.5:1 contrast).
  * Muted / Captions: `slate-500` (`#64748b`).
* **Semantic Accents:**
  * **Optimized / Realised Savings:** `emerald-400` (`#34d399`) foreground with `emerald-950/40` pills and `emerald-500/20` borders.
  * **Critical Waste / High Confidence:** `rose-400` (`#fb7185`) with `rose-950/40` backgrounds.
  * **Warning / Moderate Anomaly:** `amber-400` (`#fbbf24`) with `amber-950/40` backgrounds.
  * **Cloud Services / Ingestion:** `cyan-400` (`#22d3ee`) for AWS / cloud telemetry.

## Typography
* **UI Interface Face:** Geist Sans / Inter — clean geometric sans for navigation, filter labels, and buttons.
* **Financial & Data Face:** Geist Mono / JetBrains Mono (`font-mono tabular-nums`) — mandatory for all currency values (`$1,420.50`), percentages (`-28.4%`), Resource IDs, ARNs, and ISO timestamps. No variable-width numerals in tables or charts.
* **Scale & Hierarchy:**
  * Display KPI: `text-2xl font-bold tracking-tight font-mono`
  * Section Headers: `text-base font-semibold text-slate-100`
  * Table Cells / Body: `text-xs font-normal text-slate-300`
  * Micro / Badges: `text-[11px] font-medium tracking-wide`

## Layout & Spatial System
* **Grid Density:** Compact 4px grid (`gap-1.5`, `p-3`, `px-4 py-2`).
* **Shell Anatomy:**
  1. **Global Header (h-14):** Product wordmark, Organization / Tenant switcher, Active Dataset indicator, and status badge.
  2. **Subnav / Surface Tabs (h-11):** Direct access between `Spend & Forecast`, `Findings & Zombie Triage`, and `Billing Ingestion`.
  3. **Main Canvas:** Full-width responsive workspace with minimal horizontal margin constraints.
* **Table & Data Density:**
  * 36px table row height for maximum viewport information density.
  * Explicit column widths with text truncation and tooltip on hover for long AWS ARNs/Resource IDs.
  * Direct action buttons inside rows (`Snooze`, `Resolve`) that do not require entering secondary pages.

## Interaction & State Discipline
* **Zero Fluff:** No gradient text, no gratuitous glass blur, no decorative floating cards.
* **States:** Full coverage for Loading (monochrome pulse skeleton), Empty (helpful diagnostic prompt with upload shortcut), Error (structured recovery message), and Active selection.
* **Keyboard Navigation:** Tabular focus rings (`focus-visible:ring-1 focus-visible:ring-emerald-500 focus-visible:outline-none`).
* **Browser Surfaces:** Styled scrollbars (`scrollbar-thin scrollbar-thumb-slate-800`), custom selection (`selection:bg-emerald-500/20 selection:text-emerald-200`).
