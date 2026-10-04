import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { getProjects } from "../api/client"
import type { Project } from "../api/types"
import { getSnapshot } from "../eval/client"
import type { EvalSnapshot, UnassignedSavedData } from "../eval/types"
import { targetPaths } from "../projectPaths"
import { GlobalNav } from "./ProjectNav"

// The Target catalog: the snapshot's Targets, ordered deterministically. The
// home deliberately does not list one primary row per internal project_id -
// project_id is a storage join key, not a navigation entity.
export interface TargetCatalogEntry {
  target_id: string
  trial_count: number
  identified_count: number
  partial_count: number
  missed_count: number
}

export function targetCatalog(snapshot: EvalSnapshot | null): TargetCatalogEntry[] {
  return [...(snapshot?.targets ?? [])].sort((a, b) =>
    a.target_id.localeCompare(b.target_id),
  )
}

export interface UnassignedEntry {
  project_id: string
  status: "available" | "unavailable"
  hunting: number
  skills: number
  reason?: string
}

// Merge the backend's raw-only directory list with live runtime projects that
// no projected Trial proves belong to a Target. Diagnostic only: no entry ever
// fabricates a Trial link.
export function unassignedSavedData(
  live: Project[] | null,
  snapshot: EvalSnapshot | null,
): UnassignedEntry[] {
  const proven = new Set<string>()
  for (const trial of snapshot?.trials ?? []) {
    if (trial.project_id) proven.add(trial.project_id)
  }
  const rows = new Map<string, UnassignedEntry>()
  for (const raw of snapshot?.unassigned_saved_data ?? ([] as UnassignedSavedData[])) {
    if (proven.has(raw.project_id) || rows.has(raw.project_id)) continue
    rows.set(raw.project_id, {
      project_id: raw.project_id,
      status: raw.status,
      hunting: raw.hunting,
      skills: raw.skills,
      reason: raw.reason,
    })
  }
  for (const project of live ?? []) {
    if (proven.has(project.project_id) || rows.has(project.project_id)) continue
    rows.set(project.project_id, {
      project_id: project.project_id,
      status: "available",
      hunting: 0,
      skills: 0,
    })
  }
  return [...rows.values()].sort((a, b) => a.project_id.localeCompare(b.project_id))
}

// The Target-first home. The eval snapshot is the authoritative Target index;
// the live runtime is loaded independently and contributes only to the
// `Unassigned saved data` diagnostic. Either failure is non-blocking.
export function ProjectsPage() {
  const [live, setLive] = useState<Project[] | null>(null)
  const [snapshot, setSnapshot] = useState<EvalSnapshot | null>(null)
  const [liveUnavailable, setLiveUnavailable] = useState(false)
  const [evalsUnavailable, setEvalsUnavailable] = useState(false)

  useEffect(() => {
    let alive = true
    getProjects()
      .then((projects) => {
        if (alive) setLive(projects)
      })
      .catch(() => {
        if (alive) setLiveUnavailable(true)
      })
    getSnapshot()
      .then((snap) => {
        if (alive) setSnapshot(snap)
      })
      .catch(() => {
        if (alive) setEvalsUnavailable(true)
      })
    return () => {
      alive = false
    }
  }, [])

  const targets = targetCatalog(snapshot)
  const unassigned = unassignedSavedData(live, snapshot)
  const loading =
    live === null && snapshot === null && !liveUnavailable && !evalsUnavailable

  return (
    <main className="projects-page">
      <header className="projects-header">
        <GlobalNav active="projects" />
        <h1>Targets</h1>
      </header>

      {loading && (
        <p className="projects-status" role="status">
          Loading targets…
        </p>
      )}
      {liveUnavailable && (
        <p className="projects-notice" role="status">
          Live runtime unavailable — showing saved eval data only.
        </p>
      )}
      {evalsUnavailable && (
        <p className="projects-notice" role="status">
          Eval results unavailable — saved data is shown where it can be attributed.
        </p>
      )}
      {!loading && targets.length === 0 && (
        <p className="projects-empty">No targets found.</p>
      )}

      <ul className="project-catalog">
        {targets.map((target) => (
          <li key={target.target_id} className="project-entry">
            <div className="project-entry-identity">
              <Link
                to={targetPaths.target(target.target_id)}
                className="project-entry-name eval-ref"
              >
                {target.target_id}
              </Link>
              <span className="project-entry-id">Target</span>
            </div>
            <p className="project-entry-meta">
              {target.trial_count} {target.trial_count === 1 ? "trial" : "trials"} ·{" "}
              {target.identified_count} identified · {target.partial_count} partial ·{" "}
              {target.missed_count} missed
            </p>
            <div className="project-entry-actions">
              <Link to={targetPaths.target(target.target_id)}>Open workspace</Link>
            </div>
          </li>
        ))}
      </ul>

      <section className="unassigned" aria-label="Unassigned saved data">
        <h2>Unassigned saved data</h2>
        <p className="unassigned-note">
          Saved project data with no Trial proving which Target it belongs to. It is
          shown for diagnosis only and is never attributed to a Target.
        </p>
        {unassigned.length === 0 ? (
          <p className="projects-empty">No unassigned saved data.</p>
        ) : (
          <ul className="unassigned-list">
            {unassigned.map((entry) => (
              <li key={entry.project_id} className="project-entry">
                <div className="project-entry-identity">
                  <span className="project-entry-name eval-ref">{entry.project_id}</span>
                  <span className="project-entry-id">Unassigned</span>
                </div>
                <p className="project-entry-meta">
                  {entry.status === "available"
                    ? `${entry.hunting} hunting · ${entry.skills} skills`
                    : `unavailable (${entry.reason ?? "unknown"})`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  )
}
