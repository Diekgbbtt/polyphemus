import { Link, useParams } from "react-router-dom"
import { targetPaths } from "../projectPaths"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import { isMaterialized, verdictsAvailable } from "./trialAvailability"
import { TrialExecutionTimes, compareTrialsByStartedAt } from "./trialTimes"
import type { EvalTrial } from "./types"

// Stable per-TargetRun anchor; the Trial breadcrumb links its TargetRun crumb
// here, so the two must keep the same shape.
export function targetRunAnchor(targetRunId: string): string {
  return `targetrun-${targetRunId.replace(/[^A-Za-z0-9_-]/g, "-")}`
}

function verdictCounts(trial: EvalTrial): { identified: number; partial: number; missed: number } {
  const counts = { identified: 0, partial: 0, missed: 0 }
  for (const verdict of trial.verdicts) counts[verdict.identified] += 1
  return counts
}

// One Target ("machine"): its verdict summary, then every TargetRun with a
// compact index of its Trials. The index links each Trial to its own workspace
// and never expands a graph or an inventory, so opening a Target stays cheap
// and the full detail lives on the Trial page.
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

  const trials = snapshot.trials
    .filter((trial) => trial.target_id === targetId)
    .slice()
    .sort(compareTrialsByStartedAt)
  const degraded = trials.filter((trial) => trial.availability === "degraded").length

  // Group by TargetRun for the anchors, but order both the groups and the
  // Trials inside them newest first.
  const runs = new Map<string, EvalTrial[]>()
  for (const trial of trials) {
    const run = runs.get(trial.target_run_id) ?? []
    run.push(trial)
    runs.set(trial.target_run_id, run)
  }

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

      {[...runs.entries()].map(([targetRunId, runTrials]) => (
        <section
          key={targetRunId}
          id={targetRunAnchor(targetRunId)}
          className="eval-run-group"
          aria-label={`TargetRun ${targetRunId}`}
        >
          <h2>
            TargetRun <span className="eval-ref">{targetRunId}</span>
          </h2>
          <ul className="trial-index">
            {runTrials.map((trial) => {
              const counts = verdictCounts(trial)
              const materialized = isMaterialized(trial)
              return (
                <li key={trial.trial_id} className="trial-index-row">
                  <Link
                    className="trial-index-trial eval-ref"
                    to={targetPaths.trial(
                      trial.target_id,
                      trial.target_run_id,
                      trial.trial_id,
                    )}
                  >
                    {trial.trial_id}
                  </Link>
                  <span className="trial-index-outcome">
                    {verdictsAvailable(trial)
                      ? `${counts.identified} identified / ${counts.partial} partial / ${counts.missed} missed`
                      : "Results unavailable"}
                  </span>
                  <span className="trial-index-times">
                    <TrialExecutionTimes trial={trial} />
                  </span>
                  <span className="trial-index-saved">
                    {materialized ? null : (
                      <span className="eval-status">Not materialized</span>
                    )}
                  </span>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}

export type { EvalTrial }
