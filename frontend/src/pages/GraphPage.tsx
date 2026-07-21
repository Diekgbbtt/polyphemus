import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useGraphData } from "../graph/useGraphData"
import { GraphCanvas } from "../graph/GraphCanvas"
import type { GraphView } from "../graph/projection"

const VIEWS: { value: GraphView; label: string }[] = [
  { value: "both", label: "Both" },
  { value: "l0", label: "L0" },
  { value: "l1", label: "L1" },
]

// Segmented three-position layer filter. Purely presentational state - drives
// which projection GraphCanvas renders (see projection.ts).
function LayerToggle({ view, onChange }: { view: GraphView; onChange: (v: GraphView) => void }) {
  return (
    <div role="group" aria-label="Graph layer filter" style={{ display: "inline-flex", border: "1px solid #3c4043", borderRadius: 8, overflow: "hidden" }}>
      {VIEWS.map((v, i) => {
        const active = v.value === view
        return (
          <button
            key={v.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(v.value)}
            style={{
              padding: "4px 14px",
              border: "none",
              borderLeft: i === 0 ? "none" : "1px solid #3c4043",
              background: active ? "#2563eb" : "#14161a",
              color: active ? "#fff" : "#9aa0a6",
              font: "13px/1 system-ui, sans-serif",
              cursor: "pointer",
            }}
          >
            {v.label}
          </button>
        )
      })}
    </div>
  )
}

export function GraphPage() {
  const { id = "" } = useParams()
  const { data, loading, error } = useGraphData(id)
  const [view, setView] = useState<GraphView>("both")
  return (
    <main>
      <header style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Link to="/">back</Link> <Link to={`/p/${id}/runs`}>running runs</Link>
        <LayerToggle view={view} onChange={setView} />
      </header>
      {loading && <p>Loading graph...</p>}
      {error && <p role="alert">Graph error: {error}</p>}
      {data && data.nodes.length === 0 && <p>No assets yet for this project.</p>}
      {data && data.nodes.length > 0 && <GraphCanvas nodes={data.nodes} links={data.links} view={view} />}
    </main>
  )
}
