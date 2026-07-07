import ForceGraph2D from "react-force-graph-2d"
import type { GraphNode, GraphLink } from "../api/types"
import { nodeColor } from "./colors"

export function GraphCanvas({ nodes, links }: { nodes: GraphNode[]; links: GraphLink[] }) {
  return (
    <ForceGraph2D
      graphData={{ nodes: nodes as object[], links: links as object[] }}
      nodeId="id"
      nodeLabel={(n: object) => `${(n as GraphNode).type}: ${(n as GraphNode).name}`}
      nodeColor={(n: object) => nodeColor((n as GraphNode).type)}
      linkLabel={(l: object) => (l as GraphLink).type}
    />
  )
}
