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
const TIMEOUT_MESSAGE = "Graph read timed out. It retries on the next refresh."
const NOT_FOUND_MESSAGE = "Project not available in the graph source."
const LAST_GRAPH_NOTICE = "Graph refresh failed; showing the last loaded graph."

// The SPA waits longer than the server's own read bound (max 30 s) so a
// slow-but-successful read of a large graph is never cut early by the poller.
// This is local to the graph; the shared poller default is unchanged.
const GRAPH_REQUEST_TIMEOUT_MS = 45_000

// Reasons a read failed *temporarily*: the last loaded graph for the SAME Trial
// is kept on screen (with a notice) instead of blanking the canvas.
const TEMPORARY_REASONS = new Set([
  "project_graph_timeout",
  "project_graph_transport_error",
  "project_graph_http_error",
])

type GraphState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "empty" }
  | { kind: "timeout" }
  | { kind: "notFound" }
  | { kind: "technical"; reason: string; temporary: boolean }
  | { kind: "ready"; graph: GraphData; label: string; capturedAt: string | null }

// Turn the resolved wire contract into a render state. A valid but empty graph
// is a distinct "empty" answer; a timeout, a project missing from the source and
// a technical failure are each their own state, so an access problem is never
// shown as "no graph available".
function readyState(resolved: ResolvedProjectGraph): GraphState {
  if (resolved.status === "available" && resolved.graph.nodes.length > 0) {
    return {
      kind: "ready",
      graph: resolved.graph,
      label: SOURCE_LABEL[resolved.source],
      capturedAt: resolved.captured_at,
    }
  }
  if (resolved.status === "available") return { kind: "empty" }
  switch (resolved.reason) {
    case "project_graph_empty":
      return { kind: "empty" }
    case "project_graph_timeout":
      return { kind: "timeout" }
    case "project_graph_not_found":
      return { kind: "notFound" }
    case "project_graph_transport_error":
    case "project_graph_http_error":
      return { kind: "technical", reason: resolved.reason, temporary: true }
    default:
      return { kind: "technical", reason: resolved.reason, temporary: false }
  }
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
  // The last graph that actually carried nodes, for THIS identity: a temporary
  // refresh failure keeps it on screen instead of blanking the canvas.
  const ready = useRef<{ identity: string; resolved: ResolvedProjectGraph } | null>(null)
  // The identity THIS render asks for, and the identity the polled data belongs
  // to. `usePolledResource` keeps its previous value during the first render
  // with a new key, so without this guard a new Trial would briefly show the
  // previous Trial's graph - or its error - even when project_id is shared.
  const renderIdentity = useRef(identity)
  renderIdentity.current = identity
  const loadedIdentity = useRef<string | null>(null)

  const load = useCallback(
    async (signal: AbortSignal): Promise<ResolvedProjectGraph> => {
      // Claim this request for `identity` the moment it starts, so a superseded
      // request never revives the previous Trial.
      if (renderIdentity.current === identity) loadedIdentity.current = identity
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
    timeoutMs: GRAPH_REQUEST_TIMEOUT_MS,
  })

  // Only data that belongs to THIS identity is rendered; anything else is still
  // loading, so a Trial change never shows the previous graph or error.
  const owned = loadedIdentity.current === identity
  const data = owned ? resource.data : null
  const error = owned ? resource.error : null
  if (data && data.status === "available" && data.graph.nodes.length > 0) {
    ready.current = { identity, resolved: data }
  }
  const previousReady =
    ready.current && ready.current.identity === identity ? ready.current.resolved : null

  const state: GraphState = !owned || (resource.loading && data === null)
    ? { kind: "loading" }
    : data
      ? readyState(data)
      : { kind: "error", message: error ?? "unknown" }

  // A temporary failure with a graph already loaded for this identity: keep the
  // canvas (and its nodes reference) and warn instead of blanking it.
  const showingLastGraph =
    previousReady !== null &&
    (state.kind === "timeout" ||
      (state.kind === "technical" && state.temporary))
  const readyGraph: GraphState | null = showingLastGraph && previousReady
    ? readyState(previousReady)
    : state

  return (
    <section aria-label="Graph" className="project-trial-section">
      <h2>Graph</h2>
      {state.kind === "loading" && <p>Loading graph...</p>}
      {state.kind === "error" && <p role="alert">Graph error: {state.message}</p>}
      {state.kind === "empty" && <p className="eval-status">{NO_GRAPH}</p>}
      {state.kind === "timeout" && (
        <p className="eval-status" role="status">
          {TIMEOUT_MESSAGE}
        </p>
      )}
      {state.kind === "notFound" && (
        <p className="eval-status" role="status">
          {NOT_FOUND_MESSAGE}
        </p>
      )}
      {state.kind === "technical" && (
        <p className="eval-status" role="status">
          Graph unavailable ({state.reason}).
        </p>
      )}
      {readyGraph && readyGraph.kind === "ready" && (
        <GraphView
          data={readyGraph.graph}
          loading={false}
          error={null}
          label={readyGraph.label}
          capturedAt={readyGraph.capturedAt}
        />
      )}
      {showingLastGraph && (
        <p className="eval-status" role="status">
          {LAST_GRAPH_NOTICE}
        </p>
      )}
      {data !== null && error !== null && (
        <p className="eval-status" role="status">
          Graph refresh failed: {error}. Showing the previous graph.
        </p>
      )}
    </section>
  )
}
