import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { getProjectUsage, getRunningRuns } from "../api/client"
import type { ProjectUsage, RunningRun } from "../api/types"
import { projectPaths } from "../projectPaths"
import { ProjectNav } from "./ProjectNav"

// The live poll cadence for both the run list and the project's usage snapshot.
const POLL_MS = 2500

// A defensive shape check: a body that is not the verified usage contract is
// treated as unavailable, so a malformed response never blanks the run list.
function isValidUsage(value: ProjectUsage | null): value is ProjectUsage {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof value.total_tokens === "number" &&
    typeof value.calls === "number" &&
    value.by_agent !== null &&
    typeof value.by_agent === "object"
  )
}

// The current project's cumulative token usage, read from the app's in-memory
// ledger. The counter is attributed to the PROJECT, not a run (the endpoint
// carries no per-run attribution), and it resets with the app process, so it is
// labelled "Usage corrente progetto" - never "current context". Each poll
// REPLACES the previous snapshot; the per-call inputs are never summed.
function UsagePanel({ usage, unavailable }: { usage: ProjectUsage | null; unavailable: boolean }) {
  return (
    <section className="runs-usage" aria-label="Usage corrente progetto">
      <h2>Usage corrente progetto</h2>
      {(unavailable || usage === null) && (
        <p className="runs-usage-unavailable" role="status">
          Usage non disponibile.
        </p>
      )}
      {!unavailable && usage !== null && (
        <dl className="runs-usage-totals">
          <div>
            <dt>Token totali</dt>
            <dd data-usage="total">{usage.total_tokens}</dd>
          </div>
          <div>
            <dt>Chiamate</dt>
            <dd data-usage="calls">{usage.calls}</dd>
          </div>
        </dl>
      )}
      {!unavailable && usage !== null && Object.keys(usage.by_agent).length > 0 && (
        <table className="runs-usage-agents">
          <caption>Breakdown per agente</caption>
          <thead>
            <tr>
              <th scope="col">Agente</th>
              <th scope="col">Input</th>
              <th scope="col">Output</th>
              <th scope="col">Totali</th>
              <th scope="col">Chiamate</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(usage.by_agent)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([agent, entry]) => (
                <tr key={agent}>
                  <th scope="row">{agent}</th>
                  <td>{entry.input_tokens}</td>
                  <td>{entry.output_tokens}</td>
                  <td>{entry.total_tokens}</td>
                  <td>{entry.calls}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

export function RunsPage() {
  const { projectId = "" } = useParams()
  const [runs, setRuns] = useState<RunningRun[]>([])
  const [usage, setUsage] = useState<ProjectUsage | null>(null)
  const [usageUnavailable, setUsageUnavailable] = useState(false)

  useEffect(() => {
    let alive = true
    // One controller per project: switching project (or unmounting) aborts the
    // in-flight requests, and `alive` drops any response that still lands, so a
    // stale project's usage can never overwrite the current one.
    const controller = new AbortController()
    let inFlight = false
    const tick = async () => {
      // Never start a poll while the previous one is still in flight.
      if (inFlight) return
      inFlight = true
      try {
        try {
          const response = await getRunningRuns(controller.signal)
          if (alive) setRuns(response.runs)
        } catch {
          // A run-list error keeps the previous list; it never blanks the page.
        }
        try {
          const snapshot = await getProjectUsage(projectId, controller.signal)
          if (!isValidUsage(snapshot)) throw new Error("invalid usage body")
          if (alive) {
            setUsage(snapshot)
            setUsageUnavailable(false)
          }
        } catch {
          if (alive && !controller.signal.aborted) setUsageUnavailable(true)
        }
      } finally {
        inFlight = false
      }
    }
    tick()
    const handle = setInterval(tick, POLL_MS)
    return () => {
      alive = false
      controller.abort()
      clearInterval(handle)
    }
  }, [projectId])

  const mine = runs.filter((r) => r.project_id === projectId)
  return (
    <main className="projects-page">
      <header className="projects-header">
        <Link to={projectPaths.live(projectId)}>back to graph</Link>
        <ProjectNav projectId={projectId} active="runs" />
      </header>
      <h1>Running recon runs</h1>
      {mine.length === 0 && <p className="projects-empty">No running runs.</p>}
      <ul className="project-catalog">
        {mine.map((r) => (
          <li key={r.run_id} className="project-entry">
            <span className="project-entry-identity">
              <span className="project-entry-name">{r.run_id.slice(0, 8)}</span>
              <span data-liveness={r.liveness} className="project-entry-meta">
                [{r.liveness}]
              </span>
            </span>
            <span className="project-entry-meta">
              phase {r.current_phase ?? "-"} - {r.jobs.success}/{r.jobs.total} jobs
            </span>
          </li>
        ))}
      </ul>
      <UsagePanel usage={usage} unavailable={usageUnavailable} />
    </main>
  )
}
