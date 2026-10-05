import { act, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, vi } from "vitest"
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom"
import { RunsPage } from "./RunsPage"
import type { ProjectUsage } from "../api/types"

const RUN = {
  run_id: "r1",
  project_id: "p1",
  project_name: "acme",
  status: "running",
  liveness: "stalled" as const,
  current_phase: 1,
  started_at: null,
  last_heartbeat_at: null,
  jobs: { total: 2, in_progress: 0, success: 1, degraded: 1, skipped: 0, failed: 0 },
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

const RUNS_BODY = { liveness_ttl_seconds: 30, runs: [RUN] }

// --- the verified server contract -------------------------------------------------

type AgentTotals = ProjectUsage["by_agent"][string]

// One agent's (or the project's) token distribution. The live ledger reports
// the context split (cached/uncached), the generated split (reasoning/visible),
// the total, the total minus cache reads, and the call count.
function agentTotals(over: Partial<AgentTotals> = {}): AgentTotals {
  return {
    context_tokens: { cached: 10, uncached: 20 },
    generated_tokens: { reasoning: 5, visible: 15 },
    total_tokens: 50,
    capped_tokens: 40,
    calls: 2,
    ...over,
  }
}

function usage(over: Partial<ProjectUsage> = {}): ProjectUsage {
  return {
    project_id: "p1",
    ...agentTotals(),
    by_agent: { recon: agentTotals() },
    ...over,
  }
}

function routedFetch(handlers: {
  runs?: () => Response | Promise<Response>
  usage?: (projectId: string) => Response | Promise<Response>
}): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes("/usage")) {
      const projectId = url.match(/\/projects\/([^/]+)\/usage/)?.[1] ?? ""
      return handlers.usage ? handlers.usage(projectId) : json(usage())
    }
    return handlers.runs ? handlers.runs() : json(RUNS_BODY)
  }) as typeof fetch
}

function renderRuns() {
  return render(
    <MemoryRouter initialEntries={["/p/p1/runs"]}>
      <Routes>
        <Route path="/p/:projectId/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

// The project-level counters carry a stable hook so a test reads the value
// itself, not whatever else happens to render the same digits.
function counter(field: string): string {
  return document.querySelector(`[data-usage="${field}"]`)?.textContent ?? ""
}

function usagePanel(): HTMLElement {
  return screen.getByRole("region", { name: "Usage corrente progetto" })
}

afterEach(() => {
  vi.useRealTimers()
})

test("runs page shows a stalled badge", async () => {
  globalThis.fetch = routedFetch({})
  renderRuns()
  await waitFor(() => expect(screen.getByText(/stalled/i)).toBeDefined())
})

test("shows every project counter and the same counters per agent", async () => {
  globalThis.fetch = routedFetch({})
  renderRuns()

  await waitFor(() => expect(counter("cached")).toBe("10"))
  expect(counter("uncached")).toBe("20")
  expect(counter("reasoning")).toBe("5")
  expect(counter("visible")).toBe("15")
  expect(counter("total")).toBe("50")
  expect(counter("capped")).toBe("40")
  expect(counter("calls")).toBe("2")

  const row = screen.getByRole("row", { name: /recon/ })
  const cells = within(row).getAllByRole("cell").map((cell) => cell.textContent)
  expect(cells).toEqual(["10", "20", "5", "15", "50", "40", "2"])
})

test("successive snapshots replace the values, including a decrease after a reset", async () => {
  vi.useFakeTimers()
  let body = usage()
  globalThis.fetch = routedFetch({ usage: () => json(body) })
  renderRuns()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  expect(counter("total")).toBe("50")

  // The process restarted: the cumulative counters dropped to zero.
  body = usage({
    context_tokens: { cached: 0, uncached: 0 },
    generated_tokens: { reasoning: 0, visible: 0 },
    total_tokens: 0,
    capped_tokens: 0,
    calls: 0,
    by_agent: {},
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500)
  })
  expect(counter("total")).toBe("0")
  // Never the sum of the two snapshots.
  expect(counter("total")).not.toBe("50")
})

test("all-zero counters are shown as zero, never as unavailable", async () => {
  globalThis.fetch = routedFetch({
    usage: () =>
      json(
        usage({
          context_tokens: { cached: 0, uncached: 0 },
          generated_tokens: { reasoning: 0, visible: 0 },
          total_tokens: 0,
          capped_tokens: 0,
          calls: 0,
          by_agent: {},
        }),
      ),
  })
  renderRuns()

  await waitFor(() => expect(counter("total")).toBe("0"))
  for (const field of ["cached", "uncached", "reasoning", "visible", "capped", "calls"]) {
    expect(counter(field)).toBe("0")
  }
  expect(within(usagePanel()).queryByText(/non disponibile/i)).toBeNull()
})

test("an empty agent breakdown keeps the project panel and invents no rows", async () => {
  globalThis.fetch = routedFetch({ usage: () => json(usage({ by_agent: {} })) })
  renderRuns()

  await waitFor(() => expect(counter("total")).toBe("50"))
  expect(usagePanel()).toBeDefined()
  expect(document.querySelector(".runs-usage-agents")).toBeNull()
})

const MALFORMED_BODIES: unknown[] = [
  { ...usage(), context_tokens: undefined },
  { ...usage(), context_tokens: null },
  { ...usage(), context_tokens: { cached: 10 } },
  { ...usage(), context_tokens: { cached: "10", uncached: 20 } },
  { ...usage(), context_tokens: { cached: -1, uncached: 20 } },
  { ...usage(), context_tokens: { cached: 1.5, uncached: 20 } },
  { ...usage(), context_tokens: { cached: true, uncached: 20 } },
  { ...usage(), generated_tokens: { reasoning: 5, visible: null } },
  { ...usage(), total_tokens: null },
  { ...usage(), capped_tokens: "40" },
  { ...usage(), calls: 2.5 },
  { ...usage(), project_id: undefined },
  { ...usage(), by_agent: [] },
  { ...usage(), by_agent: { recon: agentTotals({ total_tokens: null as unknown as number }) } },
  { ...usage(), by_agent: { recon: 5 } },
  { ...usage(), by_agent: { recon: { ...agentTotals(), context_tokens: "10/20" } } },
]

for (const [index, body] of MALFORMED_BODIES.entries()) {
  test(`a malformed usage body (${index}) is unavailable and leaves the runs readable`, async () => {
    globalThis.fetch = routedFetch({ usage: () => json(body) })
    renderRuns()

    await waitFor(() =>
      expect(within(usagePanel()).getByText(/usage non disponibile/i)).toBeDefined(),
    )
    expect(counter("total")).toBe("")
    expect(screen.getByText(/stalled/i)).toBeDefined()
  })
}

test("an endpoint error never hides the runs", async () => {
  globalThis.fetch = routedFetch({ usage: () => json({ detail: "boom" }, 500) })
  renderRuns()

  await waitFor(() => expect(screen.getByText(/stalled/i)).toBeDefined())
  expect(within(usagePanel()).getByText(/usage non disponibile/i)).toBeDefined()
})

// A router whose navigate function the test can call to switch project route.
let navigateTo: ((to: string) => void) | null = null

function Probe() {
  navigateTo = useNavigate()
  return null
}

function probeRouter(initial: string) {
  return (
    <MemoryRouter initialEntries={[initial]}>
      <Probe />
      <Routes>
        <Route path="/p/:projectId/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>
  )
}

test("a project change clears the previous project's counters immediately", async () => {
  globalThis.fetch = routedFetch({
    usage: (projectId) =>
      projectId === "p1"
        ? json(usage({ project_id: "p1", ...agentTotals({ total_tokens: 4242 }) }))
        : new Promise<Response>(() => {}), // the new project has not answered yet
  })

  render(probeRouter("/p/p1/runs"))
  await waitFor(() => expect(counter("total")).toBe("4242"))

  await act(async () => {
    navigateTo?.("/p/p2/runs")
    await Promise.resolve()
  })

  // Before the new project answers, nothing of the old one may remain.
  expect(counter("total")).toBe("")
  expect(within(usagePanel()).queryByText("4242")).toBeNull()
})

test("a late response for the previous project never lands on the new one", async () => {
  let resolveOld!: (value: Response) => void
  const oldResponse = new Promise<Response>((resolve) => {
    resolveOld = resolve
  })
  globalThis.fetch = routedFetch({
    usage: (projectId) =>
      projectId === "p1"
        ? oldResponse
        : json(usage({ project_id: "p2", ...agentTotals({ total_tokens: 7 }) })),
  })

  render(probeRouter("/p/p1/runs"))
  await act(async () => {
    navigateTo?.("/p/p2/runs")
    await Promise.resolve()
  })
  await waitFor(() => expect(counter("total")).toBe("7"))

  await act(async () => {
    resolveOld(json(usage({ project_id: "p1", ...agentTotals({ total_tokens: 9999 }) })))
    await Promise.resolve()
  })
  expect(counter("total")).toBe("7")
})

test("polling never overlaps a request that is still in flight", async () => {
  vi.useFakeTimers()
  let usageCalls = 0
  globalThis.fetch = routedFetch({
    usage: () => {
      usageCalls += 1
      return new Promise<Response>(() => {}) // never resolves
    },
  })
  renderRuns()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000)
  })
  expect(usageCalls).toBe(1)
})

test("labels the counters as cumulative and attributing them to no single run", async () => {
  globalThis.fetch = routedFetch({})
  renderRuns()

  await waitFor(() => expect(counter("total")).toBe("50"))
  const panel = usagePanel().textContent ?? ""
  expect(panel).toContain("Contatori cumulativi del progetto")
  expect(panel).toContain("non rappresentano la dimensione del contesto corrente")
  // capped_tokens is not the trial budget, and no counter belongs to one run.
  expect(panel).not.toMatch(/budget/i)
  expect(panel).not.toMatch(/del run|per run/i)
})
