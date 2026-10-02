import { Link } from "react-router-dom"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { TargetCoverageDonut, VulnerabilityCoverageDonut } from "./EvalCharts"
import { useEvalData } from "./EvalDataProvider"

// The global dashboard: two coverage donuts over the deduplicated benchmark,
// the degraded-trial notice, and the Target ("machine") roster. No binary
// successful/failed state and no raw numeric card wall.
export function EvalDashboard() {
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const { dataset, coverage, targets, degraded_trials } = snapshot
  const empty = targets.length === 0 && snapshot.trials.length === 0

  return (
    <div className="eval-page">
      <EvalBreadcrumbs items={[{ label: "Eval", to: evalPaths.dashboard }, { label: dataset.name }]} />

      <header className="eval-header">
        <h1>{dataset.name}</h1>
        <p className="eval-dataset-id">{dataset.id}</p>
      </header>

      <section aria-label="Coverage">
        <h2>Coverage</h2>
        <div className="eval-donuts">
          <TargetCoverageDonut coverage={coverage} />
          <VulnerabilityCoverageDonut coverage={coverage} />
        </div>
      </section>

      {empty && <p className="eval-empty">No eval results found in the artifact store yet.</p>}

      {degraded_trials.length > 0 && (
        <section className="eval-notice" aria-label="Partial data">
          <h2>Partial data</h2>
          <p>
            {degraded_trials.length} trial
            {degraded_trials.length === 1 ? "" : "s"} could not be projected and
            {degraded_trials.length === 1 ? " is" : " are"} excluded from the coverage
            above.
          </p>
          <ul>
            {degraded_trials.map((trial) => (
              <li key={`${trial.target_id}/${trial.target_run_id}/${trial.trial_id}`}>
                <Link
                  to={evalPaths.trial(trial.target_id, trial.target_run_id, trial.trial_id)}
                >
                  <span className="eval-ref">{trial.target_id}</span>
                  <span aria-hidden="true"> / </span>
                  <span className="eval-ref">{trial.target_run_id}</span>
                  <span aria-hidden="true"> / </span>
                  <span className="eval-ref">{trial.trial_id}</span>
                </Link>
                <span> — {trial.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {targets.length > 0 && (
        <section aria-label="Targets (machines)">
          <h2>Targets (machines)</h2>
          <table className="eval-table">
            <thead>
              <tr>
                <th scope="col">Target (machine)</th>
                <th scope="col">Trials</th>
                <th scope="col">Identified</th>
                <th scope="col">Partial</th>
                <th scope="col">Missed</th>
              </tr>
            </thead>
            <tbody>
              {targets.map((target) => (
                <tr key={target.target_id}>
                  <th scope="row">
                    <Link to={evalPaths.target(target.target_id)}>{target.target_id}</Link>
                  </th>
                  <td>{target.trial_count}</td>
                  <td>{target.identified_count}</td>
                  <td>{target.partial_count}</td>
                  <td>{target.missed_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}
