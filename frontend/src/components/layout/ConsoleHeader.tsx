"use client";

import { Server } from "lucide-react";

interface ConsoleHeaderProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  activeDatasetName?: string;
  totalFindingsCount?: number;
}

export function ConsoleHeader({
  activeTab,
  setActiveTab,
  activeDatasetName = "sample_cloud_data.csv",
  totalFindingsCount = 42,
}: ConsoleHeaderProps) {
  const tabs = [
    { id: "overview", label: "Spend & Forecast" },
    { id: "findings", label: `Findings & Triage (${totalFindingsCount})` },
    { id: "ingestion", label: "Billing Ingestion" },
  ];

  return (
    <header className="sticky top-0 z-40 border-b border-rule bg-paper">
      <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center justify-between gap-6 px-6">
        <div className="flex min-w-0 items-center gap-8">
          <span className="font-display text-md font-medium tracking-tight text-ink whitespace-nowrap">
            Autonomous-FinOps
          </span>

          <dl className="hidden min-w-0 items-center gap-6 text-sm sm:flex">
            <div className="flex items-baseline gap-2">
              <dt className="text-muted">Org</dt>
              <dd className="m-0 text-ink-2">production-org</dd>
            </div>
            <div className="flex min-w-0 items-baseline gap-2">
              <dt className="text-muted">Dataset</dt>
              <dd className="measured m-0 truncate text-ink-2" title={activeDatasetName}>
                {activeDatasetName}
              </dd>
            </div>
          </dl>
        </div>

        <a
          href="http://localhost:5000"
          target="_blank"
          rel="noreferrer"
          className="btn"
          title="Open Flask Backend Engine on port 5000"
        >
          <Server className="h-3.5 w-3.5 text-cool" aria-hidden="true" />
          <span>Python API :5000</span>
        </a>
      </div>

      <div className="mx-auto w-full max-w-[1440px] overflow-x-auto px-3">
        <div role="tablist" aria-label="Console surfaces" className="flex h-11 items-stretch">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => setActiveTab(tab.id)}
                className="tab"
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>
    </header>
  );
}
