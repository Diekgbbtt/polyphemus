import { Link, useParams } from "react-router-dom"
import { useGraphData } from "../graph/useGraphData"
import { GraphCanvas } from "../graph/GraphCanvas"

export function GraphPage() {
  const { id = "" } = useParams()
  const { data, loading, error } = useGraphData(id)
  return (
    <main>
      <header><Link to="/">back</Link> <Link to={`/p/${id}/runs`}>running runs</Link></header>
      {loading && <p>Loading graph...</p>}
      {error && <p role="alert">Graph error: {error}</p>}
      {data && data.nodes.length === 0 && <p>No assets yet for this project.</p>}
      {data && data.nodes.length > 0 && <GraphCanvas nodes={data.nodes} links={data.links} />}
    </main>
  )
}
