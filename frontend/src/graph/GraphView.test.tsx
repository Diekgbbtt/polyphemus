import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { expect, test, vi } from "vitest"
import { App } from "../App"
import { GraphView } from "./GraphView"
import type { GraphData } from "../api/types"

vi.mock("./GraphCanvas", () => ({
  GraphCanvas: ({ nodes }: { nodes: Array<{ id: string }> }) => (
    <div data-testid="graph-canvas">{nodes.map((node) => node.id).join(",")}</div>
  ),
}))

const DATA: GraphData = {
  project_id: "p1",
  nodes: [{ id: "n1", name: "n1", type: "L1Unit", properties: {} }],
  links: [],
}

test("shows a loading state", () => {
  render(<GraphView data={null} loading error={null} label="Live project graph" />)

  expect(screen.getByText(/Loading graph/i)).toBeDefined()
  expect(screen.getByText("Live project graph")).toBeDefined()
})

test("shows an accessible error state", () => {
  render(<GraphView data={null} loading={false} error="boom" label="Live project graph" />)

  expect(screen.getByRole("alert").textContent).toMatch(/Graph error: boom/)
})

test("shows the empty state", () => {
  render(
    <GraphView
      data={{ project_id: "p1", nodes: [], links: [] }}
      loading={false}
      error={null}
      label="Live project graph"
    />,
  )

  expect(screen.getByText(/No assets yet/i)).toBeDefined()
})

test("both layers start on and toggle independently", () => {
  render(<GraphView data={DATA} loading={false} error={null} label="Live project graph" />)

  const l0 = screen.getByRole("button", { name: "L0" })
  const l1 = screen.getByRole("button", { name: "L1" })
  expect(l0.getAttribute("aria-pressed")).toBe("true")
  expect(l1.getAttribute("aria-pressed")).toBe("true")
  expect(screen.getByTestId("graph-canvas").textContent).toBe("n1")

  fireEvent.click(l0)
  expect(l0.getAttribute("aria-pressed")).toBe("false")
  expect(l1.getAttribute("aria-pressed")).toBe("true")
  expect(screen.getByTestId("graph-canvas")).toBeDefined()
})

test("both layers off shows the hint and no canvas", () => {
  render(<GraphView data={DATA} loading={false} error={null} label="Live project graph" />)

  fireEvent.click(screen.getByRole("button", { name: "L0" }))
  fireEvent.click(screen.getByRole("button", { name: "L1" }))

  expect(screen.getByText(/Both layers are off/i)).toBeDefined()
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
})

test("capturedAt is shown only when present", () => {
  const { unmount } = render(
    <GraphView data={DATA} loading={false} error={null} label="Trial snapshot" />,
  )
  expect(screen.queryByText(/Captured/i)).toBeNull()
  unmount()

  render(
    <GraphView
      data={DATA}
      loading={false}
      error={null}
      label="Trial snapshot"
      capturedAt="2024-05-05T00:00:00+00:00"
    />,
  )
  expect(screen.getByText(/2024-05-05/)).toBeDefined()
})

test("the live GraphPage calls only the agent graph endpoint", async () => {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    calls.push(String(input))
    return new Response(JSON.stringify(DATA), { status: 200 })
  }) as typeof fetch
  window.history.pushState({}, "", "/p/p1")
  render(<App />)

  await waitFor(() => expect(screen.getByText("Live project graph")).toBeDefined())
  expect(calls).toEqual(["/projects/p1/graph"])
  expect(calls.some((url) => url.includes("/project-graph"))).toBe(false)
  window.history.pushState({}, "", "/")
})
