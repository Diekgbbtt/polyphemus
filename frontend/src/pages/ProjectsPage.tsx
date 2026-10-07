import { useCallback } from "react"
import { Link } from "react-router-dom"
import { getProjects } from "../api/client"
import type { Project } from "../api/types"
import { getSnapshot } from "../eval/client"
import type { EvalSnapshot, UnassignedSavedData } from "../eval/types"
import { formatClockTime, usePolledResource } from "../usePolledResource"
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

function latestOf(timestamps: Array<number | null>): number | null {
  const known = timestamps.filter((value): value is number => value !== null)
  return known.length > 0 ? Math.max(...known) : null
}

// The Target-first home. The eval snapshot is the authoritative Target index;
// the live runtime is loaded independently and contributes only to the
// `Unassigned saved data` diagnostic. Either failure is non-blocking.
//
// Both sources are re-read on the shared cadence, when the tab returns, and on
// the manual button, so a Target or Trial that appears while the page is open
// shows up without a browser refresh. A failing re-read keeps the last catalog
// on screen and only adds a notice.
export function ProjectsPage() {
  const liveResource = usePolledResource<Project[]>({
    key: "live-projects",
    load: (signal) => getProjects(signal),
  })
  const evalResource = usePolledResource<EvalSnapshot>({
    key: "snapshot",
    load: (signal) => getSnapshot(signal),
  })

  const refresh = useCallback(() => {
    liveResource.refresh()
    evalResource.refresh()
  }, [liveResource.refresh, evalResource.refresh])

  const live = liveResource.data
  const snapshot = evalResource.data
  const liveUnavailable = live === null && liveResource.error !== null
  const evalsUnavailable = snapshot === null && evalResource.error !== null
  const liveRefreshFailed = live !== null && liveResource.error !== null
  const evalsRefreshFailed = snapshot !== null && evalResource.error !== null

  const targets = targetCatalog(snapshot)
  const unassigned = unassignedSavedData(live, snapshot)
  const loading =
    live === null && snapshot === null && !liveUnavailable && !evalsUnavailable
  const updatedAt = latestOf([liveResource.lastUpdatedAt, evalResource.lastUpdatedAt])

  return (
    <main className="projects-page">
      <header className="projects-header">
        <GlobalNav active="projects" />
        <h1>Targets</h1>
        <div className="eval-refresh-controls">
          <button type="button" className="eval-refresh" onClick={refresh}>
            Refresh
          </button>
          {updatedAt !== null && (
            <span className="eval-updated">
              Last updated {formatClockTime(updatedAt)}
            </span>
          )}
        </div>
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
      {liveRefreshFailed && (
        <p className="projects-notice" role="status">
          Live runtime refresh failed — showing the last data.
        </p>
      )}
      {evalsRefreshFailed && (
        <p className="projects-notice" role="status">
          Eval refresh failed — showing the last data.
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
