"use client";

import { useState } from "react";
import { ConsoleHeader } from "@/components/layout/ConsoleHeader";
import { SpendForecastView } from "@/components/dashboard/SpendForecastChart";
import { FindingsTable } from "@/components/findings/FindingsTable";
import { BillingUploadView } from "@/components/ingestion/BillingUpload";

const SYSTEM_FACTS = [
  { term: "Pipeline", value: "Healthy" },
  { term: "Engine", value: "Python 3.12 / finops_core" },
  { term: "Worker", value: "RQ (Redis Connected)" },
  { term: "Detectors", value: "IsolationForest + LSTM" },
  { term: "Tenant", value: "default-org" },
  { term: "Schema", value: "FOCUS 1.0 Compliant" },
];

export default function FinOpsConsole() {
  const [activeTab, setActiveTab] = useState<string>("overview");
  const [activeDataset, setActiveDataset] = useState<string>("sample_cloud_data.csv");

  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink">
      <ConsoleHeader
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        activeDatasetName={activeDataset}
        totalFindingsCount={42}
      />

      <main className="mx-auto w-full max-w-[1440px] flex-1 px-6 pt-8 pb-16">
        {activeTab === "overview" && <SpendForecastView />}
        {activeTab === "findings" && <FindingsTable />}
        {activeTab === "ingestion" && (
          <BillingUploadView
            onDatasetLoaded={(filename) => {
              setActiveDataset(filename);
              // Auto-navigate to findings after brief pause
              setTimeout(() => setActiveTab("findings"), 1200);
            }}
          />
        )}
      </main>

      <footer className="border-t border-rule bg-paper-3">
        <dl className="mx-auto grid w-full max-w-[1440px] grid-cols-2 gap-x-8 gap-y-3 px-6 py-4 text-xs sm:grid-cols-3 lg:grid-cols-6">
          {SYSTEM_FACTS.map((fact) => (
            <div key={fact.term} className="min-w-0">
              <dt className="text-muted">{fact.term}</dt>
              <dd className="m-0 truncate text-ink-2">{fact.value}</dd>
            </div>
          ))}
        </dl>
      </footer>
    </div>
  );
}
