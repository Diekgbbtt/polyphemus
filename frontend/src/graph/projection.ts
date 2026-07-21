import type { GraphData, GraphLink, GraphNode } from "../api/types"

// The three-position layer filter the graph toggle drives.
//   both - the full graph (L0 + L1, every edge)
//   l0   - only the descriptive attack surface (L0 nodes + L0-L0 edges)
//   l1   - the service/system model: every L1 node, plus only the L0 nodes it
//          anchors to through a cross-layer edge (see PROJECTIONS below)
export type GraphView = "both" | "l0" | "l1"

// L1 (service/system model) labels. A node whose `type` is one of these belongs
// to Layer 1; everything else (Domain, Endpoint, Parameter, Observation, ...) is
// Layer 0. Kept in sync with the L1 palette in colors.ts and the backend
// _LABEL_PRIORITY in agent/recon/graph_read.py. Catalogue nodes (SystemKind /
// DataRelationshipKind) are L1-side registry data, so they travel with L1.
const L1_TYPES = new Set([
  "L1Service", "L1System", "L1DataItem", "L1TestableUnit",
  "SystemKind", "DataRelationshipKind",
])

// The cross-layer references that hang an L1 node off its L0 evidence:
//   AGGREGATES   (:L1Service)   -> (:L0)
//   EVIDENCED_BY (:L1System)    -> (:L0)
//   SURFACES_AT  (:L1DataItem)  -> (:L0)
// In the L1 projection these are the ONLY reason an L0 node is shown.
const CROSS_LAYER_EDGES = new Set(["AGGREGATES", "EVIDENCED_BY", "SURFACES_AT"])

export function isL1Type(type: string): boolean {
  return L1_TYPES.has(type)
}

// A link's endpoints are plain string ids in the pristine data. (react-force-graph
// later rewrites them to node object references in place, which is exactly why
// the projection must run off pristine data - see GraphCanvas.)
function endpointId(end: GraphLink["source"]): string {
  return typeof end === "object" && end !== null ? String((end as GraphNode).id) : String(end)
}

// Project the full graph down to the nodes + links visible for `view`. Pure: it
// reads `data` and returns new arrays, never mutating the input.
export function projectGraph(data: GraphData, view: GraphView): {
  nodes: GraphNode[]
  links: GraphLink[]
} {
  if (view === "both") {
    return { nodes: data.nodes, links: data.links }
  }

  const typeById = new Map(data.nodes.map((n) => [n.id, n.type]))
  const isL1 = (id: string) => isL1Type(typeById.get(id) ?? "")

  if (view === "l0") {
    // Drop every L1 node; keep only edges whose endpoints are both L0. This
    // naturally discards the cross-layer edges (their L1 end is gone).
    const nodes = data.nodes.filter((n) => !isL1Type(n.type))
    const kept = new Set(nodes.map((n) => n.id))
    const links = data.links.filter(
      (l) => kept.has(endpointId(l.source)) && kept.has(endpointId(l.target)),
    )
    return { nodes, links }
  }

  // view === "l1": every L1 node, plus the L0 nodes anchored to one through a
  // cross-layer edge. Pure L0-L0 edges (and unanchored L0 nodes) stay hidden.
  const anchoredL0 = new Set<string>()
  for (const l of data.links) {
    if (!CROSS_LAYER_EDGES.has(l.type)) continue
    const s = endpointId(l.source)
    const t = endpointId(l.target)
    if (isL1(s) && !isL1(t)) anchoredL0.add(t)
    if (isL1(t) && !isL1(s)) anchoredL0.add(s) // defensive: edges are L1 -> L0
  }
  const kept = new Set<string>()
  const nodes = data.nodes.filter((n) => {
    const keep = isL1Type(n.type) || anchoredL0.has(n.id)
    if (keep) kept.add(n.id)
    return keep
  })
  const links = data.links.filter((l) => {
    const s = endpointId(l.source)
    const t = endpointId(l.target)
    // Keep L1-internal edges and cross-layer edges; exclude any surviving L0-L0
    // edge between two anchor nodes (that belongs to the L0 story, not L1).
    return kept.has(s) && kept.has(t) && (isL1(s) || isL1(t))
  })
  return { nodes, links }
}
