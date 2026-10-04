import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { projectPaths } from "../projectPaths"
import { getResolvedArtifact, resolvedArtifactContentUrl } from "./client"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import { ProjectArtifactRenderer } from "./ProjectArtifactRenderers"
import { kindLabel, representationLabel } from "./projectArtifacts"
import type { EvalTrial, ResolvedArtifactDetail } from "./types"

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "AbortError"
  )
}

function Identity({ trial }: { trial: EvalTrial }) {
  return (
    <p className="project-trial-identity">
      <span className="eval-ref">{trial.target_id}</span> /{" "}
      <span className="eval-ref">{trial.target_run_id}</span> /{" "}
      <span className="eval-ref">{trial.trial_id}</span> · project{" "}
      <span className="eval-ref">{trial.project_id}</span>
    </p>
  )
}

function Metadata({ detail }: { detail: ResolvedArtifactDetail }) {
  const entry = detail.entry
  return (
    <dl className="artifact-metadata">
      <div>
        <dt>Relative path</dt>
        <dd className="eval-ref">{entry.relative_path}</dd>
      </div>
      <div>
        <dt>Artifact id</dt>
        <dd className="eval-ref">{entry.artifact_id}</dd>
      </div>
      <div>
        <dt>Kind</dt>
        <dd>{kindLabel(entry.kind)}</dd>
      </div>
      <div>
        <dt>Representation</dt>
        <dd>{representationLabel(entry.representation)}</dd>
      </div>
      <div>
        <dt>Media type</dt>
        <dd className="eval-ref">{entry.media_type}</dd>
      </div>
      <div>
        <dt>Size</dt>
        <dd>{entry.size_bytes} bytes</dd>
      </div>
      <div>
        <dt>SHA-256</dt>
        <dd className="eval-ref">{entry.sha256}</dd>
      </div>
    </dl>
  )
}

// One artifact of one Trial: metadata plus a single safe representation. It
// reads the resolved detail contract, so the same view serves a captured
// schema-v2 artifact and one read from the allowlisted raw project directory.
// The download URL is rebuilt from the detail's own SHA-256, which binds the
// bytes to the metadata the reader just saw.
export function ProjectArtifactPage({
  variant = "workspace",
}: {
  variant?: "workspace" | "eval"
}) {
  const {
    projectId = "",
    targetId = "",
    targetRunId = "",
    trialId = "",
    artifactId = "",
  } = useParams()
  const { snapshot } = useEvalData()
  const [detail, setDetail] = useState<ResolvedArtifactDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const trial = snapshot?.trials.find(
    (item) =>
      item.target_id === targetId &&
      item.target_run_id === targetRunId &&
      item.trial_id === trialId,
  )
  const notFound =
    snapshot !== null &&
    (!trial ||
      !trial.project_id ||
      (variant === "workspace" && trial.project_id !== projectId))
  const resolvable = !!trial && !notFound

  useEffect(() => {
    if (!resolvable) {
      setDetail(null)
      setError(null)
      setLoading(false)
      return
    }
    const controller = new AbortController()
    let active = true
    setDetail(null)
    setError(null)
    setLoading(true)
    getResolvedArtifact(targetId, targetRunId, trialId, artifactId, controller.signal)
      .then((response) => {
        if (!active) return
        if (response.entry.artifact_id !== artifactId) {
          setError("Artifact detail does not match the requested id (mismatch).")
          setLoading(false)
          return
        }
        setDetail(response)
        setLoading(false)
      })
      .catch((cause: unknown) => {
        if (!active || isAbortError(cause)) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [resolvable, targetId, targetRunId, trialId, artifactId, trial?.project_id])

  if (!snapshot) return null
  if (notFound || !trial) {
    return (
      <div className="eval-page project-artifact">
        <p className="eval-empty" role="status">
          Trial not found.
        </p>
      </div>
    )
  }

  const indexPath =
    variant === "eval"
      ? evalPaths.projectArtifacts(trial.target_id, trial.target_run_id, trial.trial_id)
      : projectPaths.artifacts(projectId, trial.target_id, trial.target_run_id, trial.trial_id)
  // A raw/download URL is always rebuilt here; the server's own field is not
  // trusted for the link. The digest binds the bytes to this detail.
  const contentUrl = resolvedArtifactContentUrl(
    targetId,
    targetRunId,
    trialId,
    artifactId,
    detail?.entry.sha256 ?? "",
  )
  const label = detail?.entry.relative_path ?? artifactId

  return (
    <div className="eval-page project-artifact">
      {variant === "eval" ? (
        <EvalBreadcrumbs
          items={[
            { label: "Eval", to: evalPaths.dashboard },
            {
              label: `${trial.target_id}/${trial.target_run_id}/${trial.trial_id}`,
              to: evalPaths.trial(trial.target_id, trial.target_run_id, trial.trial_id),
            },
            { label: "Project artifacts", to: indexPath },
            { label },
          ]}
        />
      ) : (
        <nav className="eval-crumbs" aria-label="Breadcrumb">
          <ol>
            <li>
              <Link
                to={projectPaths.trial(
                  projectId,
                  trial.target_id,
                  trial.target_run_id,
                  trial.trial_id,
                )}
              >
                Trial workspace
              </Link>
            </li>
            <li>
              <Link to={indexPath}>Project artifacts</Link>
            </li>
            <li>
              <span aria-current="page">{label}</span>
            </li>
          </ol>
        </nav>
      )}

      <header className="eval-header eval-trial-header">
        <h1>Artifact</h1>
        <Identity trial={trial} />
      </header>

      {loading && <p className="eval-status">Loading artifact…</p>}
      {error && (
        <p className="eval-error" role="alert">
          Artifact load error: {error}
        </p>
      )}
      {detail && (
        <>
          <Metadata detail={detail} />
          <p className="artifact-actions">
            <a className="artifact-download" href={contentUrl} download>
              Download raw
            </a>
          </p>
          <ProjectArtifactRenderer detail={detail} />
        </>
      )}
    </div>
  )
}
