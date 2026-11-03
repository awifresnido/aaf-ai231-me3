import type { RunDetail } from "../types";
import { fmtS } from "../displayNames";

// Classifier health: success vs timeout/error counts + latency histogram.
export default function ClassifierHealth({ detail }: { detail: RunDetail }) {
  const h = detail.classifier_health;
  const buckets: [string, number, string][] = [
    ["accepted", h.accepted, "var(--good)"],
    ["escalated", h.escalated, "var(--warn)"],
    ["rejected", h.rejected, "var(--muted)"],
    ["timeout", h.timeout, "var(--bad)"],
    ["error", h.error, "var(--bad)"],
    ["bypass", h.bypass, "var(--muted)"],
    ["multiple_actions", h.multiple_actions, "var(--muted)"],
  ];
  const totalRuns =
    h.accepted + h.escalated + h.rejected + h.timeout + h.error;
  const maxBin = Math.max(...h.histogram.bins.map((b) => b.count), 1);

  return (
    <div className="panel">
      <h2>Classifier health</h2>

      {h.timeout + h.error > 0 && (
        <div className="error-note">
          <strong>
            {h.timeout} timeout{h.timeout === 1 ? "" : "s"} · {h.error} error
            {h.error === 1 ? "" : "s"}
          </strong>{" "}
          — classifier latency hit the {fmtS(detail.config.classifier_timeout_s)}{" "}
          timeout ceiling (the fp32→CPU era showed ~2 s timeouts; fp16 CUDA should
          sit well under 1 s).
        </div>
      )}

      <div className="stats" style={{ marginBottom: 16 }}>
        {buckets.map(([label, count, color]) => (
          <div className="stat" key={label}>
            <div className="k" style={{ color }}>
              {label}
            </div>
            <div className="v">{count}</div>
          </div>
        ))}
      </div>

      <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>
        classifier latency distribution ({h.latency.n} runs · median{" "}
        {fmtS(h.latency.median)} · p95 {fmtS(h.latency.p95)})
        {totalRuns > 0 ? ` · ${h.timeout + h.error}/${totalRuns} failed` : ""}
      </div>
      <div className="hist">
        {h.histogram.bins.map((b, i) => (
          <div className="bin" key={i}>
            <div
              className={`bar ${b.hi > 1.5 ? "timeout" : ""}`}
              style={{ height: `${(b.count / maxBin) * 100}%` }}
              title={`${b.lo}–${b.hi}s: ${b.count}`}
            />
            <span className="lbl">{b.lo}</span>
          </div>
        ))}
      </div>
      <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
        x-axis: seconds. Red bins ≈ the {fmtS(detail.config.classifier_timeout_s)}{" "}
        timeout ceiling.
      </div>
    </div>
  );
}
