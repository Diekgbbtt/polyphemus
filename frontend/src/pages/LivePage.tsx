import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { getAppState, getProjectUsage } from "../api/client"
import type { AppState, ProjectState, ProjectUsage } from "../api/types"
import { projectPaths } from "../projectPaths"
import { GlobalNav } from "./ProjectNav"

// The board polls a bounded, read-only surface; 2.5s matches the Runs page.
const POLL_MS = 2500
// Every read is bounded: a request that hangs is aborted and its slot freed so
// the next update can retry, instead of wedging the board forever.
const REQUEST_TIMEOUT_MS = 10_000

const RUN_KINDS = ["recon", "analysis", "hunting"] as const
type RunKind = (typeof RUN_KINDS)[number]

// One normalized run row: every run class has its own id field and only recon
// carries a liveness verdict, so the view reads this shape, not three.
interface RunRow {
  id: string
  status: string
  liveness: "live" | "stalled" | null
  phase: number | null
}

// The active runs of one project, grouped by class. A class with no runs is
// dropped entirely so a project shows only what is actually executing.
export function activeRuns(project: ProjectState, kind: RunKind): RunRow[] {
  if (kind === "recon") {
    return project.recon.map((run) => ({
      id: run.run_id,
      status: run.status,
      liveness: run.liveness,
      phase: run.current_phase,
    }))
  }
  if (kind === "analysis") {
    return project.analysis.map((run) => ({
      id: run.analysis_run_id,
      status: run.status,
      liveness: null,
      phase: null,
    }))
  }
  return project.hunting.map((run) => ({
    id: run.hunting_run_id,
    status: run.status,
    liveness: null,
    phase: null,
  }))
}

// The current endpoint reports the project-wide context and output splits.
export function usageTotals(usage: ProjectUsage): { input: number; output: number } {
  return {
    input: usage.context_tokens.cached + usage.context_tokens.uncached,
    output: usage.generated_tokens.reasoning + usage.generated_tokens.visible,
  }
}

// One project's usage as of the last successful read. `stale` marks a snapshot
// kept across a failed refresh: the numbers stay visible rather than being
// blanked to zero, and the marker says they may be out of date.
interface UsageEntry {
  snapshot: ProjectUsage | null
  error: boolean
  stale: boolean
}

// The outcome of one bounded read: success, or any failure (a real error, a
// timeout, or an unmount-time abort). The view treats a failed refresh the same
// way - keep the last reading if there is one, else show the error.
type Attempt<T> = { ok: true; value: T } | { ok: false; reason: "timeout" | "error" }

// The global live board: every project with something in flight, its active
// recon/analysis/hunting runs, and its cumulative token spend. Every read is
// independent - the state poll never waits on a usage read, and one project's
// usage read never waits on another's.
export function LivePage() {
  const [appState, setAppState] = useState<AppState | null>(null)
  const [appStateError, setAppStateError] = useState(false)
  const [loading, setLoading] = useState(true)
  const [usage, setUsage] = useState<Record<string, UsageEntry>>({})

  useEffect(() => {
    let alive = true
    // One controller aborts every in-flight request at unmount; each request
    // also gets its own controller so a timeout aborts just that one.
    const master = new AbortController()
    const timers = new Set<ReturnType<typeof setTimeout>>()
    // In-flight guards: one for the shared state read, one slot per project.
    // A pending request never blocks a different endpoint or another project.
    let appStateInFlight = false
    const usageInFlight = new Set<string>()

    // Run one request under a 10s deadline and the unmount signal, returning a
    // value instead of throwing so callers never need a try/catch.
    const attempt = async <T,>(
      run: (signal: AbortSignal) => Promise<T>,
    ): Promise<Attempt<T>> => {
      const controller = new AbortController()
      let timedOut = false
      const onMasterAbort = () => controller.abort()
      master.signal.addEventListener("abort", onMasterAbort)
      const timeout = setTimeout(() => {
        timedOut = true
        controller.abort()
      }, REQUEST_TIMEOUT_MS)
      timers.add(timeout)
      try {
        const value = await run(controller.signal)
        return { ok: true, value }
      } catch {
        return timedOut ? { ok: false, reason: "timeout" } : { ok: false, reason: "error" }
      } finally {
        clearTimeout(timeout)
        timers.delete(timeout)
        master.signal.removeEventListener("abort", onMasterAbort)
      }
    }

    // Each project's usage read settles on its own and updates only its own
    // entry the moment it lands - never waiting on its siblings.
    const pollUsage = async (projectId: string) => {
      if (usageInFlight.has(projectId)) return
      usageInFlight.add(projectId)
      const result = await attempt((signal) =>
        getProjectUsage(projectId, signal),
      ).finally(() => {
        // Always release the slot, whatever the outcome.
        usageInFlight.delete(projectId)
      })
      if (!alive) return
      setUsage((previous) => {
        const next = { ...previous }
        if (result.ok) {
          next[projectId] = { snapshot: result.value, error: false, stale: false }
        } else {
          // Keep the last good numbers and flag them; never write zeros over a
          // real reading just because the refresh failed.
          const last = previous[projectId]?.snapshot ?? null
          next[projectId] = { snapshot: last, error: true, stale: last !== null }
        }
        return next
      })
    }

    const pollAppState = async () => {
      if (appStateInFlight) return
      appStateInFlight = true
      const result = await attempt((signal) => getAppState(signal)).finally(() => {
        // The state read is done here; it must not wait on the usage reads.
        appStateInFlight = false
      })
      if (!alive) return
      if (result.ok) {
        setAppState(result.value)
        setAppStateError(false)
        setLoading(false)
        // Fan out, but do not await: a slow project never holds back the others
        // nor the next state poll.
        for (const project of result.value.projects) {
          if (project.in_flight) void pollUsage(project.project_id)
        }
      } else {
        setAppStateError(true)
        setLoading(false)
      }
    }

    void pollAppState()
    const handle = setInterval(() => {
      void pollAppState()
    }, POLL_MS)
    return () => {
      alive = false
      clearInterval(handle)
      // Abort every in-flight read and drop every timer, including the 10s
      // deadlines, so nothing fires against an unmounted tree.
      master.abort()
      for (const timer of timers) clearTimeout(timer)
      timers.clear()
    }
  }, [])

  const active = (appState?.projects ?? []).filter((project) => project.in_flight)

  return (
    <main className="live-page">
      <header className="live-header">
        <GlobalNav active="live" />
        <h1>Live</h1>
        <p className="live-intro">
          Token spend is cumulative per project since the backend started, and
          is refreshed after each model call.
        </p>
      </header>

      {loading && (
        <p className="live-status" role="status">
          Loading live projects…
        </p>
      )}
      {appStateError && (
        <p className="live-notice live-notice--error" role="alert">
          Live state unavailable — could not reach the agent.
        </p>
      )}
      {!loading && !appStateError && active.length === 0 && (
        <p className="live-empty">No projects in flight.</p>
      )}

      <ul className="live-projects">
        {active.map((project) => (
          <li
            key={project.project_id}
            className="live-project"
            data-project-id={project.project_id}
          >
            <div className="live-project-head">
              <h2 className="live-project-name">
                {project.project_name ?? project.project_id}
                <span className="live-project-id">{project.project_id}</span>
              </h2>
              <Link to={projectPaths.live(project.project_id)}>Open graph</Link>
            </div>

            {RUN_KINDS.map((kind) => {
              const runs = activeRuns(project, kind)
              if (runs.length === 0) return null
              return (
                <section
                  key={kind}
                  className={`live-run-group live-run-group--${kind}`}
                  aria-label={`${kind} runs`}
                >
                  <h3 className="live-run-group-title">{kind}</h3>
                  <ul className="live-run-list">
                    {runs.map((run) => (
                      <li key={run.id} className="live-run">
                        <span className="live-run-id">{run.id}</span>
                        <span className="live-run-status">{run.status}</span>
                        {run.phase !== null && (
                          <span className="live-run-phase">phase {run.phase}</span>
                        )}
                        {run.liveness !== null && (
                          <span className="live-run-liveness" data-liveness={run.liveness}>
                            {run.liveness}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )
            })}

            <ProjectUsageView entry={usage[project.project_id]} />
          </li>
        ))}
      </ul>
    </main>
  )
}

// The per-project usage read: its own loading / error / stale states, isolated
// from every other project and from the app-state read.
function ProjectUsageView({ entry }: { entry?: UsageEntry }) {
  if (entry?.snapshot) {
    const { input, output } = usageTotals(entry.snapshot)
    return (
      <div className="live-usage" aria-label="Token usage">
        <h3 className="live-usage-title">Token usage</h3>
        <dl className="live-usage-stats">
          <div>
            <dt>Total tokens</dt>
            <dd>{entry.snapshot.total_tokens}</dd>
          </div>
          <div>
            <dt>Input</dt>
            <dd>{input}</dd>
          </div>
          <div>
            <dt>Output</dt>
            <dd>{output}</dd>
          </div>
          <div>
            <dt>Calls</dt>
            <dd>{entry.snapshot.calls}</dd>
          </div>
        </dl>
        {entry.stale && (
          <p className="live-usage-stale" role="status">
            Usage not up to date — showing the last reading.
          </p>
        )}
      </div>
    )
  }
  if (entry?.error) {
    return (
      <p className="live-usage-error" role="alert">
        Token usage unavailable.
      </p>
    )
  }
  return <p className="live-usage-loading">Loading token usage…</p>
}
