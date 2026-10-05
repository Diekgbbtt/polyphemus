import { useCallback, useRef } from "react"
import type { GraphData } from "../api/types"
import { GraphView } from "../graph/GraphView"
import { usePolledResource } from "../usePolledResource"
import { getResolvedTrialGraph } from "./client"
import { useEvalRefreshToken } from "./EvalDataProvider"
import type { ResolvedProjectGraph } from "./types"

// The two sources the resolved endpoint reports. The browser never chooses
// between them; it only labels what the server resolved. These are the only
// labels a Trial ever shows, never a schema-version term.
const SOURCE_LABEL: Record<ResolvedProjectGraph["source"], string> = {
  trial_snapshot: "Captured with Trial",
  project_storage: "Saved for project",
}

const NO_GRAPH = "No graph available"

type GraphState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "unavailable" }
  | { kind: "ready"; graph: GraphData; label: string; capturedAt: string | null }

// Turn the resolved wire contract into a render state. Only a graph that
// actually carries nodes is drawn; an empty body and an unavailable contract
// both become the simple missing state, so an empty canvas is never shown.
function readyState(resolved: ResolvedProjectGraph): GraphState {
  if (resolved.status === "available" && resolved.graph.nodes.length > 0) {
    return {
      kind: "ready",
      graph: resolved.graph,
      label: SOURCE_LABEL[resolved.source],
      capturedAt: resolved.captured_at,
    }
  }
  return { kind: "unavailable" }
}

// Wire-level equality, so a poll that returns the same graph keeps the previous
// object. A new object would hand the canvas a new `nodes` array and silently
// reset the reader's zoom and layer selection.
function sameResolved(a: ResolvedProjectGraph, b: ResolvedProjectGraph): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

// The graph section of one Trial.
//
// It consumes only the resolved Trial endpoint: the server decides between the
// immutable capture written beside the Trial and the matching instance's
// current project graph, and reports which one it used. The component never
// calls the live agent graph client, so a Trial from another instance can never
// reach this server's project data.
//
// The section re-reads itself on the shared cadence (and on a manual refresh),
// retrying while the graph is unavailable. A capture written with the Trial is
// history: it is read once and then held, never swapped for the mutable project
// graph. A failure never blanks the section - the previous graph stays with a
// soft notice.
export function TrialProjectGraph({
  targetId,
  targetRunId,
  trialId,
}: {
  targetId: string
  targetRunId: string
  trialId: string
}) {
  const refreshToken = useEvalRefreshToken()
  // The full identity of this section instance, so a ref from a previous Trial
  // is never mistaken for this one's.
  const identity = `${targetId}\u0000${targetRunId}\u0000${trialId}`
  const frozen = useRef<{ identity: string; resolved: ResolvedProjectGraph } | null>(null)
  const last = useRef<{ identity: string; resolved: ResolvedProjectGraph } | null>(null)

  const load = useCallback(
    async (signal: AbortSignal): Promise<ResolvedProjectGraph> => {
      if (frozen.current && frozen.current.identity === identity) {
        return frozen.current.resolved
      }
      const resolved = await getResolvedTrialGraph(targetId, targetRunId, trialId, signal)
      if (resolved.status === "available" && resolved.source === "trial_snapshot") {
        frozen.current = { identity, resolved }
        last.current = { identity, resolved }
        return resolved
      }
      const previous =
        last.current && last.current.identity === identity ? last.current.resolved : null
      if (previous && sameResolved(previous, resolved)) return previous
      last.current = { identity, resolved }
      return resolved
    },
    [identity, targetId, targetRunId, trialId],
  )

  const resource = usePolledResource<ResolvedProjectGraph>({
    key: identity,
    load,
    refreshToken,
  })

  const state: GraphState = resource.loading
    ? { kind: "loading" }
    : resource.data
      ? readyState(resource.data)
      : { kind: "error", message: resource.error ?? "unknown" }

  return (
    <section aria-label="Graph" className="project-trial-section">
      <h2>Graph</h2>
      {state.kind === "loading" && <p>Loading graph...</p>}
      {state.kind === "error" && <p role="alert">Graph error: {state.message}</p>}
      {state.kind === "unavailable" && <p className="eval-status">{NO_GRAPH}</p>}
      {state.kind === "ready" && (
        <GraphView
          data={state.graph}
          loading={false}
          error={null}
          label={state.label}
          capturedAt={state.capturedAt}
        />
      )}
      {resource.data !== null && resource.error !== null && (
        <p className="eval-status" role="status">
          Graph refresh failed: {resource.error}. Showing the previous graph.
        </p>
      )}
    </section>
  )
}
