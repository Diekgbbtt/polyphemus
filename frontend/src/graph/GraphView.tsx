import { useState } from "react"
import type { GraphData } from "../api/types"
import { GraphCanvas } from "./GraphCanvas"
import type { LayerVisibility } from "./projection"

const LAYERS: { key: keyof LayerVisibility; label: string }[] = [
  { key: "l0", label: "L0" },
  { key: "l1", label: "L1" },
]

// Two independent on/off layer switches. Purely presentational state - drives
// which projection GraphCanvas renders. The combinations carry no extra rule of
// their own: both on shows both graphs, one on shows that layer (see
// projection.ts).
function LayerToggles({
  layers,
  onChange,
}: {
  layers: LayerVisibility
  onChange: (l: LayerVisibility) => void
}) {
  return (
    <div
      role="group"
      aria-label="Graph layers"
      style={{ display: "inline-flex", border: "1px solid #3c4043", borderRadius: 8, overflow: "hidden" }}
    >
      {LAYERS.map((l, i) => {
        const on = layers[l.key]
        return (
          <button
            key={l.key}
            type="button"
            aria-pressed={on}
            title={`${l.label} layer ${on ? "on" : "off"}`}
            onClick={() => onChange({ ...layers, [l.key]: !on })}
            style={{
              padding: "4px 14px",
              border: "none",
              borderLeft: i === 0 ? "none" : "1px solid #3c4043",
              background: on ? "#2563eb" : "#14161a",
              color: on ? "#fff" : "#9aa0a6",
              font: "13px/1 system-ui, sans-serif",
              cursor: "pointer",
            }}
          >
            {l.label}
          </button>
        )
      })}
    </div>
  )
}

// The shared L0/L1 graph presentation. It is deliberately source-agnostic: the
// live project page and the historical Trial snapshot both hand it fetched
// `GraphData`, and it never fetches anything itself.
export function GraphView({
  data,
  loading,
  error,
  label,
  capturedAt,
}: {
  data: GraphData | null
  loading: boolean
  error: string | null
  label: string
  capturedAt?: string | null
}) {
  const [layers, setLayers] = useState<LayerVisibility>({ l0: true, l1: true })
  const anyLayer = layers.l0 || layers.l1
  return (
    <div className="graph-view">
      <div className="graph-view-toolbar">
        <span className="graph-view-source">{label}</span>
        {capturedAt && (
          <span className="graph-view-captured">Captured {capturedAt}</span>
        )}
        <LayerToggles layers={layers} onChange={setLayers} />
      </div>
      {loading && <p>Loading graph...</p>}
      {error && <p role="alert">Graph error: {error}</p>}
      {data && data.nodes.length === 0 && <p>No assets yet for this project.</p>}
      {data && data.nodes.length > 0 && !anyLayer && (
        <p>Both layers are off - switch L0 or L1 on to see the graph.</p>
      )}
      {data && data.nodes.length > 0 && anyLayer && (
        <GraphCanvas nodes={data.nodes} links={data.links} layers={layers} />
      )}
    </div>
  )
}
