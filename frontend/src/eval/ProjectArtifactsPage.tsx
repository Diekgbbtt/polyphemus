import { Link, useParams } from "react-router-dom"
import { projectPaths } from "../projectPaths"
import { evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import { ResolvedArtifactsSection, type DetailPath } from "./ResolvedArtifactsSection"
import type { EvalTrial } from "./types"

function TrialIdentity({ trial }: { trial: EvalTrial }) {
  return (
    <p className="project-trial-identity">
      <span className="eval-ref">{trial.target_id}</span> /{" "}
      <span className="eval-ref">{trial.target_run_id}</span> /{" "}
      <span className="eval-ref">{trial.trial_id}</span> · project{" "}
      <span className="eval-ref">{trial.project_id}</span>
    </p>
  )
}

// The artifact index of one Trial. It is a thin wrapper around the shared
// resolved inventory, so the project workspace and the compatible eval route
// both read the same source-independent data. The Trial still resolves through
// the shared `/snapshot` provider: an unknown or cross-project identity is a
// generic not-found and never leaks another Trial.
export function ProjectArtifactsPage({
  variant = "workspace",
}: {
  variant?: "workspace" | "eval"
}) {
  const { projectId = "", targetId = "", targetRunId = "", trialId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const trial = snapshot.trials.find(
    (item) =>
      item.target_id === targetId &&
      item.target_run_id === targetRunId &&
      item.trial_id === trialId,
  )
  const notFound =
    !trial ||
    !trial.project_id ||
    (variant === "workspace" && trial.project_id !== projectId)
  if (notFound || !trial) {
    return (
      <div className="eval-page project-artifacts">
        <p className="eval-empty" role="status">
          Trial not found.
        </p>
      </div>
    )
  }

  const detailPath: DetailPath =
    variant === "eval"
      ? (artifactId) =>
          evalPaths.projectArtifact(
            trial.target_id,
            trial.target_run_id,
            trial.trial_id,
            artifactId,
          )
      : (artifactId) =>
          projectPaths.artifact(
            projectId,
            trial.target_id,
            trial.target_run_id,
            trial.trial_id,
            artifactId,
          )

  return (
    <div className="eval-page project-artifacts">
      <header className="eval-header">
        <h1>Project artifacts</h1>
        <TrialIdentity trial={trial} />
        {variant === "eval" && trial.project_id && (
          <p>
            <Link to={projectPaths.evals(trial.project_id)}>Open project workspace</Link>
          </p>
        )}
      </header>

      <ResolvedArtifactsSection
        targetId={trial.target_id}
        targetRunId={trial.target_run_id}
        trialId={trial.trial_id}
        detailPath={detailPath}
        expectedProjectId={trial.project_id}
      />
    </div>
  )
}
