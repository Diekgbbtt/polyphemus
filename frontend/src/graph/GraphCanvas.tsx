import { useMemo } from "react"
import ForceGraph2D from "react-force-graph-2d"
import type { GraphNode, GraphLink } from "../api/types"
import { nodeColor } from "./colors"
import { projectGraph, type GraphView } from "./projection"

// Bookkeeping keys that carry no attack-surface meaning for a viewer.
const HIDDEN_KEYS = new Set(["project_id", "id", "element_id"])

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return ""
  if (Array.isArray(v)) return v.map((x) => String(x)).join(", ")
  if (typeof v === "object") return JSON.stringify(v)
  return String(v)
}

// Small data box shown on hover: an Observation surfaces its NL comment
// (macro_kind/severity/evidence/rationale live in properties); every other
// node surfaces its object attributes. Content is escaped - it originates from
// scanned third-party targets and must never be injected as live HTML.
function nodeTooltip(n: object): string {
  const node = n as GraphNode
  const props = node.properties || {}
  const rows = Object.entries(props)
    .filter(([k, v]) => !HIDDEN_KEYS.has(k) && v !== null && v !== undefined && v !== "")
    .map(
      ([k, v]) =>
        `<div style="display:flex;gap:8px;margin-top:2px">` +
        `<span style="color:#9aa0a6;flex:0 0 34%;text-align:right">${escapeHtml(k)}</span>` +
        `<span style="flex:1 1 auto;word-break:break-word">${escapeHtml(formatValue(v))}</span></div>`,
    )
    .join("")
  return (
    `<div style="max-width:360px;padding:9px 11px;background:#14161a;color:#e8eaed;` +
    `border:1px solid #3c4043;border-radius:8px;font:12px/1.45 system-ui,sans-serif;` +
    `box-shadow:0 4px 16px rgba(0,0,0,.55)">` +
    `<div style="font-weight:600;margin-bottom:5px;color:#fff">` +
    `${escapeHtml(node.type)}<span style="color:#9aa0a6"> · </span>${escapeHtml(node.name)}</div>` +
    (rows || `<div style="color:#9aa0a6">(no attributes)</div>`) +
    `</div>`
  )
}

export function GraphCanvas({
  nodes,
  links,
  view = "both",
}: {
  nodes: GraphNode[]
  links: GraphLink[]
  view?: GraphView
}) {
  // Project to the selected layer and hand ForceGraph FRESH object copies:
  // react-force-graph rewrites each link's source/target from an id string to a
  // node reference in place, so reusing the pristine arrays would corrupt them
  // for the next projection. Copying per view keeps the source data intact.
  const graphData = useMemo(() => {
    const projected = projectGraph({ project_id: "", nodes, links }, view)
    return {
      nodes: projected.nodes.map((n) => ({ ...n })),
      links: projected.links.map((l) => ({ ...l })),
    }
  }, [nodes, links, view])

  return (
    <ForceGraph2D
      // Remount on view change so the simulation restarts from the fresh copies
      // rather than the previous view's already-mutated ones.
      key={view}
      graphData={graphData as { nodes: object[]; links: object[] }}
      nodeId="id"
      nodeLabel={nodeTooltip}
      nodeColor={(n: object) => nodeColor((n as GraphNode).type)}
      linkLabel={(l: object) => (l as GraphLink).type}
    />
  )
}
