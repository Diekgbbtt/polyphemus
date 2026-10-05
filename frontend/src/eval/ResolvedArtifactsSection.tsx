import { useCallback } from "react"
import { Link } from "react-router-dom"
import { usePolledResource } from "../usePolledResource"
import { getResolvedArtifacts } from "./client"
import { useEvalRefreshToken } from "./EvalDataProvider"
import {
  artifactKey,
  artifactSections,
  groupKey,
  groupLabel,
  kindLabel,
  representationLabel,
  sourceLabel,
  withTestSpecSides,
} from "./projectArtifacts"
import type { ProjectArtifactGroup, ResolvedArtifactInventory } from "./types"

export type DetailPath = (artifactId: string) => string

const EMPTY_LABEL: Record<"hunting" | "skill", string> = {
  hunting: "No Hunting artifacts",
  skill: "No Skill artifacts",
}

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

type InventoryState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; inventory: ResolvedArtifactInventory }

// The Hunting and Skill artifact inventory of one Trial.
//
// Like the graph section it consumes only the resolved endpoint, which prefers
// the immutable capture and otherwise reads the allowlisted raw project
// directory. It loads the inventory only: no artifact detail or content is
// fetched until the reader opens one. A zero-entry readable inventory shows
// both sections with an explicit empty state rather than a misleading
// unavailable message, and a failure stays inside this section.
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
  const refreshToken = useEvalRefreshToken()
  const identity = `${targetId}\u0000${targetRunId}\u0000${trialId}\u0000${expectedProjectId ?? ""}`

  const load = useCallback(
    async (signal: AbortSignal): Promise<ResolvedArtifactInventory> => {
      const inventory = await getResolvedArtifacts(targetId, targetRunId, trialId, signal)
      // A resolved inventory that names a different project is a safe error,
      // never a silent render, and never a fallback to another source.
      if (expectedProjectId && inventory.project_id !== expectedProjectId) {
        throw new Error("Artifact inventory does not match this Trial (mismatch).")
      }
      return inventory
    },
    [targetId, targetRunId, trialId, expectedProjectId],
  )

  const resource = usePolledResource<ResolvedArtifactInventory>({
    key: identity,
    load,
    refreshToken,
  })

  const state: InventoryState = resource.loading
    ? { kind: "loading" }
    : resource.data
      ? { kind: "ready", inventory: resource.data }
      : { kind: "error", message: resource.error ?? "unknown" }

  return (
    <div className="resolved-artifacts">
      {state.kind === "loading" && <p className="eval-status">Loading artifacts…</p>}
      {state.kind === "error" && (
        <p className="eval-error" role="alert">
          Artifact load error: {state.message}
        </p>
      )}
      {resource.data !== null && resource.error !== null && (
        <p className="eval-status" role="status">
          Artifact refresh failed: {resource.error}. Showing the previous inventory.
        </p>
      )}
      {state.kind === "ready" && state.inventory.status !== "available" && (
        <p className="eval-status eval-unavailable">
          Project artifacts unavailable ({state.inventory.reason}).
        </p>
      )}
      {state.kind === "ready" && state.inventory.status === "available" && (
        <>
          <p className="artifact-source">{sourceLabel(state.inventory.source)}</p>
          {artifactSections(withTestSpecSides(state.inventory.groups)).map((section) => (
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
