import type { DisplayNames, RunDetail } from "../types";
import { fmtS, toolName } from "../displayNames";

// Tool activity: local MCP tool counts, plus a line surfacing the workspace /
// knowledge turns that escalated to the cloud GLM. Those GLM-side tool calls
// (read_file, bash, github_repo, …) run off-instrument on the DGX, so they are
// reported as a count rather than as individual spans — honest rather than
// invented.
export default function ToolActivity({
  detail,
  dn,
}: {
  detail: RunDetail;
  dn: DisplayNames;
}) {
  const activity = detail.tool_activity;
  const escalated = detail.turns.filter((t) => t.escalate);
  const ws = escalated.filter(
    (t) => t.group === "workspace" || t.group === "knowledge"
  );

  return (
    <div className="panel panel-tight">
      <h2>Tool activity</h2>

      {ws.length > 0 && (
        <div className="ta-escalate">
          <span className="dot" style={{ background: "var(--warn)" }} />
          <span>
            <strong>{ws.length}</strong> workspace / knowledge turn
            {ws.length === 1 ? "" : "s"} handled by <strong>GLM (cloud)</strong>{" "}
            — cloud tool calls run off-instrument
          </span>
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
              <th className="num">Median</th>
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
