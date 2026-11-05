import { useEffect, useRef } from "react";
import type { DisplayNames, Turn } from "../types";
import {
  groupColor,
  groupName,
  toolName,
  dispatchName,
  fmtS,
  fmtProb,
} from "../displayNames";

// One row per turn, oldest at top, newest at the bottom. The container is
// auto-scrolled to the latest turn so a live demo defaults to the newest
// command and the operator only scrolls UP to review older ones.
export default function TurnFeed({
  turns,
  dn,
}: {
  turns: Turn[];
  dn: DisplayNames;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const gateClass = (g: string) =>
    g === "accepted"
      ? "good"
      : g === "escalated" || g === "bypass"
        ? "warn"
        : g === "timeout" || g === "error"
          ? "bad"
          : "";

  return (
    <div className="panel turn-feed">
      <h2>Turn feed ({turns.length})</h2>
      <div className="turn-scroll" ref={scrollRef}>
        <table>
          <thead>
            <tr>
              <th className="num">Turn</th>
              <th>Group</th>
              <th>Raw choice</th>
              <th className="num">Conf.</th>
              <th>Gate</th>
              <th>Handled by</th>
              <th className="num">e2e</th>
            </tr>
          </thead>
          <tbody>
            {turns.map((t) => (
              <tr key={t.turn}>
                <td className="num muted">{t.turn}</td>
                <td>
                  {t.group ? (
                    <>
                      <span className="dot" style={{ background: groupColor(dn, t.group) }} />
                      {groupName(dn, t.group)}
                      {t.escalate ? (
                        <span className="pill" style={{ marginLeft: 6 }}>
                          → GLM
                        </span>
                      ) : null}
                    </>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="mono">{t.raw_choice ?? <span className="muted">—</span>}</td>
                <td className="num">{fmtProb(t.top_prob)}</td>
                <td>
                  <span className={`badge ${gateClass(t.gate)}`}>{t.gate}</span>
                </td>
                <td>
                  {t.dispatch === "tool" && t.tool
                    ? toolName(dn, t.tool)
                    : dispatchName(dn, t.dispatch)}
                </td>
                <td className="num">{fmtS(t.timings.e2e_s)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
