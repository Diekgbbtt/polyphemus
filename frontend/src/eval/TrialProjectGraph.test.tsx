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
  // A definitive empty first answer ("No graph available"), then a real graph.
  let body: unknown = unavailable("project_graph_empty")
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


// --- distinguishable graph-read outcomes and the last valid graph --------------

test("a first-load timeout is explicit and never 'No graph available'", async () => {
  routeFetch([["/resolved-graph", () => json(unavailable("project_graph_timeout"))]])

  renderGraph()

  await waitFor(() => expect(screen.getByText(/timed out/i)).toBeDefined())
  expect(screen.queryByText("No graph available")).toBeNull()
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
})

test("a project missing from the source is distinct from an empty graph", async () => {
  routeFetch([["/resolved-graph", () => json(unavailable("project_graph_not_found"))]])

  renderGraph()

  await waitFor(() =>
    expect(screen.getByText(/not available in the graph source/i)).toBeDefined(),
  )
  expect(screen.queryByText("No graph available")).toBeNull()
})

test("transport and 5xx failures are technical errors, not 'No graph available'", async () => {
  for (const reason of ["project_graph_transport_error", "project_graph_http_error"]) {
    routeFetch([["/resolved-graph", () => json(unavailable(reason))]])
    const { unmount } = renderGraph()
    await waitFor(() =>
      expect(screen.getByText(new RegExp(`Graph unavailable \\(${reason}\\)`))).toBeDefined(),
    )
    expect(screen.queryByText("No graph available")).toBeNull()
    unmount()
  }
})

test("waits up to 45s for one graph read, beyond the server's own bound", async () => {
  vi.useFakeTimers()
  let resolveRead: ((response: Response) => void) | undefined
  const pending = new Promise<Response>((resolve) => {
    resolveRead = resolve
  })
  routeFetch([["/resolved-graph", () => pending]])
  renderGraph()

  await act(async () => {})
  // Just under the graph timeout the poller must not have given up (the shared
  // default would have failed at 15s).
  await act(async () => {
    await vi.advanceTimersByTimeAsync(44_000)
  })
  expect(screen.queryByRole("alert")).toBeNull()

  resolveRead?.(json(currentGraph(["slow"])))
  await act(async () => {})
  expect(screen.getByTestId("graph-canvas").textContent).toBe("slow")
})

test("a temporary failure on refresh keeps the last loaded graph", async () => {
  vi.useFakeTimers()
  let body: unknown = currentGraph(["kept"])
  routeFetch([["/resolved-graph", () => json(body)]])
  renderGraph()

  await act(async () => {})
  expect(screen.getByTestId("graph-canvas").textContent).toBe("kept")
  const firstNodes = canvas.nodesSeen[canvas.nodesSeen.length - 1]

  body = unavailable("project_graph_timeout")
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(screen.getByTestId("graph-canvas").textContent).toBe("kept")
  expect(screen.getByText(/last loaded graph/i)).toBeDefined()
  // The same nodes reference: the canvas keeps its zoom and layer state.
  expect(canvas.nodesSeen[canvas.nodesSeen.length - 1]).toBe(firstNodes)
})

test("a later successful refresh clears the warning and updates the graph", async () => {
  vi.useFakeTimers()
  let body: unknown = currentGraph(["kept"])
  routeFetch([["/resolved-graph", () => json(body)]])
  renderGraph()
  await act(async () => {})

  body = unavailable("project_graph_transport_error")
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })
  expect(screen.getByText(/last loaded graph/i)).toBeDefined()

  body = currentGraph(["recovered"])
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })
  expect(screen.getByTestId("graph-canvas").textContent).toBe("recovered")
  expect(screen.queryByText(/last loaded graph/i)).toBeNull()
})

test("a valid empty answer is not masked as a temporary error", async () => {
  vi.useFakeTimers()
  let body: unknown = currentGraph(["kept"])
  routeFetch([["/resolved-graph", () => json(body)]])
  renderGraph()
  await act(async () => {})
  expect(screen.getByTestId("graph-canvas").textContent).toBe("kept")

  body = unavailable("project_graph_empty")
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(screen.getByText("No graph available")).toBeDefined()
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
  expect(screen.queryByText(/last loaded graph/i)).toBeNull()
})

test("a Trial change never shows the previous Trial's graph", async () => {
  let resolveSecond: ((response: Response) => void) | undefined
  const second = new Promise<Response>((resolve) => {
    resolveSecond = resolve
  })
  routeFetch([
    ["/trial-1/resolved-graph", () => json(currentGraph(["one"]))],
    ["/trial-2/resolved-graph", () => second],
  ])
  const { rerender } = render(
    <MemoryRouter>
      <TrialProjectGraph targetId="t" targetRunId="r" trialId="trial-1" />
    </MemoryRouter>,
  )
  await act(async () => {})
  expect(screen.getByTestId("graph-canvas").textContent).toBe("one")

  rerender(
    <MemoryRouter>
      <TrialProjectGraph targetId="t" targetRunId="r" trialId="trial-2" />
    </MemoryRouter>,
  )
  await act(async () => {})
  // The previous graph and its error are gone; the new Trial is still loading.
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
  expect(screen.queryByText("No graph available")).toBeNull()
  expect(screen.queryByRole("alert")).toBeNull()

  resolveSecond?.(json(currentGraph(["two"])))
  await act(async () => {})
  expect(screen.getByTestId("graph-canvas").textContent).toBe("two")
})

test("a slow read never overlaps the next poll", async () => {
  vi.useFakeTimers()
  let resolveRead: ((response: Response) => void) | undefined
  const pending = new Promise<Response>((resolve) => {
    resolveRead = resolve
  })
  const { calls } = routeFetch([["/resolved-graph", () => pending]])
  renderGraph()

  await act(async () => {})
  expect(calls).toHaveLength(1)
  // A tick while the request is open is skipped, never overlapped.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })
  expect(calls).toHaveLength(1)

  resolveRead?.(json(currentGraph(["late"])))
  await act(async () => {})
  expect(calls).toHaveLength(1)
  expect(screen.getByTestId("graph-canvas").textContent).toBe("late")
})
