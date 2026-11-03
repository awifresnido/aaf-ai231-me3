// Thin read-only API client. The dashboard only ever GETs parsed diagnostics.

import type { RunDetail, State } from "./types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} for ${url}`);
  }
  return res.json() as Promise<T>;
}

export function fetchState(): Promise<State> {
  return getJson<State>("/api/state");
}

export function fetchRun(runId: string): Promise<RunDetail> {
  return getJson<RunDetail>(`/api/runs/${runId}`);
}
