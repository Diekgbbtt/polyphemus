import { useCallback } from "react"
import { getProjectUsage } from "../api/client"
import type { ProjectUsage, UsageTokens } from "../api/types"
import { usePolledResource } from "../usePolledResource"

// The endpoint's cumulative counters are non-negative integers; a string, a
// negative, a fraction or a null is a contract violation, never a value to
// coerce. This is the same verified wire contract RunsPage enforces, kept local
// so the summary never invents a partial reading.
function isCounter(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

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

// A body that does not carry the full contract is unavailable, so a missing or
// malformed reading is never rendered - and never coerced to zero.
export function isValidProjectUsage(value: unknown): value is ProjectUsage {
  if (!isPlainObject(value)) return false
  if (typeof value.project_id !== "string" || value.project_id.length === 0) return false
  if (!isUsageTokens(value)) return false
  if (!isPlainObject(value.by_agent)) return false
  return Object.values(value.by_agent).every(isUsageTokens)
}

const UNAVAILABLE = "Unavailable"
const LOADING = "Loading…"

// What the chip renders. `ready` keeps the last reading even across a failed
// refresh, flagged `stale`; a first read that never succeeded is `unavailable`,
// which is never rendered as zero.
type SummaryState =
  | { status: "loading" }
  | { status: "unavailable" }
  | { status: "ready"; usage: ProjectUsage; stale: boolean }

// The project's cumulative token spend, shown beside the Trial's
// identified/partial/missed outcome and expandable to the per-agent breakdown.
//
// It is the PROJECT's ledger, cumulative since the backend started: not a
// single Trial's spend, and never summed across Trials that share a project.
// `projectId` is the resource identity - the reader is keyed by it, so a switch
// to another project mounts a fresh reader and the previous project's counters
// can never appear under the new one.
export function ProjectUsageSummary({ projectId }: { projectId: string | null }) {
  // A Trial with no project has nothing to attribute usage to; it never fetches.
  if (!projectId) return <UsageChip state={{ status: "unavailable" }} />
  return <PolledProjectUsage key={projectId} projectId={projectId} />
}

function PolledProjectUsage({ projectId }: { projectId: string }) {
  const load = useCallback(
    async (signal: AbortSignal) => {
      const body = (await getProjectUsage(projectId, signal)) as unknown
      // An invalid body is a failure, not a zero: the previous reading is kept
      // and the chip is marked stale.
      if (!isValidProjectUsage(body)) throw new Error("invalid usage body")
      return body
    },
    [projectId],
  )
  const { data, error, loading } = usePolledResource<ProjectUsage>({
    key: projectId,
    load,
  })

  let state: SummaryState
  if (data) state = { status: "ready", usage: data, stale: error !== null }
  else if (error) state = { status: "unavailable" }
  else if (loading) state = { status: "loading" }
  else state = { status: "unavailable" }

  return <UsageChip state={state} />
}

function UsageChip({ state }: { state: SummaryState }) {
  const total =
    state.status === "ready"
      ? String(state.usage.total_tokens)
      : state.status === "loading"
        ? LOADING
        : UNAVAILABLE

  return (
    <li className="eval-chip eval-chip-usage">
      <span className="eval-chip-label">Project tokens</span>
      <span className="eval-chip-value" data-project-tokens>
        {total}
      </span>
      {/* Kept beside the total, outside the disclosure, so a stale reading is
          visible without opening the per-agent breakdown. */}
      {state.status === "ready" && state.stale && (
        <span className="eval-usage-stale">
          Usage not up to date — showing the last reading.
        </span>
      )}
      <details className="eval-usage-details">
        <summary className="eval-usage-summary">Usage by agent</summary>
        <div className="eval-usage-panel">
          <p className="eval-usage-note">
            Cumulative tokens for this project since the backend started — they
            are not this Trial&rsquo;s spend and are not summed across Trials.
          </p>
          {state.status === "ready" ? (
            <AgentBreakdown usage={state.usage} />
          ) : (
            <p className="eval-usage-unavailable">
              {state.status === "loading"
                ? "Loading project usage…"
                : "Project usage unavailable."}
            </p>
          )}
        </div>
      </details>
    </li>
  )
}

// One row per agent: total tokens, the context (input) and generated (output)
// splits, and the call count.
function AgentBreakdown({ usage }: { usage: ProjectUsage }) {
  const agents = Object.entries(usage.by_agent).sort(([a], [b]) => a.localeCompare(b))
  if (agents.length === 0) {
    return <p className="eval-usage-unavailable">No per-agent usage was recorded.</p>
  }
  return (
    <table className="eval-usage-agents">
      <caption>Breakdown by agent</caption>
      <thead>
        <tr>
          <th scope="col">Agent</th>
          <th scope="col">Total tokens</th>
          <th scope="col">Cached input</th>
          <th scope="col">Uncached input</th>
          <th scope="col">Reasoning output</th>
          <th scope="col">Visible output</th>
          <th scope="col">Calls</th>
        </tr>
      </thead>
      <tbody>
        {agents.map(([agent, tokens]) => (
          <tr key={agent}>
            <th scope="row">{agent}</th>
            <td>{tokens.total_tokens}</td>
            <td>{tokens.context_tokens.cached}</td>
            <td>{tokens.context_tokens.uncached}</td>
            <td>{tokens.generated_tokens.reasoning}</td>
            <td>{tokens.generated_tokens.visible}</td>
            <td>{tokens.calls}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
