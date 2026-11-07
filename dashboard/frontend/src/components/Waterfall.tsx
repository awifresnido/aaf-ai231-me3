import type { RunDetail, TurnTimings } from "../types";
import { fmtS } from "../displayNames";

interface Segment {
  key: keyof TurnTimings;
  label: string;
  color: string;
}

const SEGMENTS: Segment[] = [
  { key: "asr_s", label: "ASR", color: "#38bdf8" },
  { key: "classifier_s", label: "Classifier", color: "#a78bfa" },
  { key: "tool_s", label: "Tool / LLM", color: "#4ade80" },
  { key: "tts_first_s", label: "TTS first audio", color: "#f472b6" },
];

const STAGE_KEYS = ["e2e_s", "asr_s", "classifier_s", "tool_s", "tts_first_s"] as const;

export function LatencySummary({ detail }: { detail: RunDetail }) {
  return <div className="panel panel-tight"><h2>Latency · median / p95</h2><div className="latency-summary">
    {STAGE_KEYS.map((k) => {
      const label = k === "e2e_s" ? "E2E" : SEGMENTS.find((x) => x.key === k)?.label ?? k;
      const color = SEGMENTS.find((x) => x.key === k)?.color;
      return <div className="latency-summary-row" key={k} style={color ? { borderTopColor: color } : undefined}><span className="latency-label">{color && <span className="dot" style={{ background: color }} />}{label}</span><strong className="mono">{fmtS(detail.aggregates[k].median)}</strong><small>p95 {fmtS(detail.aggregates[k].p95)}</small></div>;
    })}
  </div></div>;
}

// Latency waterfall, trimmed to the most recent 3 turns (full-width strip).
// Each turn is a stacked bar of the measured stages; the run-level median/p95
// summary is shown inline so the whole thing stays one short band.
export default function Waterfall({ detail }: { detail: RunDetail }) {
  const turns = detail.turns.slice(-3);
  const e2eValues = turns
    .map((t) => t.timings.e2e_s)
    .filter((v): v is number => v !== null);
  const maxE2e = Math.max(...e2eValues, 1);

  return (
    <div className="panel panel-tight">
      <h2>Latency waterfall · last {turns.length} turns</h2>

      <div className="wf-head">
        <div className="legend">
          {SEGMENTS.map((s) => (
            <span className="item" key={s.key}>
              <span className="dot" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      </div>

      <div className="waterfall">
        {turns.map((t) => {
          const parts = SEGMENTS.flatMap((s) => {
            const v = t.timings[s.key];
            if (v === null || v === undefined) return [];
            return [
              {
                color: s.color,
                label: s.label,
                value: v,
                w: Math.max((v / maxE2e) * 100, 0.4),
              },
            ];
          });
          return (
            <div className="wf-row" key={t.turn}>
              <span className="muted mono wf-turn">#{t.turn}</span>
              <div className="wf-bar">
                {parts.map((p, i) => (
                  <div
                    className="wf-seg"
                    key={i}
                    style={{ background: p.color, width: `${p.w}%` }}
                    title={`${p.label}: ${fmtS(p.value)}`}
                  />
                ))}
              </div>
              <span className="wf-e2e-label">{fmtS(t.timings.e2e_s)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
