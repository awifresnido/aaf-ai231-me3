import type { RunConfig } from "../types";
import { asrLabel, routerLabel, smallBrainLabel, ttsLabel } from "../displayNames";

interface Stage {
  key: string;
  title: string;
  value: string;
  device?: string;
}

// Local and cloud brains are alternative routes, not consecutive stages.
export default function PipelineStrip({ config }: { config: RunConfig }) {
  const stages: Stage[] = [
    { key: "vad", title: "VAD", value: "Silero", device: "RPi 4" },
    { key: "asr", title: "ASR", value: asrLabel(config), device: "Jetson Orin" },
    { key: "router", title: "Router", value: routerLabel(config), device: "Jetson Orin" },
    { key: "brain", title: "Local brain / cloud brain", value: `${smallBrainLabel(config)} / ${config.cloud_escalation === false ? "cloud disabled" : "GLM 5.3"}` },
    { key: "tts", title: "TTS", value: ttsLabel(config), device: "DGX A100" },
  ];

  const renderStage = (s: Stage) => (
    <span className={`pipe-stage pipe-stage-${s.key}`} key={s.key}>
      <span className="pipe-title">{s.title}{s.device && <span className="pipe-device"> · {s.device}</span>}</span>
      <span className="pipe-value" title={s.value}>{s.value}</span>
    </span>
  );

  return (
    <div className="pipeline-strip">
      {renderStage(stages[0])}
      {renderStage(stages[1])}
      {renderStage(stages[2])}
      {renderStage(stages[3])}
      {renderStage(stages[4])}
    </div>
  );
}
