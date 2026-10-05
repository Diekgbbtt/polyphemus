import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { getProjectUsage, getRunningRuns } from "../api/client"
import type { ProjectUsage, RunningRun, UsageTokens } from "../api/types"
import { projectPaths } from "../projectPaths"
import { ProjectNav } from "./ProjectNav"

// The live poll cadence for both the run list and the project's usage snapshot.
const POLL_MS = 2500

// The endpoint's cumulative counters are integers; a non-integer, a negative, a
// string or a null is a contract violation, never a value to coerce.
function isCounter(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

// One token distribution: the context split, the generated split, the total,
// the total minus cache reads, and the call count.
function isUsageTokens(value: unknown): value is UsageTokens {
  if (!isPlainObject(value)) return false
  const context = value.context_tokens
  const generated = value.generated_tokens
  if (!isPlainObject(context) || !isPlainObject(generated)) return false
  return (
    isCounter(context.cached) &&
    isCounter(context.uncached) &&
    isCounter(generated.reasoning) &&
    isCounter(generated.visible) &&
    isCounter(value.total_tokens) &&
    isCounter(value.capped_tokens) &&
    isCounter(value.calls)
  )
}

// The verified wire contract, in full: a body that does not carry it (missing or
// malformed nested blocks, invalid counters, a non-object breakdown) is treated
// as unavailable, so it never renders as a partial, invented reading.
function isValidUsage(value: unknown): value is ProjectUsage {
  if (!isPlainObject(value)) return false
  if (typeof value.project_id !== "string" || value.project_id.length === 0) return false
  if (!isUsageTokens(value)) return false
  const byAgent = value.by_agent
  if (!isPlainObject(byAgent)) return false
  return Object.values(byAgent).every(isUsageTokens)
}

// What the panel renders for the *current* project. The state is keyed by the
// project id, so switching projects immediately drops the previous project's
// counters (no stale reading ever shows under a different project).
type UsageView =
  | { status: "pending" }
  | { status: "unavailable" }
  | { status: "ready"; usage: ProjectUsage }

const COUNTERS: { field: string; label: string }[] = [
  { field: "cached", label: "Contesto cached" },
  { field: "uncached", label: "Contesto uncached" },
  { field: "reasoning", label: "Output reasoning" },
  { field: "visible", label: "Output visibile" },
  { field: "total", label: "Token totali, cache inclusa" },
  { field: "capped", label: "Token esclusi i cache read" },
  { field: "calls", label: "Chiamate" },
]

function counters(tokens: UsageTokens): Record<string, number> {
  return {
    cached: tokens.context_tokens.cached,
    uncached: tokens.context_tokens.uncached,
    reasoning: tokens.generated_tokens.reasoning,
    visible: tokens.generated_tokens.visible,
    total: tokens.total_tokens,
    capped: tokens.capped_tokens,
    calls: tokens.calls,
  }
}

// The current project's cumulative token usage, read from the app's in-memory
// ledger. Every counter is attributed to the PROJECT (the endpoint carries no
// per-run attribution) and is cumulative since the agent started, so it is
// labelled "Usage corrente progetto" - never the current context size. Each poll
// REPLACES the previous snapshot; nothing is summed across polls or calls, and
// every value shown is returned by the endpoint (zero included).
function UsagePanel({ view }: { view: UsageView }) {
  return (
    <section className="runs-usage" aria-label="Usage corrente progetto">
      <h2>Usage corrente progetto</h2>
      <p className="runs-usage-note">
        Contatori cumulativi del progetto dall&rsquo;avvio dell&rsquo;agent; non rappresentano la
        dimensione del contesto corrente.
      </p>
      {view.status === "unavailable" && (
        <p className="runs-usage-unavailable" role="status">
          Usage non disponibile.
        </p>
      )}
      {view.status === "ready" && <UsageCounters usage={view.usage} />}
    </section>
  )
}

function UsageCounters({ usage }: { usage: ProjectUsage }) {
  const project = counters(usage)
  const agents = Object.entries(usage.by_agent).sort(([a], [b]) => a.localeCompare(b))
  return (
    <>
      <dl className="runs-usage-totals">
        {COUNTERS.map(({ field, label }) => (
          <div key={field}>
            <dt>{label}</dt>
            <dd data-usage={field}>{project[field]}</dd>
          </div>
        ))}
      </dl>
      {agents.length > 0 && (
        <div className="runs-usage-table">
          <table className="runs-usage-agents">
            <caption>Breakdown per agente</caption>
            <thead>
              <tr>
                <th scope="col">Agente</th>
                {COUNTERS.map(({ field, label }) => (
                  <th scope="col" key={field}>
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {agents.map(([agent, tokens]) => {
                const values = counters(tokens)
                return (
                  <tr key={agent}>
                    <th scope="row">{agent}</th>
                    {COUNTERS.map(({ field }) => (
                      <td key={field}>{values[field]}</td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

export function RunsPage() {
  const { projectId = "" } = useParams()
  const [runs, setRuns] = useState<RunningRun[]>([])
  const [entry, setEntry] = useState<{ projectId: string; view: UsageView } | null>(null)

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
          if (alive) setEntry({ projectId, view: { status: "ready", usage: snapshot } })
        } catch {
          if (alive && !controller.signal.aborted) {
            setEntry({ projectId, view: { status: "unavailable" } })
          }
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
  // The panel only ever renders a reading that belongs to the project on
  // screen; a project switch falls back to the pending state immediately.
  const view: UsageView =
    entry && entry.projectId === projectId ? entry.view : { status: "pending" }
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
      <UsagePanel view={view} />
    </main>
  )
}
