import type { RunDetail } from "../types";
import { fmtS } from "../displayNames";

// Classifier health, reduced: a single compact strip of gate counts plus a
// one-line latency summary. The big histogram was dropped to keep the right
// rail tight — the smart-home panel is the focus, not the classifier.
export default function ClassifierHealth({ detail }: { detail: RunDetail }) {
  const h = detail.classifier_health;
  const buckets: [string, number, string][] = [
    ["accepted", h.accepted, "var(--good)"],
    ["escalated", h.escalated, "var(--warn)"],
    ["rejected", h.rejected, "var(--muted)"],
    ["timeout", h.timeout, "var(--bad)"],
    ["error", h.error, "var(--bad)"],
  ];
  const total = h.accepted + h.escalated + h.rejected + h.timeout + h.error;

  return (
    <div className="panel panel-tight">
      <h2>Classifier health</h2>
      <div className="ch-strip">
        {buckets.map(([label, count, color]) => (
          <span className="ch-chip" key={label}>
            <span className="ch-label" style={{ color }}>
              {label}
            </span>
            <span className="ch-count">{count}</span>
          </span>
        ))}
      </div>
      <div className="muted ch-meta">
        latency median {fmtS(h.latency.median)} · p95 {fmtS(h.latency.p95)}
        {total > 0 ? ` · ${h.timeout + h.error}/${total} failed` : ""}
      </div>
    </div>
  );
}
