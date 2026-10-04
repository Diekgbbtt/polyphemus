import { useParams } from "react-router-dom"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import { TrialSection } from "./TrialSection"
import type { EvalTrial } from "./types"

// Stable per-TargetRun anchor; the Trial breadcrumb links its TargetRun crumb
// here, so the two must keep the same shape.
export function targetRunAnchor(targetRunId: string): string {
  return `targetrun-${targetRunId.replace(/[^A-Za-z0-9_-]/g, "-")}`
}

// Newest first by materialization time, then a stable lexical tie-break on the
// full identity so two Trials that share a trial id never collapse or reorder
// unpredictably.
export function compareTargetTrials(a: EvalTrial, b: EvalTrial): number {
  const left = a.copied_at ?? ""
  const right = b.copied_at ?? ""
  if (left !== right) return left < right ? 1 : -1
  for (const key of ["target_id", "target_run_id", "trial_id"] as const) {
    if (a[key] !== b[key]) return a[key] < b[key] ? -1 : 1
  }
  return 0
}

function verdictCounts(trial: EvalTrial): { identified: number; partial: number; missed: number } {
  const counts = { identified: 0, partial: 0, missed: 0 }
  for (const verdict of trial.verdicts) counts[verdict.identified] += 1
  return counts
}

// One Target ("machine"): its verdict summary, then every TargetRun with its
// Trials. Each Trial is the full continuous workspace, so the Target page is
// the whole read-only history, not just an index of links.
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
    .sort(compareTargetTrials)
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
          {runTrials.map((trial) => (
            <TrialSection key={trial.trial_id} trial={trial} />
          ))}
        </section>
      ))}
    </div>
  )
}

export type { EvalTrial }
