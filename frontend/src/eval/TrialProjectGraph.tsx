import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import type { GraphData } from "../api/types"
import { getGraph, HttpError } from "../api/client"
import { GraphView } from "../graph/GraphView"
import { projectPaths } from "../projectPaths"
import { getTrialProjectGraph } from "./client"
import type { ProjectGraphSummary } from "./types"

// The current graph is not the Trial's history, and says so.
const CURRENT_LABEL = "Current L0/L1 — not captured with Trial"
const NO_GRAPH = "No graph available"

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "AbortError"
  )
}

function isEmptyGraph(graph: GraphData | null | undefined): boolean {
  return !graph || !Array.isArray(graph.nodes) || graph.nodes.length === 0
}

type GraphState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "missing" }
  | { kind: "ready"; graph: GraphData; capturedAt: string | null }

// The graph section of one Trial.
//
// Schema-v2 Trials carry an immutable historical graph: it is the only source
// used, and a failure to load it stays an error - it never silently becomes
// live data. A Trial without a captured graph (the schema-v1 data the eval
// currently produces) instead shows the project's *current* L0/L1 graph, from
// the existing live endpoint, labelled as current data. An empty or missing
// live graph renders the simple unavailable state rather than an empty canvas.
export function TrialProjectGraph({
  projectId,
  targetId,
  targetRunId,
  trialId,
  summary,
}: {
  projectId: string
  targetId: string
  targetRunId: string
  trialId: string
  summary: ProjectGraphSummary
}) {
  const historical = summary.status === "available"
  const [state, setState] = useState<GraphState>({ kind: "loading" })

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    // A tuple change always starts from a clean slate.
    setState({ kind: "loading" })

    const request: Promise<{ graph: GraphData; capturedAt: string | null }> = historical
      ? getTrialProjectGraph(targetId, targetRunId, trialId, controller.signal).then(
          (response) => ({ graph: response.graph, capturedAt: response.captured_at }),
        )
      : getGraph(projectId, controller.signal).then((graph) => ({ graph, capturedAt: null }))

    request
      .then(({ graph, capturedAt }) => {
        if (!active) return
        if (!historical && isEmptyGraph(graph)) {
          setState({ kind: "missing" })
          return
        }
        setState({ kind: "ready", graph, capturedAt })
      })
      .catch((cause: unknown) => {
        if (!active || isAbortError(cause)) return
        // Only a live 404 means "this project has no current graph". A
        // historical failure is always an error and never a fallback.
        if (!historical && cause instanceof HttpError && cause.status === 404) {
          setState({ kind: "missing" })
          return
        }
        setState({
          kind: "error",
          message: cause instanceof Error ? cause.message : String(cause),
        })
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [historical, projectId, targetId, targetRunId, trialId])

  return (
    <section aria-label="Graph" className="project-trial-section">
      <h2>Graph</h2>
      <p className="graph-live-link">
        <Link to={projectPaths.live(projectId)}>Open live graph</Link>
      </p>
      {historical ? (
        <GraphView
          data={state.kind === "ready" ? state.graph : null}
          loading={state.kind === "loading"}
          error={state.kind === "error" ? state.message : null}
          label="Trial snapshot"
          capturedAt={state.kind === "ready" ? state.capturedAt : null}
        />
      ) : (
        <>
          {state.kind === "loading" && <p>Loading graph...</p>}
          {state.kind === "error" && <p role="alert">Graph error: {state.message}</p>}
          {state.kind === "missing" && <p className="eval-status">{NO_GRAPH}</p>}
          {state.kind === "ready" && (
            <GraphView
              data={state.graph}
              loading={false}
              error={null}
              label={CURRENT_LABEL}
            />
          )}
        </>
      )}
    </section>
  )
}
