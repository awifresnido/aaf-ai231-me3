import { useEffect, useMemo, useState } from "react";
import { fetchRun, fetchState, newTest, saveRun } from "./api";
import type { RunDetail, State } from "./types";
import PipelineStrip from "./components/PipelineStrip";
import RunCompare from "./components/RunCompare";
import TurnFeed from "./components/TurnFeed";
import Waterfall from "./components/Waterfall";
import ToolActivity from "./components/ToolActivity";
import ClassifierHealth from "./components/ClassifierHealth";
import SmartControls from "./components/SmartControls";
import { fmtS, fmtTime } from "./displayNames";

const LIVE_MS = 2000; // live refresh interval for a running trial
const RECENT_RUNS = 5; // only the last N tests show as selectable cards

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"new" | "save" | null>(null);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );

  // Initial load — select the most recently started run so a live trial is
  // tracked automatically.
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

  // Live refresh — re-pull run list + selected run detail so the turn feed,
  // waterfall, and smart-home panel track a running trial.
  useEffect(() => {
    if (!selectedId) return;
    const id = setInterval(() => {
      fetchState().then(setState).catch(() => {});
      fetchRun(selectedId).then(setDetail).catch(() => {});
    }, LIVE_MS);
    return () => clearInterval(id);
  }, [selectedId]);

  const dn = state?.display_names;

  // "New test": restart the bot on the Pi (the one pipeline-driving action),
  // then jump the selection to the freshly started run.
  const onNewTest = async () => {
    setBusy("new");
    setToast(null);
    try {
      const r = await newTest();
      setToast({
        kind: "ok",
        text: `New test started${r.run_id ? ` · ${r.run_id}` : ""}`,
      });
      if (r.run_id) setSelectedId(r.run_id);
      fetchState().then(setState).catch(() => {});
    } catch (e) {
      setToast({ kind: "err", text: String(e) });
    } finally {
      setBusy(null);
    }
  };

  const onSave = async () => {
    if (!selectedId) return;
    setBusy("save");
    setToast(null);
    try {
      await saveRun(selectedId);
      setToast({ kind: "ok", text: `Saved ${selectedId} → data/saved/` });
    } catch (e) {
      setToast({ kind: "err", text: String(e) });
    } finally {
      setBusy(null);
    }
  };

  // Last N tests, newest first, for the selector strip.
  const recentRuns = useMemo(() => {
    if (!state) return [];
    return [...state.runs]
      .sort((a, b) => (b.started_at ?? 0) - (a.started_at ?? 0))
      .slice(0, RECENT_RUNS);
  }, [state]);

  if (error && !state) {
    return <div className="error-note">Failed to load dashboard: {error}</div>;
  }

  if (!state || !dn) {
    return <p className="muted">Loading runs…</p>;
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-row">
          <div className="header-title">
            <h1>ME3 voice-agent dashboard</h1>
            <span className="subtitle-inline">
              {state.runs.length} run{state.runs.length === 1 ? "" : "s"} ·{" "}
              <span className="live-dot" aria-hidden />
              <span className="live-tag">live · {LIVE_MS / 1000}s</span>
            </span>
          </div>
          <div className="header-actions">
            <button
              className="btn btn-primary"
              onClick={onNewTest}
              disabled={busy !== null}
            >
              {busy === "new" ? "Starting…" : "+ New test"}
            </button>
            <button
              className="btn"
              onClick={onSave}
              disabled={!detail || busy !== null}
              title="Archive this run to data/saved/"
            >
              {busy === "save" ? "Saving…" : "Save"}
            </button>
          </div>
        </div>

        {toast && (
          <div className={`toast ${toast.kind}`} role="status">
            {toast.text}
          </div>
        )}

        {detail && (
          <div className="pipe-wrap">
            <PipelineStrip config={detail.config} />
            <span className="run-meta muted">
              <strong className="mono">{detail.run_id}</strong> · {detail.turns.length}{" "}
              turns · {fmtTime(detail.started_at)} → {fmtTime(detail.ended_at)}
            </span>
          </div>
        )}

        <div className="run-strip">
          {recentRuns.map((r) => (
            <div
              key={r.run_id}
              className={`run-card ${r.run_id === selectedId ? "selected" : ""}`}
              onClick={() => setSelectedId(r.run_id)}
            >
              <div className="id">{r.run_id}</div>
              <div className="meta">
                {r.turns} turns · med e2e {fmtS(r.median_e2e_s)}
              </div>
              <div className="meta">{fmtTime(r.started_at)}</div>
            </div>
          ))}
        </div>
      </header>

      {error && (
        <div className="error-note">{error}</div>
      )}

      {detail ? (
        <>
          <div className="main-grid">
            <div className="col-left">
              <SmartControls devices={detail.devices} dn={dn} />
            </div>
            <div className="col-right">
              <TurnFeed turns={detail.turns} dn={dn} />
              <ClassifierHealth detail={detail} />
              <ToolActivity detail={detail} dn={dn} />
              <RunCompare runs={state.runs} />
            </div>
          </div>

          <div className="waterfall-wrap">
            <Waterfall detail={detail} />
          </div>
        </>
      ) : (
        <p className="muted">Loading run…</p>
      )}
    </div>
  );
}
