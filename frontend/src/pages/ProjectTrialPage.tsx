import { Link, useParams } from "react-router-dom"
import { evalPaths } from "../eval/EvalBreadcrumbs"
import { useEvalData } from "../eval/EvalDataProvider"
import type { EvalTrial } from "../eval/types"

function outcomeCounts(trial: EvalTrial): { identified: number; partial: number; missed: number } {
  const counts = { identified: 0, partial: 0, missed: 0 }
  for (const verdict of trial.verdicts) counts[verdict.identified] += 1
  return counts
}

// One materialized eval Trial in its project workspace. The Trial resolves by
// its full identity, and must belong to the route's project: an unknown or
// cross-project match is a generic not-found, never a leak of the other Trial.
export function ProjectTrialPage() {
  const { projectId = "", targetId = "", targetRunId = "", trialId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const trial = snapshot.trials.find(
    (item) =>
      item.target_id === targetId &&
      item.target_run_id === targetRunId &&
      item.trial_id === trialId,
  )
  if (!trial || trial.project_id !== projectId) {
    return (
      <div className="eval-page project-trial">
        <p className="eval-empty" role="status">
          Trial not found.
        </p>
      </div>
    )
  }

  const counts = outcomeCounts(trial)
  const graph = trial.project_graph_summary
  const artifacts = trial.artifact_summary

  return (
    <div className="eval-page project-trial">
      <header className="eval-header eval-trial-header">
        <h1>
          Trial <span className="eval-ref">{trial.trial_id}</span>
        </h1>
        <p className="project-trial-identity">
          <span className="eval-ref">{trial.target_id}</span> /{" "}
          <span className="eval-ref">{trial.target_run_id}</span> /{" "}
          <span className="eval-ref">{trial.trial_id}</span>
        </p>
        <p>
          <Link
            to={evalPaths.trial(trial.target_id, trial.target_run_id, trial.trial_id)}
          >
            Open eval Trial
          </Link>
        </p>
      </header>

      <ul className="eval-chips">
        <li>
          <span className="eval-chip-label">Terminal</span>
          <span className="eval-chip-value">{trial.terminal ?? "—"}</span>
        </li>
        <li>
          <span className="eval-chip-label">Availability</span>
          <span className="eval-chip-value">{trial.availability}</span>
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
        <section className="eval-notice" aria-label="Degraded trial">
          <h2>Degraded trial</h2>
          <p>
            This trial could not be fully projected (reason:{" "}
            <span className="eval-ref">{trial.reason ?? "unknown"}</span>).
          </p>
        </section>
      )}

      {/* Placeholders for the graph, hunting, and skills views (Tasks 8-10). */}
      <section aria-label="Graph" className="project-trial-section">
        <h2>Graph</h2>
        <p className="eval-status">
          Historical L0/L1 graph ·{" "}
          <span className="eval-ref">{graph.status}</span> · {graph.nodes} nodes /{" "}
          {graph.links} links
        </p>
      </section>
      <section aria-label="Hunting" className="project-trial-section">
        <h2>Hunting</h2>
        <p className="eval-status">
          Hunting artifacts · <span className="eval-ref">{artifacts.status}</span> ·{" "}
          {artifacts.hunting} entries
        </p>
      </section>
      <section aria-label="Skills" className="project-trial-section">
        <h2>Skills</h2>
        <p className="eval-status">
          Project skills · <span className="eval-ref">{artifacts.status}</span> ·{" "}
          {artifacts.skills} entries
        </p>
      </section>
    </div>
  )
}
