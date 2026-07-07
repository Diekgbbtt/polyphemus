import { useEffect, useState } from "react"
import { getGraph } from "../api/client"
import type { GraphData } from "../api/types"

export function useGraphData(projectId: string) {
  const [data, setData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setLoading(true)
    getGraph(projectId)
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e) => { if (alive) setError(String(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [projectId])
  return { data, loading, error }
}
