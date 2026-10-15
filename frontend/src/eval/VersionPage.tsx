import { Link, useParams } from "react-router-dom"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"

// One version/environment pair. The pair (eval_sha, stack_fingerprint) is the
// identity: the same eval_sha under another fingerprint is a different page.
export function VersionPage() {
  const { evalSha = "", stackFingerprint = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const version = snapshot.versions.find(
    (item) =>
      item.eval_sha === evalSha && item.stack_fingerprint === stackFingerprint,
  )
  const crumbs = [
    { label: "Eval", to: evalPaths.dashboard },
    { label: snapshot.dataset.name, to: evalPaths.dataset(snapshot.dataset.id) },
    { label: `${evalSha} · ${stackFingerprint}` },
  ]
  if (!version) {
    return (
      <div className="eval-page">
        <EvalBreadcrumbs items={crumbs} />
        <p className="eval-empty">
          Unknown version “{evalSha} · {stackFingerprint}”.
        </p>
      </div>
    )
  }

  return (
    <div className="eval-page">
      <EvalBreadcrumbs items={crumbs} />
      <header className="eval-header">
        <h1>Version</h1>
        <p className="eval-dataset-id">
          <span className="eval-ref">{version.eval_sha}</span> ·{" "}
          <span className="eval-ref">{version.stack_fingerprint}</span>
        </p>
      </header>

      <dl className="eval-summary" aria-label="Version summary">
        <div>
          <dt>Targets</dt>
          <dd>{version.targets.length}</dd>
        </div>
        <div>
          <dt>Trials</dt>
          <dd>{version.trial_count}</dd>
        </div>
        <div>
          <dt>Identified</dt>
          <dd>{version.identified}</dd>
        </div>
        <div>
          <dt>Partial</dt>
          <dd>{version.partial}</dd>
        </div>
        <div>
          <dt>Missed</dt>
          <dd>{version.missed}</dd>
        </div>
      </dl>

      <section aria-label="Targets contributing">
        <h2>Targets contributing</h2>
        <ul className="eval-inline-list">
          {version.targets.map((targetId) => (
            <li key={targetId}>
              <Link to={evalPaths.target(targetId)}>{targetId}</Link>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Trials contributing">
        <h2>Trials contributing</h2>
        <table className="eval-table">
          <thead>
            <tr>
              <th scope="col">Target (machine)</th>
              <th scope="col">TargetRun</th>
              <th scope="col">Trial</th>
              <th scope="col">Identified</th>
              <th scope="col">Partial</th>
              <th scope="col">Missed</th>
              <th scope="col">Availability</th>
            </tr>
          </thead>
          <tbody>
            {version.trials.map((trial) => (
              <tr key={`${trial.target_id}/${trial.target_run_id}/${trial.trial_id}`}>
                <td>{trial.target_id}</td>
                <td>{trial.target_run_id}</td>
                <th scope="row">
                  <Link to={evalPaths.trial(trial.target_id, trial.target_run_id, trial.trial_id)}>
                    {trial.trial_id}
                  </Link>
                </th>
                <td>{trial.identified}</td>
                <td>{trial.partial}</td>
                <td>{trial.missed}</td>
                <td>{trial.availability}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
