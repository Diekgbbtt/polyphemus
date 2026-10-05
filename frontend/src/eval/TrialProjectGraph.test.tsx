import { act, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, expect, test, vi } from "vitest"
import { TrialProjectGraph } from "./TrialProjectGraph"

// The canvas is a bitmap; a text stub lets these tests assert which nodes the
// shared graph view actually received, and records the exact `nodes` array so a
// poll can be shown to reuse it (the real canvas would reset on a new array).
const canvas = vi.hoisted(() => ({ nodesSeen: [] as Array<Array<{ id: string }>> }))
vi.mock("../graph/GraphCanvas", () => ({
  GraphCanvas: ({ nodes }: { nodes: Array<{ id: string }> }) => {
    canvas.nodesSeen.push(nodes)
    return <div data-testid="graph-canvas">{nodes.map((node) => node.id).join(",")}</div>
  },
}))

afterEach(() => {
  vi.useRealTimers()
  canvas.nodesSeen.length = 0
})

const POLL = 15_000

function capturedGraph(ids: string[], capturedAt = "2024-05-05T00:00:00+00:00") {
  return {
    status: "available",
    source: "trial_snapshot",
    project_id: "p1",
    captured_at: capturedAt,
    fallback_reason: null,
    sha256: "graph-digest",
    graph: {
      project_id: "p1",
      nodes: ids.map((id) => ({ id, name: id, type: "L1Unit", properties: {} })),
      links: [],
    },
  }
}

function currentGraph(ids: string[]) {
  return {
    status: "available",
    source: "project_storage",
    project_id: "p1",
    captured_at: null,
    fallback_reason: null,
    sha256: null,
    graph: {
      project_id: "p1",
      nodes: ids.map((id) => ({ id, name: id, type: "L1Unit", properties: {} })),
      links: [],
    },
  }
}

function unavailable(reason = "project_graph_unavailable", source = "project_storage") {
  return {
    status: "unavailable",
    source,
    project_id: "p1",
    captured_at: null,
    fallback_reason: null,
    reason,
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function routeFetch(
  routes: Array<[string, () => Response | Promise<Response>]>,
): { calls: string[]; signals: AbortSignal[] } {
  const calls: string[] = []
  const signals: AbortSignal[] = []
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    calls.push(url)
    if (init?.signal) signals.push(init.signal as AbortSignal)
    for (const [needle, handler] of routes) {
      if (url.includes(needle)) return handler()
    }
    throw new Error(`unexpected fetch: ${url}`)
  }) as typeof fetch
  return { calls, signals }
}

function renderGraph(overrides: Partial<{
  targetId: string
  targetRunId: string
  trialId: string
}> = {}) {
  return render(
    <MemoryRouter>
      <TrialProjectGraph
        targetId={overrides.targetId ?? "t"}
        targetRunId={overrides.targetRunId ?? "r"}
        trialId={overrides.trialId ?? "trial-1"}
      />
    </MemoryRouter>,
  )
}

test("loads only the resolved graph and labels a capture with its source and time", async () => {
  const { calls } = routeFetch([
    ["/resolved-graph", () => json(capturedGraph(["trial-only"]))],
  ])

  renderGraph()

  await waitFor(() =>
    expect(screen.getByTestId("graph-canvas").textContent).toBe("trial-only"),
  )
  expect(screen.getByText("Captured with Trial")).toBeDefined()
  expect(screen.queryByText("Saved for project")).toBeNull()
  expect(screen.getByText(/2024-05-05/)).toBeDefined()
  // The layer controls stay available on a ready graph.
  expect(screen.getByRole("button", { name: "L0" })).toBeDefined()
  expect(screen.getByRole("button", { name: "L1" })).toBeDefined()
  // The browser never talks to the live agent for a Trial.
  expect(calls).toHaveLength(1)
  expect(calls[0]).toBe("/trials/t/r/trial-1/resolved-graph")
  expect(calls.some((url) => url.includes("/projects/p1/graph"))).toBe(false)
  expect(calls.some((url) => url.includes("/artifacts"))).toBe(false)
  expect(screen.queryByRole("link", { name: /live graph/i })).toBeNull()
})

test("labels a project-storage source as saved for the project", async () => {
  routeFetch([["/resolved-graph", () => json(currentGraph(["saved-only"]))]])

  renderGraph()

  await waitFor(() =>
    expect(screen.getByTestId("graph-canvas").textContent).toBe("saved-only"),
  )
  expect(screen.getByText("Saved for project")).toBeDefined()
  expect(screen.queryByText("Captured with Trial")).toBeNull()
})

test("renders the unavailable contract with no canvas and no error", async () => {
  routeFetch([["/resolved-graph", () => json(unavailable("project_graph_empty"))]])

  renderGraph()

  await waitFor(() => expect(screen.getByText("No graph available")).toBeDefined())
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
  expect(screen.queryByRole("alert")).toBeNull()
})

test("an empty available graph renders no canvas", async () => {
  routeFetch([["/resolved-graph", () => json(capturedGraph([]))]])

  renderGraph()

  await waitFor(() => expect(screen.getByText("No graph available")).toBeDefined())
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
})

test("a request failure is an error confined to the graph section", async () => {
  routeFetch([["/resolved-graph", () => json({ detail: "project_graph_invalid" }, 409)]])

  renderGraph()

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/project_graph_invalid/)
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
  expect(screen.queryByText("No graph available")).toBeNull()
  // The failure is contained by the graph section, not the whole page.
  const section = screen.getByRole("region", { name: "Graph" })
  expect(section.contains(screen.getByRole("alert"))).toBe(true)
})

test("never calls the live agent graph client on a direct Trial refresh", async () => {
  const { calls } = routeFetch([
    ["/resolved-graph", () => json(currentGraph(["saved-only"]))],
  ])

  renderGraph()

  await waitFor(() =>
    expect(screen.getByTestId("graph-canvas").textContent).toBe("saved-only"),
  )
  expect(calls.every((url) => url.includes("/resolved-graph"))).toBe(true)
})

test("aborts the old request and ignores a late response on a tuple change", async () => {
  let resolveFirst: ((response: Response) => void) | undefined
  const first = new Promise<Response>((resolve) => {
    resolveFirst = resolve
  })
  const { signals } = routeFetch([
    ["/trial-1/resolved-graph", () => first],
    ["/trial-2/resolved-graph", () => json(capturedGraph(["trial-two"]))],
  ])
  const { rerender } = render(
    <MemoryRouter>
      <TrialProjectGraph targetId="t" targetRunId="r" trialId="trial-1" />
    </MemoryRouter>,
  )
  rerender(
    <MemoryRouter>
      <TrialProjectGraph targetId="t" targetRunId="r" trialId="trial-2" />
    </MemoryRouter>,
  )

  await waitFor(() =>
    expect(screen.getByTestId("graph-canvas").textContent).toBe("trial-two"),
  )
  expect(signals[0].aborted).toBe(true)

  // The mock ignores the abort and resolves late: it must not overwrite trial-2.
  resolveFirst?.(json(capturedGraph(["trial-one"])))
  await Promise.resolve()
  await Promise.resolve()
  expect(screen.getByTestId("graph-canvas").textContent).toBe("trial-two")
  expect(screen.queryByText(/trial-one/)).toBeNull()
})

test("re-reads a current graph and shows it once it becomes available", async () => {
  vi.useFakeTimers()
  let body: unknown = unavailable("project_graph_unavailable")
  routeFetch([["/resolved-graph", () => json(body)]])
  renderGraph()

  await act(async () => {})
  expect(screen.getByText("No graph available")).toBeDefined()
  expect(screen.queryByTestId("graph-canvas")).toBeNull()

  body = currentGraph(["saved-only"])
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(screen.getByTestId("graph-canvas").textContent).toBe("saved-only")
  expect(screen.getByText("Saved for project")).toBeDefined()
})

test("keeps a captured graph historical and never replaces it with the current graph", async () => {
  vi.useFakeTimers()
  let body: unknown = capturedGraph(["trial-only"])
  const { calls } = routeFetch([["/resolved-graph", () => json(body)]])
  renderGraph()

  await act(async () => {})
  expect(screen.getByText("Captured with Trial")).toBeDefined()
  expect(calls).toHaveLength(1)

  // The server now reports the mutable project graph: it must not overwrite the
  // immutable capture that was written beside the Trial.
  body = currentGraph(["current-only"])
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(screen.getByText("Captured with Trial")).toBeDefined()
  expect(screen.queryByText("Saved for project")).toBeNull()
  expect(screen.getByTestId("graph-canvas").textContent).toBe("trial-only")
  // An immutable capture is not re-read at all.
  expect(calls).toHaveLength(1)
})

test("a poll that returns an unchanged graph reuses the same nodes array", async () => {
  vi.useFakeTimers()
  canvas.nodesSeen.length = 0
  routeFetch([["/resolved-graph", () => json(currentGraph(["saved-only"]))]])
  renderGraph()

  await act(async () => {})
  expect(canvas.nodesSeen).toHaveLength(1)
  const first = canvas.nodesSeen[0]

  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(canvas.nodesSeen.length).toBeGreaterThan(1)
  expect(canvas.nodesSeen[canvas.nodesSeen.length - 1]).toBe(first)
})

test("a changed current graph does replace the previous one", async () => {
  vi.useFakeTimers()
  let body: unknown = currentGraph(["before"])
  routeFetch([["/resolved-graph", () => json(body)]])
  renderGraph()

  await act(async () => {})
  expect(screen.getByTestId("graph-canvas").textContent).toBe("before")

  body = currentGraph(["after"])
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })
  expect(screen.getByTestId("graph-canvas").textContent).toBe("after")
})
