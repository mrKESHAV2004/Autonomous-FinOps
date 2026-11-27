"use client";

import { useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

// Realistic demonstration data mirroring finops_core statistical forecast
const HISTORY = [
  { date: "Nov 01", actual: 8400, baseline: 8400, optimized: 8400 },
  { date: "Nov 05", actual: 8650, baseline: 8650, optimized: 8650 },
  { date: "Nov 10", actual: 9100, baseline: 9100, optimized: 9100 },
  { date: "Nov 15", actual: 9350, baseline: 9350, optimized: 9350 },
  { date: "Nov 20", actual: 9800, baseline: 9800, optimized: 9800 },
  { date: "Nov 25", actual: 9620, baseline: 9620, optimized: 9620 },
  { date: "Nov 27", actual: 9940, baseline: 9940, optimized: 9940 }, // Today
];

type Timeframe = "30d" | "60d" | "90d";

const HORIZON_DAYS: Record<Timeframe, number> = { "30d": 30, "60d": 60, "90d": 90 };
const TODAY_UTC = Date.UTC(2026, 10, 27);
const DAY_MS = 86_400_000;
const FORECAST_STEP_DAYS = 5;
// Sample trend: BAU keeps its recent slope; the optimized run-rate drops as waste is removed, then drifts down slowly.
const BAU_SLOPE_PER_DAY = 46;
const OPTIMIZED_FLOOR = 8300;
const OPTIMIZED_DECAY_DAYS = 2.5;
const OPTIMIZED_DRIFT_PER_DAY = 3;

const dateLabel = (daysFromToday: number) =>
  new Date(TODAY_UTC + daysFromToday * DAY_MS).toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    timeZone: "UTC",
  });

function forecastSeries(timeframe: Timeframe) {
  const horizon = HORIZON_DAYS[timeframe];
  const start = HISTORY[HISTORY.length - 1].baseline;
  const points = [];
  for (let d = FORECAST_STEP_DAYS; d <= horizon; d += FORECAST_STEP_DAYS) {
    points.push({
      date: dateLabel(d),
      baseline: Math.round(start + BAU_SLOPE_PER_DAY * d),
      optimized: Math.round(
        OPTIMIZED_FLOOR + (start - OPTIMIZED_FLOOR) * Math.exp(-d / OPTIMIZED_DECAY_DAYS) - OPTIMIZED_DRIFT_PER_DAY * d,
      ),
    });
  }
  return [...HISTORY, ...points];
}

const TODAY = "Nov 27";

const SERVICE_BREAKDOWN = [
  { service: "AmazonEC2", waste: 18450, share: "48.0%", count: 18 },
  { service: "AmazonRDS", waste: 9820, share: "25.6%", count: 7 },
  { service: "AmazonEBS", waste: 5410, share: "14.1%", count: 12 },
  { service: "NatGateway", waste: 3120, share: "8.1%", count: 3 },
  { service: "AmazonS3", waste: 1610, share: "4.2%", count: 2 },
];

const MAX_SERVICE_WASTE = Math.max(...SERVICE_BREAKDOWN.map((s) => s.waste));

const SERIES = [
  { key: "actual", name: "Actual Spend", swatch: "text-ink-2", dashed: false },
  { key: "baseline", name: "BAU Baseline (Unoptimized)", swatch: "text-muted", dashed: true },
  { key: "optimized", name: "Optimized Run-rate", swatch: "text-accent", dashed: false },
] as const;

const SERIES_NAMES: Record<string, string> = Object.fromEntries(SERIES.map((s) => [s.key, s.name]));

function Swatch({ tone, dashed }: { tone: string; dashed?: boolean }) {
  return <span aria-hidden="true" className={`swatch ${dashed ? "swatch--dashed" : ""} ${tone}`} />;
}

export function SpendForecastView() {
  const [timeframe, setTimeframe] = useState<Timeframe>("30d");
  const series = forecastSeries(timeframe);
  const last = series[series.length - 1];

  return (
    <div className="flex flex-col gap-6">
      {/* The reading: what the detectors flagged, set large; the run-rates beside it. */}
      <section aria-labelledby="waste-reading" className="panels lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="flex flex-col justify-between gap-8 p-6 lg:p-8">
          <h2 id="waste-reading" className="text-sm font-medium tracking-normal text-muted">
            Zombie / idle waste
          </h2>
          <p className="flex items-baseline gap-2">
            <span className="measured text-reading leading-none tracking-tight text-ink">$38,410</span>
            <span className="text-md text-muted">/mo</span>
          </p>
          <dl className="grid grid-cols-2 gap-4 border-t border-rule pt-4 text-sm">
            <div>
              <dt className="text-muted">Share of monitored spend</dt>
              <dd className="measured m-0 mt-1 text-ink-2">13.5%</dd>
            </div>
            <div>
              <dt className="text-muted">Flagged cloud resources</dt>
              <dd className="measured m-0 mt-1 text-ink-2">42</dd>
            </div>
          </dl>
        </div>

        <dl className="m-0 grid divide-y divide-rule">
          <div className="grid gap-1 px-6 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-baseline sm:gap-x-6 sm:gap-y-1">
            <dt className="text-sm text-muted">Total monitored spend</dt>
            <dd className="measured m-0 text-xl text-ink sm:text-right">$284,520</dd>
            <dd className="m-0 text-sm text-muted sm:col-span-2">Last 30 days active billed</dd>
          </div>
          <div className="grid gap-1 px-6 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-baseline sm:gap-x-6 sm:gap-y-1">
            <dt className="flex items-center gap-2 text-sm text-muted">
              <Swatch tone="text-muted" dashed />
              BAU run-rate forecast
            </dt>
            <dd className="measured m-0 text-xl text-ink sm:text-right">$312,800</dd>
            <dd className="m-0 text-sm text-muted sm:col-span-2">
              <span className="measured text-ink-2">+9.9%</span> trend without fixes
            </dd>
          </div>
          <div className="grid gap-1 px-6 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-baseline sm:gap-x-6 sm:gap-y-1">
            <dt className="flex items-center gap-2 text-sm text-muted">
              <Swatch tone="text-accent" />
              Optimized run-rate
            </dt>
            <dd className="measured m-0 text-xl text-ink sm:text-right">$274,390</dd>
            <dd className="m-0 text-sm text-muted sm:col-span-2">
              <span className="measured text-ink-2">-26.8%</span>, save{" "}
              <span className="measured text-ink-2">$460,920</span> annualized
            </dd>
          </div>
        </dl>
      </section>

      {/* The forecast. */}
      <section aria-labelledby="forecast-heading" className="panel flex flex-col gap-6 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <h2 id="forecast-heading" className="text-lg">
              Spend trajectory & forecast horizon
            </h2>
            <p className="max-w-[60ch] text-sm text-muted">
              Historical actual billing compared against statistical baseline and post-triage optimized trajectories.
            </p>
          </div>

          <div className="seg" role="group" aria-label="Forecast horizon">
            {(["30d", "60d", "90d"] as const).map((t) => (
              <button
                key={t}
                type="button"
                aria-pressed={timeframe === t}
                onClick={() => setTimeframe(t)}
                className="measured"
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <ul className="m-0 flex list-none flex-wrap gap-x-6 gap-y-2 p-0 text-sm text-ink-2">
          {SERIES.map((s) => (
            <li key={s.key} className="flex items-center gap-2">
              <Swatch tone={s.swatch} dashed={s.dashed} />
              {s.name}
            </li>
          ))}
        </ul>

        <div
          className="forecast-chart h-80 w-full"
          role="img"
          aria-label={`Line chart of actual spend through ${TODAY}, then the BAU baseline rising to $${last.baseline.toLocaleString()} and the optimized run-rate falling to $${last.optimized.toLocaleString()} by ${last.date}.`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="currentColor" vertical={false} />
              <XAxis dataKey="date" stroke="currentColor" tickLine={false} axisLine tickMargin={8} />
              <YAxis
                stroke="currentColor"
                tickLine={false}
                axisLine={false}
                width={64}
                tickFormatter={(val: number) => `$${val.toLocaleString()}`}
              />
              <ReferenceLine x={TODAY} stroke="currentColor" label={{ value: "Today", position: "insideTopRight" }} />
              <Tooltip
                cursor={{ stroke: "currentColor" }}
                content={({ active, payload, label }) => {
                  if (!active || !payload || payload.length === 0) return null;
                  return (
                    <div className="panel flex min-w-56 flex-col gap-1 bg-paper-3 p-3 text-xs">
                      <div className="measured text-muted">{label}</div>
                      {payload.map((entry) => (
                        <div key={String(entry.dataKey)} className="flex items-center justify-between gap-4">
                          <span className="text-ink-2">{SERIES_NAMES[String(entry.dataKey)]}</span>
                          <span className="measured text-ink">${Number(entry.value).toLocaleString()}</span>
                        </div>
                      ))}
                    </div>
                  );
                }}
              />
              <Line
                className="series-baseline"
                type="monotone"
                dataKey="baseline"
                name="BAU Baseline (Unoptimized)"
                stroke="currentColor"
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
              />
              <Line
                className="series-optimized"
                type="monotone"
                dataKey="optimized"
                name="Optimized Run-rate"
                stroke="currentColor"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                className="series-actual"
                type="monotone"
                dataKey="actual"
                name="Actual Spend"
                stroke="currentColor"
                strokeWidth={2}
                dot={{ r: 3 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* Waste by service: five values compared, as horizontal bars in a table. */}
      <section aria-labelledby="service-heading" className="panel overflow-hidden">
        <h2 id="service-heading" className="max-w-none px-6 pt-6 pb-4 text-lg">
          Identified waste breakdown by cloud service
        </h2>
        <div className="overflow-x-auto">
          <table className="queue queue--static">
            <thead>
              <tr>
                <th scope="col">Service</th>
                <th scope="col" className="num">Findings</th>
                <th scope="col" className="num">Waste ($/mo)</th>
                <th scope="col" className="num">Share</th>
                <th scope="col" className="w-[40%]">
                  <span className="visually-hidden">Relative waste</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {SERVICE_BREAKDOWN.map((item) => (
                <tr key={item.service}>
                  <td className="text-ink">{item.service}</td>
                  <td className="num measured text-ink-2">{item.count}</td>
                  <td className="num measured text-ink">${item.waste.toLocaleString()}</td>
                  <td className="num measured text-ink-2">{item.share}</td>
                  <td>
                    <div className="bar-track" aria-hidden="true">
                      <div className="bar-fill" style={{ width: `${(item.waste / MAX_SERVICE_WASTE) * 100}%` }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
