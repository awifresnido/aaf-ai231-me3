import type { DisplayNames, RunDetail } from "../types";
import { fmtS, fmtTime, toolName } from "../displayNames";

// Tool activity: count table + a timeline of invocations across the run.
export default function ToolActivity({
  detail,
  dn,
}: {
  detail: RunDetail;
  dn: DisplayNames;
}) {
  const activity = detail.tool_activity;
  const timeline = detail.tool_timeline.filter((s) => s.at !== null);

  const start = detail.started_at;
  const end = detail.ended_at;
  const span = end && start ? end - start : 0;

  const xPct = (at: number | null) => {
    if (at === null || !start || !span) return 0;
    return ((at - start) / span) * 100;
  };

  return (
    <div className="panel">
      <h2>Tool activity</h2>

      {timeline.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>
            timeline ({fmtTime(start)} → {fmtTime(end)})
          </div>
          <div
            style={{
              position: "relative",
              height: 40,
              background: "var(--panel-2)",
              borderRadius: 6,
            }}
          >
            {timeline.map((s, i) => (
              <span
                key={i}
                title={`${toolName(dn, s.tool)} @ ${fmtTime(s.at)} (${fmtS(s.duration_s, 3)})`}
                style={{
                  position: "absolute",
                  left: `${xPct(s.at)}%`,
                  top: "50%",
                  transform: "translate(-50%, -50%)",
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: dn.groups[s.group ?? ""]?.color ?? "var(--muted)",
                }}
              />
            ))}
          </div>
        </div>
      )}

      {activity.length === 0 ? (
        <p className="muted">No MCP tool calls in this run.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Tool</th>
              <th>Group</th>
              <th className="num">Count</th>
              <th className="num">Median duration</th>
            </tr>
          </thead>
          <tbody>
            {activity.map((a) => (
              <tr key={a.tool}>
                <td className="mono">{toolName(dn, a.tool)}</td>
                <td>
                  {a.group ? (
                    <>
                      <span
                        className="dot"
                        style={{ background: dn.groups[a.group]?.color ?? "var(--muted)" }}
                      />
                      {dn.groups[a.group]?.name ?? a.group}
                    </>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="num">{a.count}</td>
                <td className="num">{fmtS(a.median_s, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
