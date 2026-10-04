import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { getProjects } from "../api/client"
import type { Project } from "../api/types"
import { getSnapshot } from "../eval/client"
import type { EvalSnapshot, EvalTrial } from "../eval/types"
import { projectPaths } from "../projectPaths"
import { GlobalNav } from "./ProjectNav"

export interface CatalogEntry {
  project_id: string
  name: string
  hasLive: boolean
  hasEvals: boolean
  latestTrial?: EvalTrial
}

// The newest Trial for one project, by the same key ProjectEvalsPage sorts on:
// the captured graph time when present, else the copy time, else the identity.
function newerTrial(current: EvalTrial | undefined, candidate: EvalTrial): EvalTrial {
  if (!current) return candidate
  const left = current.project_graph_summary.captured_at ?? current.copied_at ?? ""
  const right = candidate.project_graph_summary.captured_at ?? candidate.copied_at ?? ""
  if (left !== right) return left < right ? candidate : current
  const id = (trial: EvalTrial) => `${trial.target_id}/${trial.target_run_id}/${trial.trial_id}`
  return id(candidate) < id(current) ? candidate : current
}

// Merge the two independent sources into one card per project_id. A null live
// list (the runtime is unavailable) simply contributes no live side; the
// eval-derived projects still stand on their own.
export function buildCatalog(
  live: Project[] | null,
  snapshot: EvalSnapshot | null,
): CatalogEntry[] {
  const byId = new Map<string, CatalogEntry>()
  for (const project of live ?? []) {
    byId.set(project.project_id, {
      project_id: project.project_id,
      name: project.name || project.project_id,
      hasLive: true,
      hasEvals: false,
    })
  }
  for (const trial of snapshot?.trials ?? []) {
    const projectId = trial.project_id
    if (!projectId) continue
    let entry = byId.get(projectId)
    if (!entry) {
      entry = { project_id: projectId, name: projectId, hasLive: false, hasEvals: false }
      byId.set(projectId, entry)
    }
    entry.hasEvals = true
    entry.latestTrial = newerTrial(entry.latestTrial, trial)
  }
  return [...byId.values()].sort((a, b) =>
    a.name === b.name ? a.project_id.localeCompare(b.project_id) : a.name.localeCompare(b.name),
  )
}

// The one visible source label for a catalog entry: which sources actually
// back this project. The text carries the meaning, so the badge's colour is
// never the only indicator.
export function projectSource(entry: Pick<CatalogEntry, "hasLive" | "hasEvals">): {
  label: string
  modifier: string
} {
  if (entry.hasLive && entry.hasEvals) {
    return { label: "Live + Eval", modifier: "live-eval" }
  }
  if (entry.hasEvals) return { label: "Eval only", modifier: "eval-only" }
  return { label: "Live only", modifier: "live-only" }
}

// The unified project catalog. It loads the live runtime and the eval snapshot
// independently: either can fail without blanking the page, and an eval-only
// project links to its eval workspace rather than an unavailable live graph.
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

  const catalog = buildCatalog(live, snapshot)
  const loading = live === null && snapshot === null && !liveUnavailable && !evalsUnavailable

  return (
    <main className="projects-page">
      <header className="projects-header">
        <GlobalNav active="projects" />
        <h1>Projects</h1>
      </header>

      {loading && (
        <p className="projects-status" role="status">
          Loading projects…
        </p>
      )}
      {liveUnavailable && (
        <p className="projects-notice" role="status">
          Live runtime unavailable — showing eval projects only.
        </p>
      )}
      {evalsUnavailable && (
        <p className="projects-notice" role="status">
          Eval results unavailable — showing live projects only.
        </p>
      )}
      {!loading && catalog.length === 0 && (
        <p className="projects-empty">No projects found.</p>
      )}

      <ul className="project-catalog">
        {catalog.map((entry) => {
          // Eval-bearing projects open their eval workspace; a live-only project
          // opens its live graph. An eval-only project never links the (absent)
          // live graph.
          const workspace = entry.hasEvals
            ? projectPaths.evals(entry.project_id)
            : projectPaths.live(entry.project_id)
          const latest = entry.latestTrial
          const source = projectSource(entry)
          return (
            <li key={entry.project_id} className="project-entry">
              <div className="project-entry-identity">
                <h2 className="project-entry-name">
                  <Link to={workspace}>{entry.name}</Link>
                  <span
                    className={`project-entry-badge project-entry-badge--${source.modifier}`}
                  >
                    {source.label}
                  </span>
                </h2>
                <span className="project-entry-id eval-ref">{entry.project_id}</span>
              </div>
              <div className="project-entry-actions">
                {entry.hasEvals && (
                  <Link to={projectPaths.evals(entry.project_id)}>Evaluations</Link>
                )}
                {latest && (
                  <Link
                    to={projectPaths.trial(
                      entry.project_id,
                      latest.target_id,
                      latest.target_run_id,
                      latest.trial_id,
                    )}
                  >
                    Latest trial
                  </Link>
                )}
                {entry.hasLive && (
                  <Link to={projectPaths.live(entry.project_id)}>Live graph</Link>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </main>
  )
}
