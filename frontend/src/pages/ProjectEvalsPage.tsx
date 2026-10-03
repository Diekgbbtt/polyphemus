import { Link, useParams } from "react-router-dom"
import { useEvalData } from "../eval/EvalDataProvider"
import type { EvalTrial } from "../eval/types"
import { projectPaths } from "../projectPaths"

// The list's sort key: the captured graph time when the Trial published one,
// otherwise the materialization time. Missing both sorts last.
function snapshotTimestamp(trial: EvalTrial): string {
  return trial.project_graph_summary.captured_at ?? trial.copied_at ?? ""
}

// Newest snapshot first, then a stable lexical tie-break on the full identity so
// two Trials that share a trial id (different run or target) never collapse.
export function compareProjectTrials(a: EvalTrial, b: EvalTrial): number {
  const left = snapshotTimestamp(a)
  const right = snapshotTimestamp(b)
  if (left !== right) return left < right ? 1 : -1
  for (const key of ["target_id", "target_run_id", "trial_id"] as const) {
    if (a[key] !== b[key]) return a[key] < b[key] ? -1 : 1
  }
  return 0
}

function outcomeCounts(trial: EvalTrial): { identified: number; partial: number; missed: number } {
  const counts = { identified: 0, partial: 0, missed: 0 }
  for (const verdict of trial.verdicts) counts[verdict.identified] += 1
  return counts
}

export function ProjectEvalsPage() {
  const { projectId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  // Only the exact project, and every materialized Trial - a degraded Trial is
  // still real history and stays listed.
  const trials = snapshot.trials
    .filter((trial) => trial.project_id === projectId)
    .slice()
    .sort(compareProjectTrials)

  return (
    <div className="eval-page project-evals">
      <header className="eval-header">
        <h1>Eval Trials</h1>
        <p className="eval-status">Materialized Trials for this project.</p>
      </header>

      {trials.length === 0 && (
        <p className="eval-empty">No eval Trials for this project yet.</p>
      )}

      <ul className="project-eval-list">
        {trials.map((trial) => {
          const counts = outcomeCounts(trial)
          const graph = trial.project_graph_summary
          const artifacts = trial.artifact_summary
          return (
            <li
              key={`${trial.target_id}/${trial.target_run_id}/${trial.trial_id}`}
              className="project-eval-item"
            >
              <Link
                className="eval-ref"
                to={projectPaths.trial(
                  projectId,
                  trial.target_id,
                  trial.target_run_id,
                  trial.trial_id,
                )}
              >
                {trial.trial_id}
              </Link>
              <p className="project-eval-identity">
                <span className="eval-ref">{trial.target_id}</span> /{" "}
                <span className="eval-ref">{trial.target_run_id}</span>
              </p>
              <ul className="eval-chips">
                <li>
                  <span className="eval-chip-label">Availability</span>
                  <span className="eval-chip-value">{trial.availability}</span>
                </li>
                <li>
                  <span className="eval-chip-label">Terminal</span>
                  <span className="eval-chip-value">{trial.terminal ?? "—"}</span>
                </li>
                <li>
                  <span className="eval-chip-label">Outcome</span>
                  <span className="eval-chip-value">
                    {counts.identified} identified / {counts.partial} partial / {counts.missed} missed
                  </span>
                </li>
                <li>
                  <span className="eval-chip-label">Graph</span>
                  <span className="eval-chip-value">
                    {graph.status} · {graph.nodes} nodes / {graph.links} links
                  </span>
                </li>
                <li>
                  <span className="eval-chip-label">Hunting</span>
                  <span className="eval-chip-value">{artifacts.hunting}</span>
                </li>
                <li>
                  <span className="eval-chip-label">Skills</span>
                  <span className="eval-chip-value">{artifacts.skills}</span>
                </li>
              </ul>
              {trial.availability === "degraded" && (
                <p className="eval-notice">Degraded ({trial.reason ?? "unknown"})</p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
