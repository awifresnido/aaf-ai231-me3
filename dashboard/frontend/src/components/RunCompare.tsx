import type { RunSummary } from "../types";
import { fmtS, fmtTime } from "../displayNames";

// Run comparison: rank loaded runs by median end-to-end latency.
export default function RunCompare({ runs }: { runs: RunSummary[] }) {
  const ranked = [...runs].sort((a, b) => {
    const ma = a.median_e2e_s ?? Number.POSITIVE_INFINITY;
    const mb = b.median_e2e_s ?? Number.POSITIVE_INFINITY;
    return ma - mb;
  });

  return (
    <div className="panel">
      <h2>Run comparison (ranked by median e2e)</h2>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Run</th>
            <th>Schema</th>
            <th className="num">Turns</th>
            <th className="num">Median e2e</th>
            <th className="num">p95 e2e</th>
            <th className="num">Classifier ok / fail</th>
            <th>Window</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((r, i) => (
            <tr key={r.run_id}>
              <td className="muted">{i + 1}</td>
              <td className="mono">{r.run_id}</td>
              <td>
                <span className="pill">{r.schema}</span>
              </td>
              <td className="num">{r.turns}</td>
              <td className="num">{fmtS(r.median_e2e_s)}</td>
              <td className="num">{fmtS(r.p95_e2e_s)}</td>
              <td className="num">
                <span className={r.classifier_fail > 0 ? "bad" : "good"}>
                  {r.classifier_ok} ok / {r.classifier_fail} fail
                </span>
              </td>
              <td className="muted">
                {fmtTime(r.started_at)}–{fmtTime(r.ended_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
