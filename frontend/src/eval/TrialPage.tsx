import { Link, useParams } from "react-router-dom"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import { projectPaths } from "../projectPaths"
import { ARTIFACT_LABELS, ARTIFACT_ORDER, summarizeArtifact } from "./TrialArtifactPage"

// Must match the id TargetPage puts on each TargetRun group.
function targetRunAnchor(targetRunId: string): string {
  return `targetrun-${targetRunId.replace(/[^A-Za-z0-9_-]/g, "-")}`
}

// The Trial page is an index of the artifacts the store materialized: the trial
// header, then exactly four entries, each linking to its own readable view.
export function TrialPage() {
  const { targetId = "", targetRunId = "", trialId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const trial = snapshot.trials.find(
    (item) =>
      item.target_id === targetId &&
      item.target_run_id === targetRunId &&
      item.trial_id === trialId,
  )
  const crumbs = [
    { label: "Eval", to: evalPaths.dashboard },
    { label: snapshot.dataset.name, to: evalPaths.dataset(snapshot.dataset.id) },
    { label: targetId, to: evalPaths.target(targetId) },
    {
      label: targetRunId,
      to: `${evalPaths.target(targetId)}#${targetRunAnchor(targetRunId)}`,
    },
    { label: trialId },
  ]
  if (!trial) {
    return (
      <div className="eval-page">
        <EvalBreadcrumbs items={crumbs} />
        <p className="eval-empty">Unknown trial “{trialId}”.</p>
      </div>
    )
  }

  return (
    <div className="eval-page">
      <EvalBreadcrumbs items={crumbs} />

      <header className="eval-header eval-trial-header">
        <h1>
          Trial <span className="eval-ref">{trial.trial_id}</span>
        </h1>
        <ul className="eval-chips">
          <li>
            <span className="eval-chip-label">Terminal</span>
            <span className="eval-chip-value">{trial.terminal ?? "—"}</span>
          </li>
          <li>
            <span className="eval-chip-label">Availability</span>
            <span className="eval-chip-value">{trial.availability}</span>
          </li>
        </ul>
        {trial.project_id && (
          <p className="eval-trial-workspace">
            <Link
              to={projectPaths.trial(
                trial.project_id,
                trial.target_id,
                trial.target_run_id,
                trial.trial_id,
              )}
            >
              Open project workspace
            </Link>
          </p>
        )}
      </header>

      {trial.availability === "degraded" && (
        <section className="eval-notice" aria-label="Degraded trial">
          <h2>Degraded trial</h2>
          <p>
            This trial could not be fully projected (reason:{" "}
            <span className="eval-ref">{trial.reason ?? "unknown"}</span>). Only the
            artifacts it does carry are shown.
          </p>
        </section>
      )}

      <section aria-label="Project artifacts" className="eval-artifacts-summary">
        <h2>Project artifacts</h2>
        {trial.artifact_summary.status === "available" ? (
          <p>
            <Link
              to={evalPaths.projectArtifacts(
                trial.target_id,
                trial.target_run_id,
                trial.trial_id,
              )}
            >
              {trial.artifact_summary.hunting} hunting · {trial.artifact_summary.skills} skills
            </Link>
          </p>
        ) : (
          <p className="eval-notice">
            Project artifacts not available for this Trial (
            <span className="eval-ref">{trial.artifact_summary.status}</span>).
          </p>
        )}
      </section>

      <section aria-label="Artifacts">
        <h2>Materialized artifacts</h2>
        <ul className="eval-artifacts">
          {ARTIFACT_ORDER.map((artifact) => {
            const summary = summarizeArtifact(trial, artifact)
            return (
              <li key={artifact}>
                <Link
                  to={evalPaths.trialArtifact(
                    trial.target_id,
                    trial.target_run_id,
                    trial.trial_id,
                    artifact,
                  )}
                >
                  <span className="eval-ref">{ARTIFACT_LABELS[artifact]}</span>
                </Link>
                <span className="eval-artifact-status">{summary.statusLabel}</span>
                <p className="eval-artifact-summary">{summary.summary}</p>
              </li>
            )
          })}
        </ul>
      </section>
    </div>
  )
}
