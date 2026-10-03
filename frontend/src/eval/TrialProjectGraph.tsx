import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import type { GraphData } from "../api/types"
import { GraphView } from "../graph/GraphView"
import { projectPaths } from "../projectPaths"
import { getTrialProjectGraph } from "./client"
import type { ProjectGraphSummary } from "./types"

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "AbortError"
  )
}

// The historical graph loader for one Trial. It talks to the eval API only:
// the live graph is a separate source and is never fetched or used as a
// fallback here. An unavailable snapshot renders its state without a request.
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
  const available = summary.status === "available"
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(available)
  const [error, setError] = useState<string | null>(null)
  const [capturedAt, setCapturedAt] = useState<string | null>(null)

  useEffect(() => {
    if (!available) {
      setData(null)
      setError(null)
      setCapturedAt(null)
      setLoading(false)
      return
    }
    const controller = new AbortController()
    let active = true
    // A tuple change always starts from a clean slate.
    setData(null)
    setError(null)
    setCapturedAt(null)
    setLoading(true)

    getTrialProjectGraph(targetId, targetRunId, trialId, controller.signal)
      .then((response) => {
        if (!active) return
        setData(response.graph)
        setCapturedAt(response.captured_at)
        setLoading(false)
      })
      .catch((cause: unknown) => {
        if (!active || isAbortError(cause)) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setLoading(false)
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [available, targetId, targetRunId, trialId])

  return (
    <section aria-label="Graph" className="project-trial-section">
      <h2>Graph</h2>
      <p className="graph-live-link">
        <Link to={projectPaths.live(projectId)}>Open live graph</Link>
      </p>
      {available ? (
        <GraphView
          data={data}
          loading={loading}
          error={error}
          label="Trial snapshot"
          capturedAt={capturedAt}
        />
      ) : (
        <p className="eval-status">
          Historical graph not available for this Trial ({summary.status}).
        </p>
      )}
    </section>
  )
}
