// Friendly-name resolution. Single source of truth is the backend's
// `display_names` (never hardcoded in components); these helpers just read it.

import type { DisplayNames, RunConfig } from "./types";

export function groupName(dn: DisplayNames, id: string | null): string {
  if (!id) return "—";
  return dn.groups[id]?.name ?? id;
}

export function groupColor(dn: DisplayNames, id: string | null): string {
  if (!id) return "var(--muted)";
  return dn.groups[id]?.color ?? "var(--muted)";
}

export function outcomeName(dn: DisplayNames, id: string | null): string {
  if (!id) return "—";
  return dn.outcomes[id]?.name ?? dn.groups[id]?.name ?? id;
}

export function outcomeColor(dn: DisplayNames, id: string | null): string {
  if (!id) return "var(--muted)";
  return dn.outcomes[id]?.color ?? dn.groups[id]?.color ?? "var(--muted)";
}

export function toolName(dn: DisplayNames, id: string | null): string {
  if (!id) return "—";
  return dn.tools[id] ?? id;
}

export function dispatchName(dn: DisplayNames, id: string | null): string {
  if (!id) return "—";
  return dn.dispatch[id]?.name ?? id;
}

export function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "not recorded";
  return `${(v * 1000).toFixed(0)} ms`;
}

export function fmtS(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "not recorded";
  return `${v.toFixed(digits)} s`;
}

export function fmtTime(epoch: number | null | undefined): string {
  if (epoch === null || epoch === undefined) return "not recorded";
  return new Date(epoch * 1000).toLocaleTimeString("en-GB", { hour12: false });
}

export function fmtProb(v: number | null | undefined): string {
  if (v === null || v === undefined) return "not recorded";
  return v.toFixed(2);
}

// ---- Pipeline component labels (single source of truth for the pipeline
// strip and the run-comparison "name" column). ----------------------------

function shortModel(m: string | null | undefined, fallback = "—"): string {
  if (!m) return fallback;
  const tail = m.split("/").pop() ?? m;
  return tail;
}

export function asrLabel(c: RunConfig): string {
  return c.asr_model ?? c.asr_backend ?? "—";
}

export function routerLabel(c: RunConfig): string {
  const m = c.router_model;
  if (!m) return "—";
  if (m === "laya") return "Laya";
  if (m === "jev") return "Jev";
  return m;
}

export function smallBrainLabel(c: RunConfig): string {
  if (!c.small_llm_primary_model) return "—";
  const t = shortModel(c.small_llm_primary_model);
  const m = t.match(/Llama-([\d.]+)/i);
  return m ? `Llama ${m[1]}` : t;
}

export function ttsLabel(c: RunConfig): string {
  if (!c.tts_model) return c.tts_backend ?? "—";
  const t = shortModel(c.tts_model);
  return t.match(/Qwen3-TTS/i)?.[0] ?? t.match(/Qwen2-Audio/i)?.[0] ?? t;
}

// Compact "name" describing a run by its pipeline components, used as the
// run-comparison identity column (replaces the raw run-id + schema columns).
export function pipelineName(c: RunConfig): string {
  const parts = [
    asrLabel(c),
    routerLabel(c),
    smallBrainLabel(c),
    ttsLabel(c),
  ].filter((p) => p && p !== "—");
  return parts.length ? parts.join(" · ") : "—";
}
