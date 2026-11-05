import type { RunConfig } from "../types";
import { asrLabel, routerLabel, smallBrainLabel, ttsLabel } from "../displayNames";

interface Stage {
  key: string;
  title: string;
  value: string;
  cls?: string;
}

// Read-only guide to the pipeline this run used. Renders the four hot-path
// stages (ASR → router → small brain → TTS) with the actual component names
// pulled from the run's configuration, plus a muted note that
// knowledge/workspace turns escalate to the cloud GLM instead of the small brain.
export default function PipelineStrip({ config }: { config: RunConfig }) {
  const stages: Stage[] = [
    { key: "asr", title: "ASR", value: asrLabel(config) },
    { key: "router", title: "Router", value: routerLabel(config) },
    { key: "small", title: "Small brain", value: smallBrainLabel(config) },
    { key: "tts", title: "TTS", value: ttsLabel(config) },
  ];

  return (
    <div className="pipeline-strip">
      {stages.map((s, i) => (
        <span className="pipe-stage" key={s.key}>
          <span className="pipe-title">{s.title}</span>
          <span className="pipe-value" title={s.value}>
            {s.value}
          </span>
          {i < stages.length - 1 && <span className="pipe-arrow">→</span>}
        </span>
      ))}
      <span className="pipe-escalate">
        ⇢ knowledge / workspace escalate to GLM (cloud)
      </span>
    </div>
  );
}
