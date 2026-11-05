import { useEffect, useMemo, useState } from "react";
import { fetchRun, fetchState } from "./api";
import type { RunDetail, State } from "./types";
import RunCompare from "./components/RunCompare";
import TurnFeed from "./components/TurnFeed";
import Waterfall from "./components/Waterfall";
import RoutingTrace from "./components/RoutingTrace";
import ToolActivity from "./components/ToolActivity";
import ClassifierHealth from "./components/ClassifierHealth";
import SmartControls from "./components/SmartControls";
import { fmtS, fmtTime } from "./displayNames";

const LIVE_MS = 2000; // live refresh interval for a running trial

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Initial load — select the most recently started run (the active session in
  // a live trial) so the dashboard tracks the current trial automatically.
  useEffect(() => {
    fetchState()
      .then((s) => {
        setState(s);
        const newest = [...s.runs].sort(
          (a, b) => (b.started_at ?? 0) - (a.started_at ?? 0)
        )[0];
        if (newest) setSelectedId(newest.run_id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Load a run's detail whenever the selection changes.
  useEffect(() => {
    if (!selectedId) return;
    setDetail(null);
    fetchRun(selectedId)
      .then(setDetail)
      .catch((e) => setError(String(e)));
  }, [selectedId]);

  // Live refresh — re-pull the run list and the selected run's detail so the
  // turn feed, latency waterfall, and smart-home panel track a running trial.
  useEffect(() => {
    if (!selectedId) return;
    const id = setInterval(() => {
      fetchState().then(setState).catch(() => {});
      fetchRun(selectedId).then(setDetail).catch(() => {});
    }, LIVE_MS);
    return () => clearInterval(id);
  }, [selectedId]);

  const dn = state?.display_names;

  const headerMeta = useMemo(() => {
    if (!detail) return null;
    const c = detail.config;
    const parts = [
      detail.schema,
      c.router_model ? `router=${c.router_model}` : null,
      c.asr_model ?? c.asr_backend,
      c.tts_backend,
      c.orchestration_mode,
    ].filter(Boolean) as string[];
    return parts.join(" · ");
  }, [detail]);

  if (error && !state) {
    return (
      <div className="error-note">
        Failed to load dashboard: {error}
      </div>
    );
  }

  if (!state || !dn) {
    return <p className="muted">Loading runs…</p>;
  }

  return (
    <div>
      <header>
        <h1>ME3 voice-agent dashboard</h1>
        <p className="subtitle">
          Read-only pipeline diagnostics · {state.runs.length} run
          {state.runs.length === 1 ? "" : "s"} · source {state.data_dir} ·{" "}
          <span className="live-dot" aria-hidden />
          <span className="live-tag">live · {LIVE_MS / 1000}s</span>
        </p>
      </header>

      {error && (
        <div className="error-note" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}

      <div className="run-strip">
        {state.runs.map((r) => (
          <div
            key={r.run_id}
            className={`run-card ${r.run_id === selectedId ? "selected" : ""}`}
            onClick={() => setSelectedId(r.run_id)}
          >
            <div className="id">{r.run_id}</div>
            <div className="meta">
              {r.turns} turns · {r.schema}
            </div>
            <div className="meta">
              med e2e {fmtS(r.median_e2e_s)} · {fmtTime(r.started_at)}
            </div>
            <div className="badges">
              <span className={`badge ${r.classifier_fail > 0 ? "bad" : "good"}`}>
                {r.classifier_ok} ok / {r.classifier_fail} fail
              </span>
              {r.schema === "v4_tool" && <span className="badge warn">legacy</span>}
            </div>
          </div>
        ))}
      </div>

      <RunCompare runs={state.runs} />

      {detail && (
        <>
          <div className="muted" style={{ marginBottom: 16 }}>
            <strong className="mono">{detail.run_id}</strong> · {headerMeta} ·{" "}
            {detail.turns.length} turns ·{" "}
            {fmtTime(detail.started_at)} → {fmtTime(detail.ended_at)}
          </div>

          <div className="grid grid-2">
            <RoutingTrace detail={detail} dn={dn} />
            <ClassifierHealth detail={detail} />
          </div>
          <ToolActivity detail={detail} dn={dn} />
          <Waterfall detail={detail} />
          <TurnFeed turns={detail.turns} dn={dn} />
          <SmartControls devices={detail.devices} dn={dn} />
        </>
      )}
    </div>
  );
}
