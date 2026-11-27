"use client";

import { useState } from "react";
import { UploadCloud, CheckCircle2, AlertCircle, RefreshCw, Check } from "lucide-react";

export function BillingUploadView({
  onDatasetLoaded,
}: {
  onDatasetLoaded?: (filename: string) => void;
}) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStep, setUploadStep] = useState<number>(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);

  const simulateProcessingPipeline = (filename: string) => {
    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
    setUploadStep(1); // Uploading & Sniffing

    setTimeout(() => {
      setUploadStep(2); // Ingestion & Tenant Scoping
    }, 900);

    setTimeout(() => {
      setUploadStep(3); // ML Zombie Detection Ensemble
    }, 1800);

    setTimeout(() => {
      setUploadStep(4); // Statistical Spend Forecasting
    }, 2800);

    setTimeout(() => {
      setUploadStep(5); // Succeeded
      setIsUploading(false);
      // The pipeline is simulated in the browser: say so rather than claim an upload happened.
      setUploadSuccess(`Demo run finished for ${filename}. No file was sent to the API; the findings shown are sample data.`);
      if (onDatasetLoaded) onDatasetLoaded(filename);
    }, 3800);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (!file.name.toLowerCase().endsWith(".csv")) {
        setUploadError("Only FOCUS-compliant CSV files are supported.");
        return;
      }
      setSelectedFile(file);
      simulateProcessingPipeline(file.name);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (!file.name.toLowerCase().endsWith(".csv")) {
        setUploadError("Only FOCUS-compliant CSV files are supported.");
        return;
      }
      setSelectedFile(file);
      simulateProcessingPipeline(file.name);
    }
  };

  const loadSampleDataset = () => {
    setSelectedFile(null);
    simulateProcessingPipeline("sample_cloud_data.csv (FOCUS 1.0 - 10,000 rows)");
  };

  const openFilePicker = () => {
    if (!isUploading) {
      document.getElementById("file-upload")?.click();
    }
  };

  const pipelineSteps = [
    { step: 1, label: "CSV Sniff & Schema Validation", detail: "Checking FOCUS 1.0 column contracts" },
    { step: 2, label: "Tenant Database Persistence", detail: "Writing raw records to PostgreSQL" },
    { step: 3, label: "Zombie Detection Ensemble", detail: "IsolationForest outlier & peer median waste" },
    { step: 4, label: "Spend Trajectory Forecasting", detail: "Statistical baseline & LSTM projection" },
    { step: 5, label: "Analysis Ready", detail: "42 Findings generated with confidence scores" },
  ];

  const pipelineStatus =
    uploadStep === 0 ? "Waiting for a file" : uploadStep === 5 ? "Status: Succeeded" : `Stage ${uploadStep}/4 Active`;

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
      {/* The upload. */}
      <section aria-labelledby="ingest-heading" className="panel flex flex-col gap-6 p-6 lg:p-8">
        <div className="flex flex-col gap-2">
          <h2 id="ingest-heading" className="text-xl">
            Billing Dataset Ingestion (FOCUS 1.0 Specification)
          </h2>
          <p className="max-w-[62ch] text-sm text-muted">
            Upload multi-cloud cost exports (AWS CUR, Azure Cost Management, GCP Billing) normalized to FinOps Open Cost &amp; Usage Specification.
          </p>
        </div>

        <div
          role="button"
          tabIndex={isUploading ? -1 : 0}
          aria-disabled={isUploading}
          aria-describedby="drop-help"
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => {
            if (!isUploading) {
              document.getElementById("file-upload")?.click();
            }
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              openFilePicker();
            }
          }}
          className={`flex min-h-56 flex-col items-center justify-center gap-3 rounded-card border border-dashed p-8 text-center transition-colors ${
            isUploading
              ? "cursor-progress border-cool bg-cool-soft/40"
              : "cursor-pointer border-rule-2 bg-paper-3 hover:border-muted"
          }`}
        >
          <input
            id="file-upload"
            type="file"
            accept=".csv"
            onChange={handleFileInput}
            className="hidden"
            disabled={isUploading}
          />
          {isUploading ? (
            <RefreshCw className="h-6 w-6 animate-spin text-cool motion-reduce:animate-none" aria-hidden="true" />
          ) : (
            <UploadCloud className="h-6 w-6 text-ink-2" aria-hidden="true" />
          )}
          <p className="text-md text-ink">
            {isUploading
              ? "Processing billing dataset through finops_core pipeline..."
              : "Drop FOCUS billing CSV file here, or click to browse"}
          </p>
          <p id="drop-help" className="text-sm text-muted">
            Accepts CSV up to 100MB. Sniffs required FOCUS columns:{" "}
            <code className="measured text-ink-2">BilledCost</code>, <code className="measured text-ink-2">ResourceId</code>,{" "}
            <code className="measured text-ink-2">ChargePeriodStart</code>
          </p>
          {selectedFile && (
            <p className="measured text-xs text-ink-2">{selectedFile.name}</p>
          )}
        </div>

        {uploadError && (
          <p role="alert" className="flex items-center gap-2 rounded-pill border border-bad/50 bg-bad-soft px-4 py-3 text-sm text-ink">
            <AlertCircle className="h-4 w-4 shrink-0 text-bad" aria-hidden="true" />
            {uploadError}
          </p>
        )}

        {uploadSuccess && (
          <p role="status" className="flex items-center gap-2 rounded-pill border border-ok/50 bg-ok-soft px-4 py-3 text-sm text-ink">
            <CheckCircle2 className="h-4 w-4 shrink-0 text-ok" aria-hidden="true" />
            {uploadSuccess}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-rule pt-6">
          <p className="text-sm text-muted">Need sample data to evaluate detection models?</p>
          <button type="button" onClick={loadSampleDataset} disabled={isUploading} className="btn btn--primary">
            Load Sample FOCUS Dataset
          </button>
        </div>
      </section>

      {/* The pipeline, as a trail. */}
      <section aria-labelledby="pipeline-heading" className="panel flex flex-col gap-6 p-6 lg:p-8">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="pipeline-heading" className="text-lg">
            Autonomous ingestion & ML pipeline
          </h2>
          <p role="status" className="measured text-xs text-cool">
            {pipelineStatus}
          </p>
        </div>

        <ol className="trail gap-6">
          {pipelineSteps.map((st) => {
            const isPast = uploadStep > st.step || uploadStep === 5;
            const isCurrent = uploadStep === st.step && uploadStep !== 5;
            const state = isPast ? "Done" : isCurrent ? "Executing..." : "Queued";
            return (
              <li key={st.step} className="flex items-start justify-between gap-4">
                <span
                  className={`trail-mark ${isPast ? "border-ok bg-ok-soft" : isCurrent ? "border-cool bg-cool-soft" : ""}`}
                  aria-hidden="true"
                >
                  {isPast && <Check className="h-2.5 w-2.5 text-ok" />}
                </span>
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className={`text-sm font-medium ${isPast || isCurrent ? "text-ink" : "text-muted"}`}>
                    {st.label}
                  </span>
                  <span className="text-sm text-muted">{st.detail}</span>
                </div>
                <span className={`measured shrink-0 text-xs ${isCurrent ? "text-cool" : "text-muted"}`}>{state}</span>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}
