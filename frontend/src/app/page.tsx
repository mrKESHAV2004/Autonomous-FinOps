import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ForecastPanel } from "@/components/dashboard/SpendForecastChart";
import "./landing.css";

export const metadata: Metadata = {
  title: "Autonomous-FinOps: cloud waste, traced to the resource",
  description:
    "Reads FOCUS billing exports, flags idle and overpriced cloud resources with the reason, and forecasts spend with and without the waste.",
};

const REPO_URL = "https://github.com/mrKESHAV2004/Autonomous-FinOps";

const SIGNALS = [
  {
    id: "idle",
    title: "Idle",
    body: "Zero usage across the billing period. The whole cost counts as waste.",
  },
  {
    id: "overpriced",
    title: "Overpriced",
    body: "At least 3× the peer median cost per unit for the same service and unit, with a modified z-score of 3.5 or more. Only the cost above the median counts.",
  },
  {
    id: "ml_outlier",
    title: "Unusual",
    body: "An ensemble of Isolation Forests marks rows outside the usual pattern. It supports a finding and never makes one alone.",
  },
];

const DECISIONS = [
  { title: "Snoozed", body: "Hidden until a date you pick, up to 365 days, then reopened." },
  { title: "Resolved", body: "Checked against the next upload. Still flagged means still wasting." },
  { title: "Ignored", body: "Kept as a false positive with your note, carried to the next upload." },
  { title: "Every change", body: "Recorded with who, when and the note, in the audit log." },
];

const SOURCES = [
  { source: "FOCUS 1.0 CSV", how: "Upload in the browser, checked against the schema first", status: "Available" },
  { source: "AWS CUR 2.0 or FOCUS export", how: "A read-only cross-account IAM role on your S3 bucket; no keys stored", status: "Available" },
  { source: "Azure Cost Management FOCUS export", how: "Connector", status: "Stub" },
  { source: "GCP BigQuery billing export", how: "Connector", status: "Stub" },
];

export default function Landing() {
  return (
    <div className="site">
      <header className="slab">
        <nav className="container" aria-label="Main">
          <Link href="/" className="wordmark" aria-label="Autonomous-FinOps home">
            Autonomous-FinOps
          </Link>
          <ul className="slab-links">
            <li><a href="#why">Why it flags</a></li>
            <li><a href="#forecast">Forecast</a></li>
            <li><a href="#sources">Sources</a></li>
          </ul>
          <div className="slab-actions">
            <a href={REPO_URL} className="btn btn--nav btn--github" target="_blank" rel="noopener noreferrer">
              GitHub
            </a>
            <Link href="/console" className="btn btn--nav btn--primary">
              Open the console
            </Link>
          </div>
        </nav>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-head">
          <div className="container">
            <div>
              <h1 id="hero-head">Cloud waste, traced to the resource.</h1>
              <p className="lead">Flags each idle resource in your FOCUS billing export, and says why.</p>
              <div className="actions">
                <Link href="/console" className="btn btn--primary">
                  Open the console
                </Link>
                <a href={REPO_URL} className="btn" target="_blank" rel="noopener noreferrer">
                  Source on GitHub
                </a>
              </div>
              <p className="wip">
                A project in progress: the console runs on sample data, and the Azure and GCP connectors are still stubs.
              </p>
            </div>
            <figure className="capture capture--hero">
              <Image
                src="/screens/triage.png"
                width={2880}
                height={2256}
                sizes="(min-width: 60rem) 60vw, 100vw"
                priority
                alt="The findings queue with one EC2 instance open: $1,420.50 flagged, $184.50 peer median, and the three reasons it was flagged."
              />
            </figure>
          </div>
        </section>

        <section id="why" className="section section--tall" aria-labelledby="why-head">
          <div className="container grid-12 pinned">
            <figure className="pinned-figure">
              <div className="capture capture--record">
                <Image
                  src="/screens/record.png"
                  width={768}
                  height={1960}
                  sizes="(min-width: 60rem) 36vw, 100vw"
                  alt="One finding's record: the flagged waste, actual and peer median cost, the reasons, and the signals that fired."
                />
              </div>
              <figcaption className="caption">One finding, from the console. Sample data.</figcaption>
            </figure>
            <div className="pinned-body">
              <div className="head">
                <h2 id="why-head">Every finding says why</h2>
                <p className="lead">Three signals, each with its own rule. The reason is written on the record.</p>
              </div>
              <ol className="signals">
                {SIGNALS.map((s) => (
                  <li key={s.id}>
                    <span className="signal-id">{s.id}</span>
                    <h3>{s.title}</h3>
                    <p>{s.body}</p>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </section>

        <section id="forecast" className="section band-quiet" aria-labelledby="forecast-head">
          <div className="container grid-12">
            <div className="showcase-head">
              <h2 id="forecast-head">Two forecasts, one decision</h2>
              <p className="lead">
                The run-rate if nothing changes, beside the run-rate once the flagged waste is gone.
              </p>
            </div>
            <figure className="showcase-figure">
              <ForecastPanel headingId="landing-forecast-heading" headingLevel="h3" />
              <figcaption className="caption">
                The baseline is a 7-day moving average or a weekly-seasonal model, whichever backtests better on the last week. Sample data.
              </figcaption>
            </figure>
          </div>
        </section>

        <section className="section section--tall" aria-labelledby="decisions-head">
          <div className="container grid-12">
            <div className="head">
              <h2 id="decisions-head">Decisions that carry over</h2>
              <p className="lead">A person decides what happens to each finding, and the decision outlives the upload.</p>
            </div>
            <ul className="rows">
              {DECISIONS.map((d) => (
                <li key={d.title}>
                  <h3>{d.title}</h3>
                  <p>{d.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="sources" className="section" aria-labelledby="sources-head">
          <div className="container grid-12">
            <div className="head">
              <h2 id="sources-head">Where the bills come from</h2>
            </div>
            <table className="spec">
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">How it connects</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {SOURCES.map((s) => (
                  <tr key={s.source}>
                    <td>{s.source}</td>
                    <td>{s.how}</td>
                    <td>
                      <span className={s.status === "Available" ? "chip chip--ok" : "chip chip--quiet"}>{s.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="spec-note">
              Runs with docker compose: the web app, a worker, PostgreSQL and Redis.
            </p>
          </div>
        </section>

        <section className="close" aria-labelledby="close-head">
          <div className="container">
            <div>
              <h2 id="close-head">See it on sample data</h2>
              <p className="lead">The console opens on a sample FOCUS export. Nothing to upload first.</p>
              <div className="actions">
                <Link href="/console" className="btn btn--primary">
                  Open the console
                </Link>
              </div>
            </div>
            <figure className="capture">
              <Image
                src="/screens/pipeline.png"
                width={2880}
                height={1468}
                sizes="(min-width: 60rem) 55vw, 100vw"
                alt="The ingestion screen mid-run: schema validation and persistence done, zombie detection executing, forecasting queued."
              />
            </figure>
          </div>
        </section>
      </main>

      <footer className="colophon">
        <div className="container">
          <p>
            Autonomous-FinOps reads FOCUS 1.0 billing exports, flags idle and overpriced resources with the reason, and
            forecasts spend with and without the waste. Recommendations are read-only: nothing in your cloud changes
            without a person.
          </p>
          <ul>
            <li><Link href="/console" className="text-link">Console</Link></li>
            <li><a href={REPO_URL} className="text-link" target="_blank" rel="noopener noreferrer">Source on GitHub</a></li>
          </ul>
        </div>
      </footer>
    </div>
  );
}
