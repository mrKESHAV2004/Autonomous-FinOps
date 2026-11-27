"use client";

import { useState, useMemo } from "react";
import { 
  Finding, 
  TriageStatus, 
  FindingConfidence 
} from "@/types/finops";
import { Search, Copy, Check, X } from "lucide-react";

const INITIAL_FINDINGS: Finding[] = [
  {
    id: "fnd-001",
    analysis_id: "anl-latest",
    resource_key: "arn:aws:ec2:us-east-1:123456789012:instance/i-03fa99b4d8e712a81",
    provider: "aws",
    service: "AmazonEC2",
    region_id: "us-east-1",
    status: "open",
    confidence: "high",
    waste_estimate: 1420.50,
    waste_pct: 88.5,
    actual_cost: 1605.00,
    peer_median_cost: 184.50,
    signals: ["idle_cpu_p95_lt_2pct", "network_in_out_zero", "isolation_forest_outlier"],
    reasons: [
      "Average CPU utilization below 1.8% over 30 days",
      "Cost is 8.7x higher than peer instances in us-east-1",
      "Tagged environment: staging (no active incoming traffic)"
    ],
    recommended_action: "Stop instance or downscale from c5.4xlarge to t3.medium",
    created_at: "2026-11-20T10:00:00Z"
  },
  {
    id: "fnd-002",
    analysis_id: "anl-latest",
    resource_key: "arn:aws:rds:us-east-1:123456789012:db:analytics-replica-old",
    provider: "aws",
    service: "AmazonRDS",
    region_id: "us-east-1",
    status: "open",
    confidence: "high",
    waste_estimate: 2180.00,
    waste_pct: 95.0,
    actual_cost: 2294.00,
    peer_median_cost: 114.00,
    signals: ["zero_read_queries", "zero_connections", "snapshot_available"],
    reasons: [
      "Zero client connections detected for 21 consecutive days",
      "Read replica orphaned after migration cutover"
    ],
    recommended_action: "Take final snapshot and delete orphaned read replica",
    created_at: "2026-11-21T12:30:00Z"
  },
  {
    id: "fnd-003",
    analysis_id: "anl-latest",
    resource_key: "arn:aws:ec2:eu-west-1:123456789012:volume/vol-091a2b3c4d5e6f7a8",
    provider: "aws",
    service: "AmazonEBS",
    region_id: "eu-west-1",
    status: "snoozed",
    confidence: "high",
    waste_estimate: 480.00,
    waste_pct: 100.0,
    actual_cost: 480.00,
    peer_median_cost: 0.00,
    signals: ["unattached_volume_gt_14d"],
    reasons: [
      "gp3 volume has been in available (unattached) state for 38 days",
      "Size: 4,000 GiB with 10,000 IOPS provisioned"
    ],
    recommended_action: "Create snapshot and terminate unattached volume",
    snoozed_until: "2026-12-15",
    created_at: "2026-11-18T08:00:00Z"
  },
  {
    id: "fnd-004",
    analysis_id: "anl-latest",
    resource_key: "arn:aws:ec2:us-west-2:123456789012:natgateway/nat-04a8b7c6d5e",
    provider: "aws",
    service: "NatGateway",
    region_id: "us-west-2",
    status: "open",
    confidence: "medium",
    waste_estimate: 680.00,
    waste_pct: 72.0,
    actual_cost: 944.00,
    peer_median_cost: 264.00,
    signals: ["nat_idle_data_transfer", "vpc_endpoint_candidate"],
    reasons: [
      "High NAT gateway hourly fee with negligible outbound egress data transfer",
      "Traffic predominantly routed to S3 (candidate for free Gateway VPC Endpoint)"
    ],
    recommended_action: "Deploy S3 Gateway Endpoint to bypass NAT Gateway data processing charges",
    created_at: "2026-11-22T14:15:00Z"
  },
  {
    id: "fnd-005",
    analysis_id: "anl-latest",
    resource_key: "arn:aws:ec2:us-east-1:123456789012:instance/i-09b8c7d6e5f4a3b2c",
    provider: "aws",
    service: "AmazonEC2",
    region_id: "us-east-1",
    status: "resolved",
    confidence: "high",
    waste_estimate: 960.00,
    waste_pct: 64.0,
    actual_cost: 1500.00,
    peer_median_cost: 540.00,
    signals: ["overprovisioned_memory"],
    reasons: [
      "Downscaled from r5.2xlarge to r5.large on Nov 24 following FinOps audit"
    ],
    recommended_action: "Downsized successfully",
    created_at: "2026-11-15T09:00:00Z"
  }
];

export function FindingsTable() {
  const [findings, setFindings] = useState<Finding[]>(INITIAL_FINDINGS);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [confidenceFilter, setConfidenceFilter] = useState<string>("all");
  const [activeFinding, setActiveFinding] = useState<Finding | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Triage state mutation form
  const [triageStatus, setTriageStatus] = useState<TriageStatus>("open");
  const [triageNote, setTriageNote] = useState("");
  const [snoozeDays, setSnoozeDays] = useState("14");

  const filteredFindings = useMemo(() => {
    return findings.filter((f) => {
      const matchesSearch =
        search === "" ||
        f.resource_key.toLowerCase().includes(search.toLowerCase()) ||
        f.service.toLowerCase().includes(search.toLowerCase()) ||
        f.region_id.toLowerCase().includes(search.toLowerCase());

      const matchesStatus = statusFilter === "all" || f.status === statusFilter;
      const matchesConfidence = confidenceFilter === "all" || f.confidence === confidenceFilter;

      return matchesSearch && matchesStatus && matchesConfidence;
    });
  }, [findings, search, statusFilter, confidenceFilter]);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const handleOpenTriage = (finding: Finding) => {
    setActiveFinding(finding);
    setTriageStatus(finding.status);
    setTriageNote("");
  };

  const handleSaveTriage = () => {
    if (!activeFinding) return;

    const updated = findings.map((f) => {
      if (f.id === activeFinding.id) {
        let snoozedDate: string | null = null;
        if (triageStatus === "snoozed") {
          const d = new Date();
          d.setDate(d.getDate() + parseInt(snoozeDays, 10));
          snoozedDate = d.toISOString().split("T")[0];
        }
        return {
          ...f,
          status: triageStatus,
          snoozed_until: snoozedDate,
          reasons: triageNote ? [...f.reasons, `Triage Note: ${triageNote}`] : f.reasons,
        };
      }
      return f;
    });

    setFindings(updated);
    setActiveFinding(null);
  };

  const statusChip: Record<TriageStatus, string> = {
    open: "chip",
    snoozed: "chip chip--person",
    resolved: "chip chip--ok",
    ignored: "chip chip--quiet",
  };

  const confidenceChip: Record<FindingConfidence, string> = {
    high: "chip chip--cool",
    medium: "chip",
    low: "chip chip--quiet",
  };

  const money = (n: number) =>
    `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <div className="flex flex-col gap-4">
      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-60 max-w-sm flex-1">
          <label htmlFor="finding-search" className="visually-hidden">
            Filter findings
          </label>
          <Search className="pointer-events-none absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2 text-muted" aria-hidden="true" />
          <input
            id="finding-search"
            name="finding-search"
            type="search"
            autoComplete="off"
            placeholder="Filter by Resource ARN, Service, Region..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="field pl-9"
          />
        </div>

        <div className="flex items-center gap-2">
          <span id="status-filter-label" className="text-sm text-muted">
            Status
          </span>
          <div className="seg" role="group" aria-labelledby="status-filter-label">
            {["all", "open", "snoozed", "resolved"].map((st) => (
              <button
                key={st}
                type="button"
                aria-pressed={statusFilter === st}
                onClick={() => setStatusFilter(st)}
                className="capitalize"
              >
                {st}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span id="confidence-filter-label" className="text-sm text-muted">
            Confidence
          </span>
          <div className="seg" role="group" aria-labelledby="confidence-filter-label">
            {["all", "high", "medium"].map((cf) => (
              <button
                key={cf}
                type="button"
                aria-pressed={confidenceFilter === cf}
                onClick={() => setConfidenceFilter(cf)}
                className="capitalize"
              >
                {cf}
              </button>
            ))}
          </div>
        </div>

        <p className="ml-auto text-sm text-muted" aria-live="polite">
          Showing <span className="measured text-ink">{filteredFindings.length}</span> of{" "}
          <span className="measured text-ink-2">{findings.length}</span> items
        </p>
      </div>

      {/* The queue beside the open record. */}
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="panel overflow-hidden">
          <div className="overflow-x-auto">
            <table className="queue">
              <thead>
                <tr>
                  <th scope="col">Resource identifier</th>
                  <th scope="col">Service and region</th>
                  <th scope="col" className="num">Actual cost</th>
                  <th scope="col" className="num">Waste ($/mo)</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredFindings.length === 0 && (
                  <tr className="cursor-default">
                    <td colSpan={7} className="h-auto py-10 text-center">
                      <p className="mx-auto text-ink">No findings match these filters.</p>
                      <p className="mx-auto mt-1 text-sm text-muted">
                        Clear the search or set status and confidence back to all.
                      </p>
                    </td>
                  </tr>
                )}
                {filteredFindings.map((finding) => {
                  const resourceId = finding.resource_key.split("/").pop() || finding.resource_key;
                  const isCopied = copiedId === finding.id;
                  const isActive = activeFinding?.id === finding.id;

                  return (
                    <tr key={finding.id} aria-selected={isActive} onClick={() => handleOpenTriage(finding)}>
                      <td>
                        <div className="flex max-w-[13rem] items-center gap-1">
                          <span className="measured truncate text-ink" title={finding.resource_key}>
                            {resourceId}
                          </span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              copyToClipboard(finding.resource_key, finding.id);
                            }}
                            className="icon-btn shrink-0"
                            aria-label={isCopied ? "Copied full ARN" : "Copy full ARN"}
                            title="Copy Full ARN"
                          >
                            {isCopied ? (
                              <Check className="h-3.5 w-3.5 text-ok" aria-hidden="true" />
                            ) : (
                              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                            )}
                          </button>
                        </div>
                      </td>
                      <td>
                        <span className="block text-ink-2">{finding.service}</span>
                        <span className="measured block text-xs text-muted">{finding.region_id}</span>
                      </td>
                      <td className="num measured text-ink-2">{money(finding.actual_cost)}</td>
                      <td className="num measured whitespace-nowrap text-ink">
                        {money(finding.waste_estimate)}
                        {finding.waste_pct && (
                          <span className="ml-2 text-xs text-muted">{finding.waste_pct}%</span>
                        )}
                      </td>
                      <td>
                        <span className={`${confidenceChip[finding.confidence]} capitalize`}>{finding.confidence}</span>
                      </td>
                      <td>
                        <span className={`${statusChip[finding.status]} capitalize`}>{finding.status}</span>
                      </td>
                      <td className="text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleOpenTriage(finding);
                          }}
                          className="btn min-h-8"
                        >
                          Triage
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* The record: why it was flagged, and the decision a person signs. */}
        <aside
          aria-label="Resource anomaly triage"
          className="panel xl:sticky xl:top-[calc(var(--shell-h)+var(--space-md))]"
        >
          {!activeFinding ? (
            <div className="flex flex-col gap-2 p-6">
              <h2 className="text-lg">No finding open</h2>
              <p className="text-sm text-muted">
                Pick a row to see why it was flagged, compare it with its peers, and record a triage decision.
              </p>
            </div>
          ) : (
            <div className="flex flex-col">
              <div className="flex items-start justify-between gap-3 border-b border-rule p-6">
                <div className="flex min-w-0 flex-col gap-2">
                  <h2 className="text-lg">
                    {activeFinding.service} in {activeFinding.region_id}
                  </h2>
                  <p className="measured text-xs break-all text-muted">{activeFinding.resource_key}</p>
                </div>
                <button type="button" onClick={() => setActiveFinding(null)} className="icon-btn shrink-0" aria-label="Close triage">
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>

              <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-4 border-b border-rule p-6">
                <div className="col-span-2">
                  <dt className="text-sm text-muted">Flagged waste</dt>
                  <dd className="measured m-0 mt-1 text-3xl leading-none text-ink">
                    {money(activeFinding.waste_estimate)}
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-muted">Actual billed</dt>
                  <dd className="measured m-0 mt-1 text-ink-2">{money(activeFinding.actual_cost)}</dd>
                </div>
                <div>
                  <dt className="text-sm text-muted">Peer median cost</dt>
                  <dd className="measured m-0 mt-1 text-ink-2">{money(activeFinding.peer_median_cost ?? 0)}</dd>
                </div>
              </dl>

              <div className="flex flex-col gap-3 border-b border-rule p-6">
                <h3 className="text-sm font-medium tracking-normal text-ink">Peer-median heuristics & signals</h3>
                <ol className="trail">
                  {activeFinding.reasons.map((r, i) => (
                    <li key={i} className="text-sm text-ink-2">
                      <span className="trail-mark" aria-hidden="true" />
                      {r}
                    </li>
                  ))}
                </ol>
                {activeFinding.signals && (
                  <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                    {activeFinding.signals.map((sig) => (
                      <li key={sig} className="chip chip--cool measured">
                        {sig}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {activeFinding.recommended_action && (
                <div className="flex flex-col gap-1 border-b border-rule p-6">
                  <h3 className="text-sm font-medium tracking-normal text-ink">Recommended remedy</h3>
                  <p className="text-sm text-ink-2">{activeFinding.recommended_action}</p>
                </div>
              )}

              <div className="flex flex-col gap-4 p-6">
                <div className="flex flex-col gap-2">
                  <span id="decision-label" className="text-sm text-muted">
                    Status decision
                  </span>
                  <div className="seg self-start" role="group" aria-labelledby="decision-label">
                    {(["open", "snoozed", "resolved", "ignored"] as TriageStatus[]).map((st) => (
                      <button
                        key={st}
                        type="button"
                        aria-pressed={triageStatus === st}
                        onClick={() => setTriageStatus(st)}
                        className="capitalize"
                      >
                        {st}
                      </button>
                    ))}
                  </div>
                </div>

                {triageStatus === "snoozed" && (
                  <div className="flex flex-col gap-2">
                    <span id="snooze-label" className="text-sm text-muted">
                      Snooze duration
                    </span>
                    <div className="seg self-start" role="group" aria-labelledby="snooze-label">
                      {[
                        { days: "7", label: "7 Days" },
                        { days: "14", label: "14 Days" },
                        { days: "30", label: "30 Days" },
                      ].map((s) => (
                        <button
                          key={s.days}
                          type="button"
                          aria-pressed={snoozeDays === s.days}
                          onClick={() => setSnoozeDays(s.days)}
                        >
                          {s.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex flex-col gap-2">
                  <label htmlFor="triage-note" className="text-sm text-muted">
                    Audit note / reason
                  </label>
                  <input
                    id="triage-note"
                    name="triage-note"
                    type="text"
                    autoComplete="off"
                    placeholder="e.g. Scheduled for termination after Friday deploy"
                    value={triageNote}
                    onChange={(e) => setTriageNote(e.target.value)}
                    className="field"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2">
                  <button type="button" onClick={() => setActiveFinding(null)} className="btn">
                    Cancel
                  </button>
                  <button type="button" onClick={handleSaveTriage} className="btn btn--primary">
                    Save triage decision
                  </button>
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
