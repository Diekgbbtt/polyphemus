import { useMemo } from "react"
import { Link } from "react-router-dom"
import { useResolvedArtifactsResource, useResolvedInventory } from "./ResolvedArtifactsProvider"
import type { ResolvedArtifactsResource } from "./ResolvedArtifactsProvider"
import { usePodExportOutcomes } from "./usePodExportOutcomes"
import {
  artifactKey,
  artifactSections,
  collectPodExports,
  groupKey,
  groupLabel,
  kindLabel,
  representationLabel,
  sourceLabel,
  withPodExportOutcomes,
  withTestSpecSides,
} from "./projectArtifacts"
import type { ProjectArtifactGroup } from "./types"

export type DetailPath = (artifactId: string) => string

const EMPTY_LABEL: Record<"hunting" | "skill", string> = {
  hunting: "No Hunting artifacts",
  skill: "No Skill artifacts",
}

const NO_GROUPS: ProjectArtifactGroup[] = []

// One inventory group rendered as a nested section. Shared with the standalone
// artifacts page so the inline and routed views never drift.
export function ArtifactGroupNode({
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
        <ArtifactGroupNode
          key={groupKey(child)}
          group={child}
          detailPath={detailPath}
          depth={depth + 1}
        />
      ))}
    </section>
  )
}

// The Hunting and Skill inventory of one Trial, rendered from the shared
// resource (the workspace provider) or from this section's own poll (the
// standalone artifacts page). It loads the inventory only: no artifact detail or
// content is fetched until the reader opens one. A zero-entry readable inventory
// shows both sections with an explicit empty state, and a failure stays here.
function ResolvedArtifactsView({
  resource,
  targetId,
  targetRunId,
  trialId,
  detailPath,
}: {
  resource: ResolvedArtifactsResource
  targetId: string
  targetRunId: string
  trialId: string
  detailPath: DetailPath
}) {
  const kind = resource.loading ? "loading" : resource.data ? "ready" : "error"

  // The PodExport outcome groups need the detail (the inventory has no
  // terminal_reason), so classify the export entries here and fold the result
  // into the same shared presentation the rest of the tree uses.
  const availableInventory = resource.data && resource.data.status === "available" ? resource.data : null
  const inventoryGroups = availableInventory ? availableInventory.groups : NO_GROUPS
  const podExports = useMemo(
    () => (availableInventory ? collectPodExports(availableInventory.groups) : []),
    [availableInventory],
  )
  const podExportOutcomes = usePodExportOutcomes({
    targetId,
    targetRunId,
    trialId,
    exports: podExports,
    inventoryRevision: resource.lastUpdatedAt ?? 0,
  })
  const groups = useMemo(
    () => withPodExportOutcomes(withTestSpecSides(inventoryGroups), podExportOutcomes),
    [inventoryGroups, podExportOutcomes],
  )

  return (
    <div className="resolved-artifacts">
      {kind === "loading" && <p className="eval-status">Loading artifacts…</p>}
      {kind === "error" && (
        <p className="eval-error" role="alert">
          Artifact load error: {resource.error ?? "unknown"}
        </p>
      )}
      {resource.data !== null && resource.error !== null && (
        <p className="eval-status" role="status">
          Artifact refresh failed: {resource.error}. Showing the previous inventory.
        </p>
      )}
      {kind === "ready" && resource.data !== null && resource.data.status !== "available" && (
        <p className="eval-status eval-unavailable">
          Project artifacts unavailable ({resource.data.reason}).
        </p>
      )}
      {kind === "ready" && resource.data !== null && resource.data.status === "available" && (
        <>
          <p className="artifact-source">{sourceLabel(resource.data.source)}</p>
          {artifactSections(groups).map((section) => (
            <section
              key={section.category}
              id={section.category === "hunting" ? "hunting" : "skills"}
              aria-label={section.label}
            >
              <h2>{section.label}</h2>
              {section.groups.length === 0 ? (
                <p className="eval-status">{EMPTY_LABEL[section.category]}</p>
              ) : (
                section.groups.map((group) => (
                  <ArtifactGroupNode
                    key={groupKey(group)}
                    group={group}
                    detailPath={detailPath}
                    depth={0}
                  />
                ))
              )}
            </section>
          ))}
        </>
      )}
    </div>
  )
}

// The standalone path: the artifacts page owns its own poll. Inside the Trial
// workspace the shared provider answers instead, so the inventory is polled once.
function StandaloneResolvedArtifactsSection({
  targetId,
  targetRunId,
  trialId,
  expectedProjectId,
  detailPath,
}: {
  targetId: string
  targetRunId: string
  trialId: string
  expectedProjectId?: string | null
  detailPath: DetailPath
}) {
  const resource = useResolvedInventory({ targetId, targetRunId, trialId, expectedProjectId })
  return (
    <ResolvedArtifactsView
      resource={resource}
      targetId={targetId}
      targetRunId={targetRunId}
      trialId={trialId}
      detailPath={detailPath}
    />
  )
}

export function ResolvedArtifactsSection({
  targetId,
  targetRunId,
  trialId,
  detailPath,
  expectedProjectId,
}: {
  targetId: string
  targetRunId: string
  trialId: string
  detailPath: DetailPath
  // The project id the Trial record claims. When known, a resolved inventory
  // that names a different project is a safe error, never a silent render.
  expectedProjectId?: string | null
}) {
  const provided = useResolvedArtifactsResource()
  if (provided) {
    return (
      <ResolvedArtifactsView
        resource={provided}
        targetId={targetId}
        targetRunId={targetRunId}
        trialId={trialId}
        detailPath={detailPath}
      />
    )
  }
  return (
    <StandaloneResolvedArtifactsSection
      targetId={targetId}
      targetRunId={targetRunId}
      trialId={trialId}
      expectedProjectId={expectedProjectId}
      detailPath={detailPath}
    />
  )
}
