export type TriageStatus = "open" | "snoozed" | "resolved" | "ignored";
export type FindingConfidence = "high" | "medium" | "low";

export interface Finding {
  id: string;
  analysis_id: string;
  resource_key: string;
  provider: string;
  service: string;
  region_id: string;
  sub_account_id?: string;
  tags?: Record<string, string>;
  status: TriageStatus;
  confidence: FindingConfidence;
  waste_estimate: number;
  waste_pct?: number;
  actual_cost: number;
  peer_median_cost?: number;
  signals?: string[];
  reasons: string[];
  recommended_action?: string;
  snoozed_until?: string | null;
  created_at: string;
  updated_at?: string;
}

export interface AnalysisSummary {
  id: string;
  org_id: string;
  original_filename: string;
  status: "queued" | "running" | "succeeded" | "failed";
  records?: number;
  resources?: number;
  findings?: number;
  total_cost?: number;
  total_waste?: number;
  confidence?: {
    high: number;
    medium: number;
    low: number;
  };
  period?: {
    start: string;
    end: string;
    days: number;
  };
  waste_by_service?: Record<string, number>;
  by_status?: Record<TriageStatus, number>;
  error_message?: string;
  created_at: string;
}

export interface SpendSeriesPoint {
  date: string;
  actual_spend?: number;
  baseline_forecast?: number;
  optimized_forecast?: number;
  waste_spend?: number;
}

export interface SeriesResponse {
  analysis_id: string;
  historical: SpendSeriesPoint[];
  forecast: SpendSeriesPoint[];
}

export interface CloudConnector {
  id: string;
  provider: "aws" | "azure" | "gcp";
  name: string;
  role_arn?: string;
  external_id?: string;
  s3_bucket?: string;
  s3_prefix?: string;
  region?: string;
  status: "active" | "error" | "pending";
  last_synced_at?: string | null;
  last_error?: string | null;
}

export interface Budget {
  id: string;
  scope_type: "total" | "service" | "tag";
  scope_value?: string | null;
  monthly_amount: number;
  status?: {
    current_spend: number;
    projected_spend: number;
    percent_used: number;
    is_exceeded: boolean;
  } | null;
}

export interface AlertConfig {
  id: string;
  channel_type: "slack" | "webhook" | "email";
  destination: string;
  notify_high_confidence: boolean;
  notify_budget_exceeded: boolean;
  notify_spend_spikes: boolean;
  spike_threshold_percent: number;
  is_active: boolean;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: string | null;
  meta?: {
    total: number;
    page: number;
    per_page: number;
    pages: number;
  };
}
