import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { projectPaths } from "../projectPaths"
import { getProjectArtifacts } from "./client"
import { evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import {
  artifactKey,
  artifactSections,
  groupKey,
  groupLabel,
  kindLabel,
  representationLabel,
} from "./projectArtifacts"
import type {
  EvalTrial,
  ProjectArtifactGroup,
  ProjectArtifactInventory,
} from "./types"

type DetailPath = (artifactId: string) => string

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "AbortError"
  )
}

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

function GroupNode({
  group,
  detailPath,
  depth,
}: {
  group: ProjectArtifactGroup
  detailPath: DetailPath
  depth: number
}) {
  const label = groupLabel(group)
  return (
    <section className="project-artifacts-group" aria-label={label}>
      {depth === 0 ? <h3>{label}</h3> : depth === 1 ? <h4>{label}</h4> : <h5>{label}</h5>}
      {group.entries.length > 0 && (
        <ul className="project-artifact-entries">
          {group.entries.map((entry) => (
            <li key={artifactKey(entry)}>
              <Link to={detailPath(entry.artifact_id)} className="eval-ref">
                {entry.relative_path}
              </Link>
              <span className="project-artifact-meta">
                {kindLabel(entry.kind)} · {representationLabel(entry.representation)} ·{" "}
                {entry.size_bytes} bytes ·{" "}
                <span className="eval-ref">{entry.artifact_id}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {group.children.map((child) => (
        <GroupNode key={groupKey(child)} group={child} detailPath={detailPath} depth={depth + 1} />
      ))}
    </section>
  )
}

// The on-demand historical artifact index. It resolves the Trial through the
// shared `/snapshot` provider and then loads only the inventory - never the
// detail or content endpoints.
export function ProjectArtifactsPage({
  variant = "workspace",
}: {
  variant?: "workspace" | "eval"
}) {
  const { projectId = "", targetId = "", targetRunId = "", trialId = "" } = useParams()
  const { snapshot } = useEvalData()
  const [inventory, setInventory] = useState<ProjectArtifactInventory | null>(null)
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
  const available = !!trial && !notFound && trial.artifact_summary.status === "available"

  useEffect(() => {
    if (!available) {
      setInventory(null)
      setError(null)
      setLoading(false)
      return
    }
    const controller = new AbortController()
    let active = true
    setInventory(null)
    setError(null)
    setLoading(true)
    getProjectArtifacts(targetId, targetRunId, trialId, controller.signal)
      .then((response) => {
        if (!active) return
        if (!trial || response.project_id !== trial.project_id) {
          setError("Artifact inventory does not match this Trial (mismatch).")
          setLoading(false)
          return
        }
        setInventory(response)
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
  }, [available, targetId, targetRunId, trialId, trial?.project_id])

  if (!snapshot) return null
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
          evalPaths.projectArtifact(trial.target_id, trial.target_run_id, trial.trial_id, artifactId)
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
      </header>

      {trial.artifact_summary.status !== "available" ? (
        <p className="eval-notice">
          Project artifacts not available for this Trial ({trial.artifact_summary.status}).
        </p>
      ) : (
        <>
          {loading && <p className="eval-status">Loading artifacts…</p>}
          {error && (
            <p className="eval-error" role="alert">
              Artifact load error: {error}
            </p>
          )}
          {inventory && inventory.groups.length === 0 && (
            <p className="eval-empty">No artifacts for this Trial.</p>
          )}
          {inventory &&
            inventory.groups.length > 0 &&
            artifactSections(inventory.groups).map((section) => (
              <section
                key={section.category}
                id={section.category === "hunting" ? "hunting" : "skills"}
                aria-label={section.label}
              >
                <h2>{section.label}</h2>
                {section.groups.length === 0 && (
                  <p className="eval-status">No artifacts in this section.</p>
                )}
                {section.groups.map((group) => (
                  <GroupNode key={groupKey(group)} group={group} detailPath={detailPath} depth={0} />
                ))}
              </section>
            ))}
        </>
      )}
    </div>
  )
}
