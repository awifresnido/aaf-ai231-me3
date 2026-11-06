import { useEffect, useState } from "react";
import type { DeviceEvent, Devices, DisplayNames } from "../types";
import { toolName, fmtTime, fmtS } from "../displayNames";

const BULB_COLORS: Record<string, string> = {
  Red: "#E0473A",
  Blue: "#3A7BE0",
  Green: "#3DAA5C",
};
const WARM_WHITE = "#FFC857";

function Card({ title, children, style }: { title: string; children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <section style={style} className={`device-card ${title === "Light" || title === "Timer & alarm" || title.startsWith("Reminders") ? "device-card-featured" : ""}`}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function LightCard({ light }: { light: Devices["final"]["lights"] }) {
  const col = light.color ? BULB_COLORS[light.color] ?? WARM_WHITE : WARM_WHITE;
  const parsedBrightness = Number.parseInt(light.brightness, 10);
  const brightness = Number.isFinite(parsedBrightness) ? Math.max(0, Math.min(100, parsedBrightness)) / 100 : 1;
  const intensity = light.power ? brightness : 0;
  const glow = intensity * 0.9;
  const cardAlpha = Math.round(intensity * 0.4 * 255).toString(16).padStart(2, "0");
  return (
    <Card title="Light" style={light.power ? { background: `linear-gradient(135deg, ${col}${cardAlpha}, #171c28)`, borderColor: col } : undefined}>
      <div className="sc-light">
        <svg viewBox="0 0 120 150" className="sc-bulb" aria-hidden>
          <defs>
            <radialGradient id="sc-glow">
              <stop offset="0%" stopColor={col} stopOpacity={glow} />
              <stop offset="100%" stopColor={col} stopOpacity={0} />
            </radialGradient>
          </defs>
          <circle cx="60" cy="58" r="58" fill="url(#sc-glow)" />
          <path
            d="M60 14c-22 0-38 16-38 37 0 14 7 23 14 31 5 6 8 11 8 18h32c0-7 3-12 8-18 7-8 14-17 14-31 0-21-16-37-38-37z"
            fill={light.power ? col : "#3a4048"}
            fillOpacity={light.power ? 0.15 + 0.85 * intensity : 1}
            stroke="#56606A"
            strokeWidth="2"
          />
          <rect x="44" y="104" width="32" height="8" rx="2" fill="#8A939B" />
          <rect x="46" y="114" width="28" height="8" rx="2" fill="#8A939B" />
          <rect x="50" y="124" width="20" height="8" rx="3" fill="#6E777F" />
        </svg>
        <dl className="sc-facts">
          <div><dt>Power</dt><dd>{light.power ? "On" : "Off"}</dd></div>
          <div><dt>Brightness</dt><dd>{Math.round(brightness * 100)}%</dd></div>
          <div><dt>Colour</dt><dd>{light.color ?? "Warm white"}</dd></div>
        </dl>
      </div>
    </Card>
  );
}

function ThermostatCard({ t }: { t: Devices["final"]["thermostat"] }) {
  return (
    <Card title="Thermostat">
      <div className="sc-thermostat">
        <span className="sc-bignum">{t.degrees ?? "—"}</span>
        <span className="sc-unit">°C</span>
        {t.degrees === null && <p className="muted">Not set this run.</p>}
      </div>
    </Card>
  );
}

function MediaCard({ m }: { m: Devices["final"]["media"] }) {
  const playing = m.status === "playing";
  const vol = typeof m.volume === "number" ? Math.max(0, Math.min(4, m.volume)) : 3;
  return (
    <Card title="Music">
      <div className="sc-media">
        <span className={`sc-eq ${playing ? "on" : ""}`} aria-hidden>
          <i /><i /><i />
        </span>
        <div>
          <div className="sc-title">{m.title ?? "Nothing playing"}</div>
          <div className="muted">
            {playing ? "Playing" : m.status === "paused" ? "Paused" : "Stopped"}
            {m.mode === "music" && m.title ? " · requested" : ""}
          </div>
        </div>
      </div>
      <div className="sc-vol" title={`Volume ${vol + 1} of 5`} aria-label={`Volume ${vol + 1} of 5`}>
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} className={`sc-vol-bar ${i <= vol ? "on" : ""}`} />
        ))}
        <span className="muted sc-vol-label">volume {vol + 1}/5</span>
      </div>
    </Card>
  );
}

function ClockCard({ timers, alarms, serverTimeMs, receivedMonotonicMs }: { timers: Devices["final"]["timers"]; alarms: Devices["final"]["alarms"]; serverTimeMs: number; receivedMonotonicMs: number }) {
  const [tick, setTick] = useState(performance.now());
  useEffect(() => { const id = setInterval(() => setTick(performance.now()), 250); return () => clearInterval(id); }, []);
  const now = serverTimeMs + Math.max(0, tick - receivedMonotonicMs);
  const activeTimers = timers.filter((t) => t.ends_at == null || t.ends_at * 1000 > now);
  const latestAlarm = alarms.slice(-1);
  return (
    <Card title="Timer & alarm">
      <div className="sc-list">
        {activeTimers.length === 0 && alarms.length === 0 && (
          <p className="muted">No timers or alarms set.</p>
        )}
        {activeTimers.map((t, i) => (
          <div key={`t${i}`} className="sc-row">
            <span className="mono countdown">{t.ends_at == null ? t.label : formatCountdown(t.ends_at, now)}</span>
            <span>{t.ends_at != null && t.ends_at * 1000 <= now ? "Finished" : "Remaining"}</span>
          </div>
        ))}
        {latestAlarm.map((a, i) => (
          <div key={`a${i}`} className="sc-row">
            <span className="mono">{a.time_str}</span>
            <span className="muted">{alarms.length > 1 ? `latest alarm · ${alarms.length} set` : "alarm"}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function formatCountdown(endsAt: number, now: number) {
  const seconds = Math.max(0, Math.ceil(endsAt - now / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  const remaining = String(seconds % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${remaining}` : `${minutes}:${remaining}`;
}

function RemindersCard({ reminders }: { reminders: Devices["final"]["reminders"] }) {
  return (
    <Card title={`Reminders · ${reminders.length}`}>
      <div className="sc-list sc-reminders">
        {reminders.length === 0 && <p className="muted">No reminders added.</p>}
        {reminders.map((r, i) => (
          <div key={i} className="sc-row">
            <span>{r.text}</span>
            <span className="muted small">voice</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function CallCard({ call, message }: { call: Devices["final"]["call"]; message: Devices["final"]["message"] }) {
  return (
    <Card title="Calls & messages · simulated">
      <div className="sc-list">
        {call.status === "idle" ? (
          <p className="muted">No call placed.</p>
        ) : (
          <div className="sc-row">
            <span>{call.status === "calling" ? "Calling" : call.status}</span>
            <span className="muted">{call.to}</span>
          </div>
        )}
        {message.status === "simulated" && <div className="sc-row"><span>Message to {message.to}</span><span>{message.text}</span></div>}
        <p className="muted small">Contacts: Mom · Dad · John</p>
      </div>
    </Card>
  );
}

function ActivityFeed({ events, dn }: { events: DeviceEvent[]; dn: DisplayNames }) {
  if (events.length === 0) {
    return <p className="muted">No tool calls in this run.</p>;
  }
  const recent = events.slice(-10);
  return (
    <div className="sc-activity">
      {recent.map((e, i) => (
        <div key={i} className="sc-activity-row">
          <time className="mono muted">{fmtTime(e.at)}</time>
          <span className="sc-tool">{toolName(dn, e.tool)}</span>
          <span className="sc-change">{e.change ?? "—"}</span>
          <span className="mono muted sc-dur">
            {e.duration_s != null ? fmtS(e.duration_s) : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function SmartControls({ devices, dn, serverTimeMs, receivedMonotonicMs }: { devices: Devices; dn: DisplayNames; serverTimeMs: number; receivedMonotonicMs: number }) {
  const d = devices.final;
  return (
    <section className="panel">
      <div className="sc-head">
        <h2>Simulated smart home</h2>
        <span className="badge warn">Simulated · current run</span>
        {!devices.args_recorded && (
          <span className="badge bad">args not recorded</span>
        )}
      </div>

      {!devices.args_recorded && (
        <p className="muted sc-note">
          This run predates tool-argument logging, so the devices below show their
          default state and the activity feed lists tool names only. Re-run a trial
          with the enriched pipeline (see the runbook) to see live state changes.
        </p>
      )}

      <div className="sc-grid">
        <LightCard light={d.lights} />
        <ThermostatCard t={d.thermostat} />
        <MediaCard m={d.media} />
        <ClockCard timers={d.timers} alarms={d.alarms} serverTimeMs={serverTimeMs} receivedMonotonicMs={receivedMonotonicMs} />
        <RemindersCard reminders={d.reminders} />
        <CallCard call={d.call} message={d.message} />
      </div>

      <h3 className="sc-sub">Device activity (last 10 commands)</h3>
      <ActivityFeed events={devices.events} dn={dn} />
    </section>
  );
}
