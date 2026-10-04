import { render } from "@testing-library/react"
import { expect, test, vi } from "vitest"
import type { GraphLink, GraphNode } from "../api/types"

// Capture the props react-force-graph is handed. The mock renders nothing: the
// unit under test is the prop contract, not the WebGL/2D rendering.
const captured = vi.hoisted(() => ({ props: {} as Record<string, unknown> }))

vi.mock("react-force-graph-2d", () => ({
  default: (props: Record<string, unknown>) => {
    captured.props = props
    return null
  },
}))

import { GraphCanvas } from "./GraphCanvas"

const NODES: GraphNode[] = [
  { id: "service:p", name: "service", type: "L1Service", properties: {} },
  { id: "endpoint:a", name: "a", type: "Endpoint", properties: {} },
]
const LINKS: GraphLink[] = [
  { source: "service:p", target: "endpoint:a", type: "AGGREGATES" },
]

test("gives graph edges an explicit high-contrast color and a wider stroke", () => {
  const { container } = render(<GraphCanvas nodes={NODES} links={LINKS} />)

  // Root cause: accessor-fn treats every *string* as a property name, so
  // passing "#8ab4f8" means `link["#8ab4f8"]` -> undefined -> the library's
  // rgba(0,0,0,0.15) black fallback, invisible on the dark canvas. linkColor
  // must therefore be a callback, and it must return the palette accent for a
  // link that carries no color of its own. This is what fixes both the live and
  // the historical graph.
  const linkColor = captured.props.linkColor
  expect(typeof linkColor).toBe("function")
  const resolveColor = linkColor as (link: GraphLink) => string
  expect(resolveColor(LINKS[0])).toBe("#8ab4f8")
  expect(resolveColor(LINKS[0])).not.toBe("rgba(0,0,0,0.15)")
  expect(captured.props.linkWidth as number).toBeGreaterThan(1)
  expect(captured.props.backgroundColor).toBe("#0b0d10")
  // A framed surface so the canvas is not a raw window-sized rectangle.
  expect(container.querySelector(".graph-canvas")).not.toBeNull()
})
