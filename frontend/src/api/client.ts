/** Thin typed fetch wrapper over the REST API. */

import type {
  BranchDiff,
  BranchOut,
  BranchTimeline,
  ForkRequest,
  Meta,
  RunDetail,
  RunListItem,
} from "./types";

const BASE = "";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getMeta: () => request<Meta>("/api/meta"),
  listRuns: () => request<RunListItem[]>("/api/runs"),
  getRun: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  createRun: (prompt: string, seed = 42) =>
    request<RunDetail>("/api/runs", {
      method: "POST",
      body: JSON.stringify({ prompt, seed }),
    }),
  deleteRun: (id: string) =>
    request<{ ok: boolean }>(`/api/runs/${id}`, { method: "DELETE" }),
  exportRun: (id: string) => request<unknown>(`/api/runs/${id}/export`),

  branchTimeline: (branchId: string) =>
    request<BranchTimeline>(`/api/branches/${branchId}/timeline`),
  fork: (branchId: string, body: ForkRequest) =>
    request<BranchOut>(`/api/branches/${branchId}/fork`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  diff: (branchId: string, against?: string) =>
    request<BranchDiff>(
      `/api/branches/${branchId}/diff${against ? `?against=${against}` : ""}`,
    ),
};

export { ApiError };
