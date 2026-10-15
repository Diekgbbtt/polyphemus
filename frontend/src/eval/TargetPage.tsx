import { Link, useParams } from "react-router-dom"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import type { EvalTrial } from "./types"

// Stable per-TargetRun anchor; TrialPage links its TargetRun crumb here, so the
// two must keep the same shape.
function targetRunAnchor(targetRunId: string): string {
  return `targetrun-${targetRunId.replace(/[^A-Za-z0-9_-]/g, "-")}`
}

function verdictCounts(trial: EvalTrial) {
  const counts = { identified: 0, partial: 0, missed: 0 }
  for (const verdict of trial.verdicts) counts[verdict.identified] += 1
  return counts
}

function phasesLabel(trial: EvalTrial): string {
  const names = trial.phases.map((phase) => phase.phase).filter(Boolean)
  return names.length > 0 ? names.join(" → ") : "—"
}

function groupByTargetRun(trials: EvalTrial[]): [string, EvalTrial[]][] {
  const groups = new Map<string, EvalTrial[]>()
  for (const trial of trials) {
    const run = groups.get(trial.target_run_id) ?? []
    run.push(trial)
    groups.set(trial.target_run_id, run)
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
}

// One Target ("machine"): its verdict summary, its TargetRuns, and every Trial.
export function TargetPage() {
  const { targetId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const target = snapshot.targets.find((item) => item.target_id === targetId)
  const crumbs = [
    { label: "Eval", to: evalPaths.dashboard },
    { label: snapshot.dataset.name, to: evalPaths.dataset(snapshot.dataset.id) },
    { label: targetId },
  ]
  if (!target) {
    return (
      <div className="eval-page">
        <EvalBreadcrumbs items={crumbs} />
        <p className="eval-empty">Unknown target “{targetId}”.</p>
      </div>
    )
  }

  const trials = snapshot.trials.filter((trial) => trial.target_id === targetId)
  const degraded = trials.filter((trial) => trial.availability === "degraded").length

  return (
    <div className="eval-page">
      <EvalBreadcrumbs items={crumbs} />
      <header className="eval-header">
        <h1>{target.target_id}</h1>
        <p className="eval-dataset-id">Target (machine)</p>
      </header>

      <dl className="eval-summary" aria-label="Target summary">
        <div>
          <dt>Identified</dt>
          <dd>{target.identified_count}</dd>
        </div>
        <div>
          <dt>Partial</dt>
          <dd>{target.partial_count}</dd>
        </div>
        <div>
          <dt>Missed</dt>
          <dd>{target.missed_count}</dd>
        </div>
        <div>
          <dt>Degraded trials</dt>
          <dd>{degraded}</dd>
        </div>
      </dl>

      {groupByTargetRun(trials).map(([targetRunId, runTrials]) => (
        <section
          key={targetRunId}
          id={targetRunAnchor(targetRunId)}
          className="eval-run-group"
          aria-label={`TargetRun ${targetRunId}`}
        >
          <h2>
            TargetRun <span className="eval-ref">{targetRunId}</span>
          </h2>
          <table className="eval-table">
            <thead>
              <tr>
                <th scope="col">Trial</th>
                <th scope="col">Terminal</th>
                <th scope="col">Phases</th>
                <th scope="col">Identified</th>
                <th scope="col">Partial</th>
                <th scope="col">Missed</th>
                <th scope="col">eval_sha</th>
                <th scope="col">Fingerprint</th>
                <th scope="col">Availability</th>
              </tr>
            </thead>
            <tbody>
              {runTrials.map((trial) => {
                const counts = verdictCounts(trial)
                return (
                  <tr key={trial.trial_id}>
                    <th scope="row">
                      <Link to={evalPaths.trial(trial.target_id, trial.target_run_id, trial.trial_id)}>
                        {trial.trial_id}
                      </Link>
                    </th>
                    <td>{trial.terminal ?? "—"}</td>
                    <td>{phasesLabel(trial)}</td>
                    <td>{counts.identified}</td>
                    <td>{counts.partial}</td>
                    <td>{counts.missed}</td>
                    <td>
                      {trial.eval_sha ? (
                        <Link to={evalPaths.version(trial.eval_sha, trial.stack_fingerprint ?? "")}>
                          {trial.eval_sha}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{trial.stack_fingerprint ?? "—"}</td>
                    <td>{trial.availability}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  )
}
