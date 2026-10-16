import { useEffect, useState } from "react"
import { HttpError, getGraph } from "../api/client"
import type { GraphData } from "../api/types"

export function useGraphData(projectId: string) {
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // A 404 is a stable answer ("this project has no stored graph"), not a
  // failure: the caller states it in words instead of showing a raw HTTP error.
  const [notFound, setNotFound] = useState(false)
  useEffect(() => {
    let alive = true
    setLoading(true)
    setNotFound(false)
    getGraph(projectId)
      .then((d) => { if (alive) { setData(d); setError(null); setNotFound(false) } })
      .catch((e) => {
        if (!alive) return
        setNotFound(e instanceof HttpError && e.status === 404)
        setError(String(e))
      })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [projectId])
  return { data, loading, error, notFound }
}
