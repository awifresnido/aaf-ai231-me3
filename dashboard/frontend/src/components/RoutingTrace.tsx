import type { DisplayNames, RunDetail } from "../types";
import { outcomeColor, outcomeName } from "../displayNames";

// Aggregate group distribution + reject/escalate indicators.
export default function RoutingTrace({
  detail,
  dn,
}: {
  detail: RunDetail;
  dn: DisplayNames;
}) {
  const dist = detail.group_distribution;
  const entries = Object.entries(dist);
  const total = entries.reduce((a, [, n]) => a + n, 0);
  const maxCount = Math.max(...entries.map(([, n]) => n), 1);

  return (
    <div className="panel">
      <h2>Routing trace ({total} turns)</h2>
      <div className="legend" style={{ marginBottom: 8 }}>
        {dn.groups && (
          <span className="item muted">
            {Object.keys(dn.groups).length} groups · escalate groups (knowledge,
            workspace) always route to GLM
          </span>
        )}
      </div>
      {entries.map(([key, count]) => (
        <div className="trace-row" key={key}>
          <span style={{ fontSize: 12 }}>
            <span className="dot" style={{ background: outcomeColor(dn, key) }} />
            {outcomeName(dn, key)}
          </span>
          <div className="trace-bar">
            <div
              className="trace-fill"
              style={{
                background: outcomeColor(dn, key),
                width: `${(count / maxCount) * 100}%`,
              }}
            />
          </div>
          <span className="mono num" style={{ textAlign: "right" }}>
            {count}
          </span>
        </div>
      ))}
    </div>
  );
}
