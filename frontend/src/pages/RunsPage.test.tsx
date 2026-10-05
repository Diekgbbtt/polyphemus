import { act, render, screen, waitFor } from "@testing-library/react"
import { afterEach, vi } from "vitest"
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom"
import { RunsPage } from "./RunsPage"

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

// The endpoint's verified wire shape: project totals plus the per-agent
// breakdown. There is deliberately no cached/uncached field and no per-run
// attribution, so the page must not invent either.
function usage(total: number, calls = 1) {
  return {
    project_id: "p1",
    total_tokens: total,
    calls,
    by_agent: { recon: { input_tokens: total - 1, output_tokens: 1, total_tokens: total, calls } },
  }
}

function usageTotal(): string {
  return document.querySelector('[data-usage="total"]')?.textContent ?? ""
}

function routedFetch(handlers: {
  runs?: () => Response | Promise<Response>
  usage?: (projectId: string) => Response | Promise<Response>
}): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes("/usage")) {
      const projectId = url.match(/\/projects\/([^/]+)\/usage/)?.[1] ?? ""
      return handlers.usage ? handlers.usage(projectId) : json(usage(0, 0))
    }
    return handlers.runs ? handlers.runs() : json(RUNS_BODY)
  }) as typeof fetch
}

afterEach(() => {
  vi.useRealTimers()
})

test("runs page shows a stalled badge", async () => {
  globalThis.fetch = routedFetch({})
  render(
    <MemoryRouter initialEntries={["/p/p1/runs"]}>
      <Routes>
        <Route path="/p/:projectId/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByText(/stalled/i)).toBeDefined())
})

test("consecutive usage snapshots replace the value instead of accumulating", async () => {
  vi.useFakeTimers()
  let total = 100
  globalThis.fetch = routedFetch({ usage: () => json(usage(total)) })

  render(
    <MemoryRouter initialEntries={["/p/p1/runs"]}>
      <Routes>
        <Route path="/p/:projectId/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>,
  )
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  expect(usageTotal()).toBe("100")

  total = 175
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500)
  })
  expect(usageTotal()).toBe("175")
  // The two snapshots are never summed into 275.
  expect(usageTotal()).not.toBe("275")
})

test("absent cached/uncached fields are never synthesized", async () => {
  globalThis.fetch = routedFetch({ usage: () => json(usage(42)) })
  render(
    <MemoryRouter initialEntries={["/p/p1/runs"]}>
      <Routes>
        <Route path="/p/:projectId/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>,
  )
  await waitFor(() => expect(usageTotal()).toBe("42"))
  expect(screen.queryByText(/cached/i)).toBeNull()
  expect(screen.queryByText(/uncached/i)).toBeNull()
  expect(screen.queryByText(/contesto corrente/i)).toBeNull()
})

test("a usage error leaves the runs list readable", async () => {
  globalThis.fetch = routedFetch({ usage: () => json({ detail: "boom" }, 500) })
  render(
    <MemoryRouter initialEntries={["/p/p1/runs"]}>
      <Routes>
        <Route path="/p/:projectId/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByText(/stalled/i)).toBeDefined())
  expect(screen.getByText(/usage non disponibile/i)).toBeDefined()
})

test("a project change drops the previous project's usage response", async () => {
  let resolveOld!: (value: Response) => void
  const oldResponse = new Promise<Response>((resolve) => {
    resolveOld = resolve
  })
  let navigate!: (to: string) => void
  globalThis.fetch = routedFetch({
    usage: (projectId) => (projectId === "p1" ? oldResponse : json(usage(200))),
  })

  function Probe() {
    navigate = useNavigate()
    return null
  }

  render(
    <MemoryRouter initialEntries={["/p/p1/runs"]}>
      <Probe />
      <Routes>
        <Route path="/p/:projectId/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>,
  )
  await act(async () => {
    await Promise.resolve()
  })

  await act(async () => {
    navigate("/p/p2/runs")
    await Promise.resolve()
  })
  await waitFor(() => expect(usageTotal()).toBe("200"))

  await act(async () => {
    resolveOld(json(usage(111)))
    await Promise.resolve()
  })
  expect(usageTotal()).not.toBe("111")
  expect(usageTotal()).toBe("200")
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
  render(
    <MemoryRouter initialEntries={["/p/p1/runs"]}>
      <Routes>
        <Route path="/p/:projectId/runs" element={<RunsPage />} />
      </Routes>
    </MemoryRouter>,
  )
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000)
  })
  expect(usageCalls).toBe(1)
})
