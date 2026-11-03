// Friendly-name resolution. Single source of truth is the backend's
// `display_names` (never hardcoded in components); these helpers just read it.

import type { DisplayNames } from "./types";

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
