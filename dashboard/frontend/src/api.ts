// Thin read-only API client. The dashboard only ever GETs parsed diagnostics.

import type { RunDetail, State } from "./types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} for ${url}`);
  }
  return res.json() as Promise<T>;
}

async function postJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body?.detail ? `: ${body.detail}` : "";
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(`${res.status} ${res.statusText}${detail}`);
  }
  return res.json() as Promise<T>;
}

export function fetchState(): Promise<State> {
  return getJson<State>("/api/state");
}

export function fetchRun(runId: string): Promise<RunDetail> {
  return getJson<RunDetail>(`/api/runs/${runId}`);
}

export function newTest(): Promise<{
  ok: boolean;
  run_id: string | null;
  message: string;
}> {
  return postJson("/api/tests/new");
}

export function saveRun(runId: string): Promise<{ ok: boolean; path: string }> {
  return postJson(`/api/runs/${runId}/save`);
}
