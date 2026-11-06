import type { RunSummary } from "../types";
import { fmtS, pipelineName } from "../displayNames";

// Rank ALL loaded runs by median end-to-end latency. The identity column is a
// pipeline-components description (ASR · router · small brain · TTS), not the
// raw run-id — that reads better in a live demo and the schema/run/classifier/
// window columns are intentionally dropped for the same reason.
export default function RunCompare({ runs }: { runs: RunSummary[] }) {
  const ranked = [...runs].sort((a, b) => {
    const ma = a.median_e2e_s ?? Number.POSITIVE_INFINITY;
    const mb = b.median_e2e_s ?? Number.POSITIVE_INFINITY;
    return ma - mb;
  }).slice(0, 3);

  return (
    <div className="panel">
      <h2>Run comparison · ranked by median e2e ({ranked.length} runs)</h2>
      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Pipeline</th>
            <th className="num">Turns</th>
            <th className="num">Median e2e</th>
            <th className="num">p95 e2e</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((r, i) => (
            <tr key={r.run_id} title={r.run_id}>
              <td className="muted num">{i + 1}</td>
              <td className="pipeline-cell">
                <span className="pipe-name">{pipelineName(r.config)}</span>
                <span className="run-id muted">{r.run_id}</span>
              </td>
              <td className="num">{r.turns}</td>
              <td className="num">{fmtS(r.median_e2e_s)}</td>
              <td className="num">{fmtS(r.p95_e2e_s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
