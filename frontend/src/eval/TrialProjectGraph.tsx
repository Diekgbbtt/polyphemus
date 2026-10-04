import { useEffect, useState } from "react"
import type { GraphData } from "../api/types"
import { GraphView } from "../graph/GraphView"
import { getResolvedTrialGraph } from "./client"
import type { ResolvedProjectGraph } from "./types"

// The two sources the resolved endpoint reports. The browser never chooses
// between them; it only labels what the server resolved. These are the only
// labels a Trial ever shows, never a schema-version term.
const SOURCE_LABEL: Record<ResolvedProjectGraph["source"], string> = {
  trial_snapshot: "Captured with Trial",
  project_storage: "Saved for project",
}

const NO_GRAPH = "No graph available"

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "AbortError"
  )
}

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

// The graph section of one Trial.
//
// It consumes only the resolved Trial endpoint: the server decides between the
// immutable capture written beside the Trial and the matching instance's
// current project graph, and reports which one it used. The component never
// calls the live agent graph client, so a Trial from another instance can never
// reach this server's project data. A failure here stays an error inside this
// section and never silently becomes a different source.
export function TrialProjectGraph({
  targetId,
  targetRunId,
  trialId,
}: {
  targetId: string
  targetRunId: string
  trialId: string
}) {
  const [state, setState] = useState<GraphState>({ kind: "loading" })

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    // A tuple change always starts from a clean slate.
    setState({ kind: "loading" })

    getResolvedTrialGraph(targetId, targetRunId, trialId, controller.signal)
      .then((resolved) => {
        if (!active) return
        setState(readyState(resolved))
      })
      .catch((cause: unknown) => {
        if (!active || isAbortError(cause)) return
        setState({
          kind: "error",
          message: cause instanceof Error ? cause.message : String(cause),
        })
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [targetId, targetRunId, trialId])

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
    </section>
  )
}
