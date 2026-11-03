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

// Per-turn stacked latency waterfall (measured stages), with median/p95 summary.
export default function Waterfall({ detail }: { detail: RunDetail }) {
  const turns = detail.turns;
  const e2eValues = turns
    .map((t) => t.timings.e2e_s)
    .filter((v): v is number => v !== null);
  const maxE2e = Math.max(...e2eValues, 1);

  return (
    <div className="panel">
      <h2>Latency waterfall (per turn)</h2>
      <div className="legend">
        {SEGMENTS.map((s) => (
          <span className="item" key={s.key}>
            <span className="dot" style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
        <span className="item muted">
          widths scale to max e2e ({fmtS(maxE2e)}); stages don't sum to e2e — the
          gap is unmeasured (VAD / queue / dispatch).
        </span>
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
              <span className="muted mono" style={{ fontSize: 11 }}>
                #{t.turn}
              </span>
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

      <div className="stats" style={{ marginTop: 14 }}>
        {STAGE_KEYS.map((k) => {
          const s = detail.aggregates[k];
          const label =
            k === "e2e_s"
              ? "E2E"
              : SEGMENTS.find((x) => x.key === k)?.label ?? k;
          return (
            <div className="stat" key={k}>
              <div className="k">{label}</div>
              <div className="v">{fmtS(s.median)}</div>
              <div className="muted" style={{ fontSize: 11 }}>
                median · p95 {fmtS(s.p95)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
