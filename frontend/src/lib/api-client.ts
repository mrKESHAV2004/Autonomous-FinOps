import { ApiResponse } from "@/types/finops";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiClient<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<{ data: T; meta?: ApiResponse<T>["meta"] }> {
  // Use /api/v1 proxy or direct URL
  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const url = path.startsWith("/api/v1") ? path : `/api/v1${path}`;

  const res = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...options.headers,
    },
  });

  const json = (await res.json()) as ApiResponse<T>;

  if (!res.ok || !json.success) {
    throw new ApiError(json.error || `Request failed with status ${res.status}`, res.status, json);
  }

  return { data: json.data, meta: json.meta };
}
