import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, test, vi } from "vitest"
import { App } from "../App"
import { TrialProjectGraph } from "./TrialProjectGraph"
import type { EvalSnapshot, EvalTrial, ProjectGraphSummary } from "./types"

// The canvas is a bitmap; a text stub lets these tests assert which nodes the
// shared graph view actually received.
vi.mock("../graph/GraphCanvas", () => ({
  GraphCanvas: ({ nodes }: { nodes: Array<{ id: string }> }) => (
    <div data-testid="graph-canvas">{nodes.map((node) => node.id).join(",")}</div>
  ),
}))

const AVAILABLE: ProjectGraphSummary = {
  status: "available",
  nodes: 1,
  links: 0,
  captured_at: "2024-05-05T00:00:00+00:00",
}

const UNAVAILABLE: ProjectGraphSummary = {
  status: "project_snapshot_unavailable",
  nodes: 0,
  links: 0,
  captured_at: null,
}

function graphResponse(ids: string[], capturedAt = AVAILABLE.captured_at) {
  return {
    status: "available",
    captured_at: capturedAt,
    sha256: "graph-digest",
    graph: {
      project_id: "p1",
      nodes: ids.map((id) => ({ id, name: id, type: "L1Unit", properties: {} })),
      links: [],
    },
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

function renderGraph(
  overrides: Partial<{
    projectId: string
    targetId: string
    targetRunId: string
    trialId: string
    summary: ProjectGraphSummary
  }> = {},
) {
  return render(
    <MemoryRouter>
      <TrialProjectGraph
        projectId={overrides.projectId ?? "p1"}
        targetId={overrides.targetId ?? "t"}
        targetRunId={overrides.targetRunId ?? "r"}
        trialId={overrides.trialId ?? "trial-1"}
        summary={overrides.summary ?? AVAILABLE}
      />
    </MemoryRouter>,
  )
}

function evalTrial(overrides: Partial<EvalTrial> = {}): EvalTrial {
  return {
    target_id: "t",
    target_run_id: "r",
    trial_id: "trial-1",
    instance_id: "inst-1",
    project_id: "p1",
    start_phase: "recon",
    terminal: "complete",
    copied_at: "2024-01-01T00:00:00+00:00",
    phases: [],
    eval_sha: "sha-x",
    stack_fingerprint: "fp-x",
    verdicts: [],
    diagnoses: [],
    availability: "complete",
    reason: null,
    artifact_summary: { status: "available", hunting: 0, skills: 0 },
    project_graph_summary: AVAILABLE,
    ...overrides,
  }
}

function evalSnapshot(trials: EvalTrial[]): EvalSnapshot {
  return {
    dataset: { id: "webexploitbench", name: "WebExploitBench" },
    summary: { targets: 1, trials: trials.length, identified: 0, partial: 0, missed: 0, degraded: 0 },
    targets: [],
    trials,
    versions: [],
    coverage: {
      targets: { tested: 0, with_identified: 0, without_identified: 0 },
      vulnerabilities: { total: 0, found: 0, not_found: 0, partial: 0 },
    },
    successes: [],
    degraded_trials: [],
  }
}

test("loads the historical graph with its label, capture time, and live link", async () => {
  const { calls } = routeFetch([
    ["/project-graph", () => json(graphResponse(["trial-only"]))],
  ])

  renderGraph()

  await waitFor(() =>
    expect(screen.getByTestId("graph-canvas").textContent).toBe("trial-only"),
  )
  expect(screen.getByText("Trial snapshot")).toBeDefined()
  expect(screen.getByText(/2024-05-05/)).toBeDefined()
  expect(screen.getByRole("link", { name: /live graph/i }).getAttribute("href")).toBe("/p/p1")
  expect(calls).toHaveLength(1)
  expect(calls[0]).toBe("/trials/t/r/trial-1/project-graph")
  expect(calls.some((url) => url.includes("/projects/p1/graph"))).toBe(false)
  expect(calls.some((url) => url.includes("/artifacts"))).toBe(false)
})

test("renders the empty state for an empty historical graph", async () => {
  routeFetch([["/project-graph", () => json(graphResponse([]))]])

  renderGraph()

  await waitFor(() => expect(screen.getByText(/No assets yet/i)).toBeDefined())
})

test("an unavailable summary falls back to the current live graph only", async () => {
  const { calls } = routeFetch([
    [
      "/projects/p1/graph",
      () =>
        json({
          project_id: "p1",
          nodes: [{ id: "live-only", name: "live", type: "L1Service", properties: {} }],
          links: [],
        }),
    ],
  ])

  renderGraph({ summary: UNAVAILABLE })

  await waitFor(() =>
    expect(screen.getByTestId("graph-canvas").textContent).toBe("live-only"),
  )
  // The fallback is labelled as current data, never as the Trial snapshot.
  expect(screen.getByText("Current L0/L1 — not captured with Trial")).toBeDefined()
  expect(screen.queryByText("Trial snapshot")).toBeNull()
  expect(calls).toEqual(["/projects/p1/graph"])
})

test("an empty live graph renders no canvas", async () => {
  routeFetch([
    ["/projects/p1/graph", () => json({ project_id: "p1", nodes: [], links: [] })],
  ])

  renderGraph({ summary: UNAVAILABLE })

  await waitFor(() => expect(screen.getByText("No graph available")).toBeDefined())
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
})

test("a 404 live graph renders no canvas and no error", async () => {
  routeFetch([["/projects/p1/graph", () => json({ detail: "unknown project" }, 404)]])

  renderGraph({ summary: UNAVAILABLE })

  await waitFor(() => expect(screen.getByText("No graph available")).toBeDefined())
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
  expect(screen.queryByRole("alert")).toBeNull()
})

test("a failing live graph that is not a 404 stays an error", async () => {
  routeFetch([["/projects/p1/graph", () => json({ detail: "boom" }, 500)]])

  renderGraph({ summary: UNAVAILABLE })

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/500/)
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
  expect(screen.queryByText("No graph available")).toBeNull()
})

test("an API error never falls back to the live graph", async () => {
  const { calls } = routeFetch([
    [
      "/projects/p1/graph",
      () =>
        json({
          project_id: "p1",
          nodes: [{ id: "live-only", name: "live", type: "L1Unit", properties: {} }],
          links: [],
        }),
    ],
    ["/project-graph", () => json({ detail: "project_graph_unavailable" }, 409)],
  ])

  renderGraph()

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/project_graph_unavailable/)
  expect(screen.queryByTestId("graph-canvas")).toBeNull()
  expect(screen.queryByText(/live-only/)).toBeNull()
  expect(calls.some((url) => url.includes("/projects/p1/graph"))).toBe(false)
})

test("aborts the old request and ignores a late response on a tuple change", async () => {
  let resolveFirst: ((response: Response) => void) | undefined
  const first = new Promise<Response>((resolve) => {
    resolveFirst = resolve
  })
  const { signals } = routeFetch([
    ["/trial-1/project-graph", () => first],
    ["/trial-2/project-graph", () => json(graphResponse(["trial-two"]))],
  ])
  const { rerender } = render(
    <MemoryRouter>
      <TrialProjectGraph
        projectId="p1"
        targetId="t"
        targetRunId="r"
        trialId="trial-1"
        summary={AVAILABLE}
      />
    </MemoryRouter>,
  )
  rerender(
    <MemoryRouter>
      <TrialProjectGraph
        projectId="p1"
        targetId="t"
        targetRunId="r"
        trialId="trial-2"
        summary={AVAILABLE}
      />
    </MemoryRouter>,
  )

  await waitFor(() =>
    expect(screen.getByTestId("graph-canvas").textContent).toBe("trial-two"),
  )
  expect(signals[0].aborted).toBe(true)

  // The mock ignores the abort and resolves late: it must not overwrite trial-2.
  resolveFirst?.(json(graphResponse(["trial-one"])))
  await Promise.resolve()
  await Promise.resolve()
  expect(screen.getByTestId("graph-canvas").textContent).toBe("trial-two")
  expect(screen.queryByText(/trial-one/)).toBeNull()
})

test("a direct refresh of the workspace route loads only the historical graph", async () => {
  const { calls } = routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    [
      "/projects/p1/graph",
      () =>
        json({
          project_id: "p1",
          nodes: [{ id: "live-only", name: "live", type: "L1Unit", properties: {} }],
          links: [],
        }),
    ],
    ["/project-graph", () => json(graphResponse(["trial-only"]))],
  ])
  window.history.pushState({}, "", "/p/p1/evals/t/r/trial-1")
  render(<App />)

  await waitFor(() =>
    expect(screen.getByTestId("graph-canvas").textContent).toBe("trial-only"),
  )
  expect(calls.some((url) => url.includes("/projects/p1/graph"))).toBe(false)
  expect(calls.filter((url) => url.endsWith("/snapshot"))).toHaveLength(1)
  window.history.pushState({}, "", "/")
})
