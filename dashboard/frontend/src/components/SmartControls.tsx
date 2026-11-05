import type { DeviceEvent, Devices, DisplayNames } from "../types";
import { toolName, fmtTime, fmtS } from "../displayNames";

const BULB_COLORS: Record<string, string> = {
  Red: "#E0473A",
  Blue: "#3A7BE0",
  Green: "#3DAA5C",
};
const WARM_WHITE = "#FFC857";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="device-card">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function LightCard({ light }: { light: Devices["final"]["lights"] }) {
  const col = light.color ? BULB_COLORS[light.color] ?? WARM_WHITE : WARM_WHITE;
  const glow = light.power ? 0.2 + 0.8 * (parseInt(light.brightness, 10) || 100) / 100 : 0;
  return (
    <Card title="Light">
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
            fillOpacity={light.power ? 0.4 + 0.6 * (parseInt(light.brightness, 10) || 100) / 100 : 1}
            stroke="#56606A"
            strokeWidth="2"
          />
          <rect x="44" y="104" width="32" height="8" rx="2" fill="#8A939B" />
          <rect x="46" y="114" width="28" height="8" rx="2" fill="#8A939B" />
          <rect x="50" y="124" width="20" height="8" rx="3" fill="#6E777F" />
        </svg>
        <dl className="sc-facts">
          <div><dt>Power</dt><dd>{light.power ? "On" : "Off"}</dd></div>
          <div><dt>Brightness</dt><dd>{light.brightness}</dd></div>
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
    </Card>
  );
}

function ClockCard({ timers, alarms }: { timers: Devices["final"]["timers"]; alarms: Devices["final"]["alarms"] }) {
  return (
    <Card title="Timer & alarm">
      <div className="sc-list">
        {timers.length === 0 && alarms.length === 0 && (
          <p className="muted">No timers or alarms set.</p>
        )}
        {timers.map((t, i) => (
          <div key={`t${i}`} className="sc-row">
            <span className="mono">{t.label}</span>
            <span className="muted">timer</span>
          </div>
        ))}
        {alarms.map((a, i) => (
          <div key={`a${i}`} className="sc-row">
            <span className="mono">{a.time_str}</span>
            <span className="muted">alarm</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function RemindersCard({ reminders }: { reminders: Devices["final"]["reminders"] }) {
  return (
    <Card title="Reminders">
      <div className="sc-list">
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

function CallCard({ call }: { call: Devices["final"]["call"] }) {
  return (
    <Card title="Phone">
      <div className="sc-list">
        {call.status === "idle" ? (
          <p className="muted">No call placed.</p>
        ) : (
          <div className="sc-row">
            <span>{call.status === "calling" ? "Calling" : call.status}</span>
            <span className="muted">{call.to}</span>
          </div>
        )}
      </div>
    </Card>
  );
}

function ActivityFeed({ events, dn }: { events: DeviceEvent[]; dn: DisplayNames }) {
  if (events.length === 0) {
    return <p className="muted">No tool calls in this run.</p>;
  }
  return (
    <div className="sc-activity">
      {events.map((e, i) => (
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

export default function SmartControls({ devices, dn }: { devices: Devices; dn: DisplayNames }) {
  const d = devices.final;
  return (
    <section className="panel">
      <div className="sc-head">
        <h2>Simulated smart home</h2>
        <span className="badge warn">reconstructed from tool args</span>
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
        <ClockCard timers={d.timers} alarms={d.alarms} />
        <RemindersCard reminders={d.reminders} />
        <CallCard call={d.call} />
      </div>

      <h3 className="sc-sub">Device activity</h3>
      <ActivityFeed events={devices.events} dn={dn} />
    </section>
  );
}
