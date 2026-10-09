import { StrictMode } from "react"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, expect, test, vi } from "vitest"
import { App } from "../App"
import type { ProjectState } from "../api/types"
import { LivePage } from "./LivePage"

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function project(partial: Partial<ProjectState> & { project_id: string }): ProjectState {
  return {
    project_name: partial.project_id,
    in_flight: true,
    recon: [],
    analysis: [],
    hunting: [],
    ...partial,
  }
}

function recon(id: string, liveness: "live" | "stalled" = "live") {
  return {
    run_id: id,
    project_id: "p",
    project_name: "p",
    status: "running",
    liveness,
    current_phase: 1,
    started_at: null,
    last_heartbeat_at: null,
    jobs: { total: 3, in_progress: 1, success: 1, degraded: 0, skipped: 0, failed: 1 },
  }
}

const analysis = (id: string) => ({
  analysis_run_id: id,
  run_id: "parent",
  project_id: "p",
  status: "draining",
  started_at: null,
})

const hunting = (id: string) => ({
  hunting_run_id: id,
  project_id: "p",
  status: "running",
  started_at: null,
  finished_at: null,
})

function usage(projectId: string, total: number, calls: number, byAgent: Record<string, unknown>) {
  const by_agent = Object.fromEntries(Object.entries(byAgent).map(([name, raw]) => {
    const agent = raw as { input_tokens: number; output_tokens: number; total_tokens: number; calls: number }
    return [name, {
      context_tokens: { cached: 0, uncached: agent.input_tokens },
      generated_tokens: { reasoning: 0, visible: agent.output_tokens },
      total_tokens: agent.total_tokens,
      capped_tokens: agent.total_tokens,
      calls: agent.calls,
    }]
  }))
  return {
    project_id: projectId, total_tokens: total, capped_tokens: total, calls, by_agent,
    context_tokens: { cached: 0, uncached: Object.values(by_agent).reduce((sum, agent) => sum + agent.context_tokens.uncached, 0) },
    generated_tokens: { reasoning: 0, visible: Object.values(by_agent).reduce((sum, agent) => sum + agent.generated_tokens.visible, 0) },
  }
}

// A per-path fetch stub: the first route whose needle is a substring of the
// request URL wins, and every call is recorded so a test can inspect polling.
function routeFetch(
  routes: Array<[string, (url: string) => Response | Promise<Response>]>,
): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    for (const [needle, handler] of routes) {
      if (url.includes(needle)) return handler(url)
    }
    throw new Error(`unexpected fetch: ${url}`)
  }) as typeof fetch
  return calls
}

function card(projectId: string): HTMLElement {
  const node = document.querySelector<HTMLElement>(`[data-project-id="${projectId}"]`)
  if (!node) throw new Error(`no card for ${projectId}`)
  return node
}

function abortError(): Error {
  const error = new Error("aborted")
  error.name = "AbortError"
  return error
}

// A request that never settles on its own but rejects when its signal aborts,
// mirroring how a real fetch behaves under AbortController.
function holdOpen(signal: AbortSignal): Promise<Response> {
  return new Promise((_resolve, reject) => {
    if (signal.aborted) return reject(abortError())
    signal.addEventListener("abort", () => reject(abortError()))
  })
}

// A signal-aware fetch stub: `route` sees each request's URL and AbortSignal,
// and per-endpoint concurrency is tracked so a test can prove nothing overlaps.
function makeFetch(
  route: (url: string, signal: AbortSignal) => Response | Promise<Response>,
) {
  const calls: string[] = []
  const peak = new Map<string, number>()
  const active = new Map<string, number>()
  const keyFor = (url: string) => {
    const match = /\/projects\/([^/]+)\/usage/.exec(url)
    if (match) return `usage:${match[1]}`
    const appState = /\/app-state/.exec(url)
    return appState ? "app-state" : url
  }
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    calls.push(url)
    const key = keyFor(url)
    const concurrent = (active.get(key) ?? 0) + 1
    active.set(key, concurrent)
    peak.set(key, Math.max(peak.get(key) ?? 0, concurrent))
    try {
      return await route(url, init?.signal as AbortSignal)
    } finally {
      active.set(key, (active.get(key) ?? 1) - 1)
    }
  }) as typeof fetch
  return { calls, peak }
}

async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

afterEach(() => {
  vi.useRealTimers()
  window.history.pushState({}, "", "/")
})

// --- active projects per run class ----------------------------------------------

test("shows active projects for each run class and hides the idle ones", async () => {
  routeFetch([
    [
      "/app-state",
      () =>
        json({
          idle: false,
          projects: [
            project({ project_id: "p-recon", recon: [recon("r1", "stalled")] }),
            project({ project_id: "p-analysis", analysis: [analysis("a1")] }),
            project({ project_id: "p-hunting", hunting: [hunting("h1")] }),
            project({ project_id: "p-idle", in_flight: false }),
          ],
        }),
    ],
    ["/usage", (url) => json(usage(url.split("/")[2], 0, 0, {}))],
  ])
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getByText("r1")).toBeDefined())
  expect(screen.getByText("a1")).toBeDefined()
  expect(screen.getByText("h1")).toBeDefined()
  // The stalled recon run stays visible, spelled out.
  expect(screen.getByText("stalled")).toBeDefined()
  // Each class renders its own labelled group.
  expect(screen.getByRole("region", { name: "recon runs" })).toBeDefined()
  expect(screen.getByRole("region", { name: "analysis runs" })).toBeDefined()
  expect(screen.getByRole("region", { name: "hunting runs" })).toBeDefined()
  // The idle project is not shown at all.
  expect(screen.queryByText("p-idle")).toBeNull()
  expect(card("p-recon")).toBeDefined()
})

// --- usage totals and isolation -------------------------------------------------

test("totals input and output over by_agent and keeps projects isolated", async () => {
  routeFetch([
    [
      "/app-state",
      () =>
        json({
          idle: false,
          projects: [
            project({ project_id: "p1", recon: [recon("r1")] }),
            project({ project_id: "p2", hunting: [hunting("h1")] }),
          ],
        }),
    ],
    [
      "/projects/p1/usage",
      () =>
        json(
          usage("p1", 300, 3, {
            alpha: { input_tokens: 100, output_tokens: 200, total_tokens: 300, calls: 2 },
            beta: { input_tokens: 0, output_tokens: 0, total_tokens: 0, calls: 1 },
          }),
        ),
    ],
    [
      "/projects/p2/usage",
      () =>
        json(
          usage("p2", 50, 1, {
            gamma: { input_tokens: 20, output_tokens: 30, total_tokens: 50, calls: 1 },
          }),
        ),
    ],
  ])
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )

  await waitFor(() => expect(within(card("p1")).getByText("300")).toBeDefined())
  const p1 = within(card("p1"))
  expect(p1.getByText("100")).toBeDefined() // input = 100 + 0
  expect(p1.getByText("200")).toBeDefined() // output = 200 + 0
  expect(p1.getByText("3")).toBeDefined() // calls

  const p2 = within(card("p2"))
  expect(p2.getByText("50")).toBeDefined()
  expect(p2.getByText("20")).toBeDefined()
  expect(p2.getByText("30")).toBeDefined()
  expect(p2.getByText("1")).toBeDefined()
  // No bleed: p2's single agent never shows up as part of p1's totals.
  expect(p1.queryByText("50")).toBeNull()
})

// --- polling --------------------------------------------------------------------

test("the next poll refreshes both the runs and the tokens", async () => {
  vi.useFakeTimers()
  let pass = 0
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    if (url.includes("/app-state")) {
      pass += 1
      return json({
        idle: false,
        projects: [project({ project_id: "p1", recon: [recon(`r${pass}`)] })],
      })
    }
    if (url.includes("/usage")) {
      return json(
        usage("p1", pass * 100, pass, {
          a: {
            input_tokens: pass * 40,
            output_tokens: pass * 60,
            total_tokens: pass * 100,
            calls: pass,
          },
        }),
      )
    }
    throw new Error(url)
  }) as typeof fetch

  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await flush()
  await flush()
  expect(screen.getByText("r1")).toBeDefined()
  expect(within(card("p1")).getByText("100")).toBeDefined()

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500)
  })
  await flush()
  expect(screen.getByText("r2")).toBeDefined()
  expect(screen.queryByText("r1")).toBeNull()
  expect(within(card("p1")).getByText("200")).toBeDefined()
})

// --- shared states --------------------------------------------------------------

test("shows a loading state before the app state resolves", () => {
  globalThis.fetch = (() => new Promise<Response>(() => {})) as typeof fetch
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  expect(screen.getByText(/loading live projects/i)).toBeDefined()
})

test("shows an empty state when nothing is in flight", async () => {
  routeFetch([
    [
      "/app-state",
      () =>
        json({ idle: true, projects: [project({ project_id: "p-idle", in_flight: false })] }),
    ],
  ])
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByText(/no projects in flight/i)).toBeDefined())
  expect(document.querySelectorAll("[data-project-id]")).toHaveLength(0)
})

test("an app-state failure is a page-level error", async () => {
  routeFetch([["/app-state", () => json({ detail: "unavailable" }, 503)]])
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByText(/live state unavailable/i)).toBeDefined()
  expect(screen.queryByText(/no projects in flight/i)).toBeNull()
})

test("a usage failure stays local to its project", async () => {
  routeFetch([
    [
      "/app-state",
      () =>
        json({
          idle: false,
          projects: [
            project({ project_id: "p1", recon: [recon("r1")] }),
            project({ project_id: "p2", hunting: [hunting("h1")] }),
          ],
        }),
    ],
    ["/projects/p1/usage", () => json({ detail: "boom" }, 500)],
    [
      "/projects/p2/usage",
      () =>
        json(
          usage("p2", 7, 1, {
            a: { input_tokens: 3, output_tokens: 4, total_tokens: 7, calls: 1 },
          }),
        ),
    ],
  ])
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )

  await waitFor(() => expect(within(card("p1")).getByRole("alert")).toBeDefined())
  expect(within(card("p1")).getByText(/token usage unavailable/i)).toBeDefined()
  // p2 is unaffected, and the failure never blanks it to zero.
  expect(within(card("p2")).getByText("7")).toBeDefined()
  expect(screen.queryByText(/live state unavailable/i)).toBeNull()
})

test("a failed refresh keeps the last tokens and marks them stale", async () => {
  vi.useFakeTimers()
  let usageCalls = 0
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    if (url.includes("/app-state")) {
      return json({
        idle: false,
        projects: [project({ project_id: "p1", recon: [recon("r1")] })],
      })
    }
    if (url.includes("/usage")) {
      usageCalls += 1
      if (usageCalls === 1) {
        return json(
          usage("p1", 300, 3, {
            a: { input_tokens: 100, output_tokens: 200, total_tokens: 300, calls: 3 },
          }),
        )
      }
      return json({ detail: "boom" }, 500)
    }
    throw new Error(url)
  }) as typeof fetch

  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await flush()
  await flush()
  expect(within(card("p1")).getByText("300")).toBeDefined()
  expect(within(card("p1")).queryByText(/not up to date/i)).toBeNull()

  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500)
  })
  await flush()
  // The numbers survive the failure...
  expect(within(card("p1")).getByText("300")).toBeDefined()
  // ...marked as not refreshed, and never replaced with zero.
  expect(within(card("p1")).getByText(/not up to date/i)).toBeDefined()
  expect(screen.queryByText("0")).toBeNull()
})

// --- cleanup and global navigation ----------------------------------------------

test("clears its polling timer when the page unmounts", async () => {
  vi.useFakeTimers()
  const calls = routeFetch([["/app-state", () => json({ idle: true, projects: [] })]])
  const clearSpy = vi.spyOn(globalThis, "clearInterval")
  const { unmount } = render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await flush()
  await flush()
  const before = calls.length

  unmount()
  expect(clearSpy).toHaveBeenCalled()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000)
  })
  expect(calls.length).toBe(before)
})

test("the global nav reaches the live board at /live", async () => {
  routeFetch([
    ["/app-state", () => json({ idle: true, projects: [] })],
    ["/projects", () => json({ projects: [] })],
    [
      "/snapshot",
      () =>
        json({
          dataset: { id: "d", name: "D" },
          summary: { targets: 0, trials: 0, identified: 0, partial: 0, missed: 0, degraded: 0 },
          targets: [],
          trials: [],
          versions: [],
          coverage: {
            targets: { tested: 0, with_identified: 0, without_identified: 0 },
            vulnerabilities: { total: 0, found: 0, not_found: 0, partial: 0 },
          },
          successes: [],
          degraded_trials: [],
        }),
    ],
  ])
  window.history.pushState({}, "", "/")
  render(<App />)

  const live = await screen.findByRole("link", { name: "Live" })
  expect(live.getAttribute("href")).toBe("/live")
  fireEvent.click(live)

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Live" })).toBeDefined(),
  )
  expect(window.location.pathname).toBe("/live")
  expect(screen.getByRole("link", { name: "Live" }).getAttribute("aria-current")).toBe("page")
})

// --- independent, non-blocking reads --------------------------------------------

test("a slow usage read never blocks another project's usage", async () => {
  makeFetch((url, signal) => {
    if (url.includes("/app-state")) {
      return json({
        idle: false,
        projects: [
          project({ project_id: "p1", recon: [recon("r1")] }),
          project({ project_id: "p2", hunting: [hunting("h1")] }),
        ],
      })
    }
    if (url.includes("/projects/p1/usage")) return holdOpen(signal)
    if (url.includes("/projects/p2/usage")) {
      return json(
        usage("p2", 50, 1, {
          a: { input_tokens: 20, output_tokens: 30, total_tokens: 50, calls: 1 },
        }),
      )
    }
    throw new Error(url)
  })
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )

  // p1 is still pending; p2's numbers land anyway.
  await waitFor(() => expect(within(card("p2")).getByText("50")).toBeDefined())
  expect(within(card("p1")).getByText(/loading token usage/i)).toBeDefined()
})

test("app-state keeps polling runs while a usage read is pending", async () => {
  vi.useFakeTimers()
  let pass = 0
  makeFetch((url, signal) => {
    if (url.includes("/app-state")) {
      pass += 1
      return json({
        idle: false,
        projects: [project({ project_id: "p1", recon: [recon(`r${pass}`)] })],
      })
    }
    if (url.includes("/usage")) return holdOpen(signal)
    throw new Error(url)
  })
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await flush()
  await flush()
  expect(screen.getByText("r1")).toBeDefined()

  // The usage read for p1 is still hanging, yet the runs advance.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500)
  })
  await flush()
  expect(screen.getByText("r2")).toBeDefined()
  expect(within(card("p1")).getByText(/loading token usage/i)).toBeDefined()
})

test("never runs two requests against the same endpoint at once", async () => {
  vi.useFakeTimers()
  // Both endpoints take 6s, longer than one poll, so a tick lands mid-flight.
  const slow = (body: unknown) => (signal: AbortSignal) =>
    new Promise<Response>((resolve, reject) => {
      const timer = setTimeout(() => resolve(json(body)), 6000)
      signal.addEventListener("abort", () => {
        clearTimeout(timer)
        reject(abortError())
      })
    })
  const { calls, peak } = makeFetch((url, signal) => {
    if (url.includes("/app-state")) {
      return slow({
        idle: false,
        projects: [project({ project_id: "p1", recon: [recon("r1")] })],
      })(signal)
    }
    if (url.includes("/usage")) return slow(usage("p1", 300, 1, {}))(signal)
    throw new Error(url)
  })
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )

  // Two ticks elapse while the first app-state read is still open: it must not
  // stack a second one.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })
  expect(calls.filter((url) => url.includes("/app-state"))).toHaveLength(1)

  // Let the app-state read land, which starts p1's usage read; a later tick
  // must not stack a second usage read while the first is open.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3500)
  })
  await flush()
  // Ticks kept firing (two state reads), yet neither endpoint ever ran two at
  // once - and the second state read did not stack a second usage read.
  expect(calls.filter((url) => url.includes("/app-state"))).toHaveLength(2)
  expect(peak.get("app-state")).toBe(1)
  expect(peak.get("usage:p1")).toBe(1)
  expect(calls.filter((url) => url.includes("/projects/p1/usage"))).toHaveLength(1)
})

// --- timeouts -------------------------------------------------------------------

test("a usage read times out at 10s, frees its slot, and retries", async () => {
  vi.useFakeTimers()
  const signals: AbortSignal[] = []
  let usageCalls = 0
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    const signal = init?.signal as AbortSignal
    if (url.includes("/app-state")) {
      return json({
        idle: false,
        projects: [project({ project_id: "p1", recon: [recon("r1")] })],
      })
    }
    if (url.includes("/usage")) {
      usageCalls += 1
      signals.push(signal)
      if (usageCalls === 1) return holdOpen(signal)
      return json(
        usage("p1", 400, 2, {
          a: { input_tokens: 150, output_tokens: 250, total_tokens: 400, calls: 2 },
        }),
      )
    }
    throw new Error(url)
  }) as typeof fetch
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await flush()
  await flush()
  expect(within(card("p1")).getByText(/loading token usage/i)).toBeDefined()

  // The 10s deadline aborts the hanging read; with no previous value the local
  // error shows (never a zero).
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000)
  })
  await flush()
  expect(signals[0].aborted).toBe(true)
  expect(within(card("p1")).getByRole("alert")).toBeDefined()
  expect(screen.queryByText("0")).toBeNull()

  // The slot was released: the next tick issues a fresh read that succeeds.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500)
  })
  await flush()
  await flush()
  expect(usageCalls).toBe(2)
  expect(within(card("p1")).getByText("400")).toBeDefined()
  expect(within(card("p1")).queryByRole("alert")).toBeNull()
})

test("after a usage timeout a later read clears the stale marker", async () => {
  vi.useFakeTimers()
  let usageCalls = 0
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    const signal = init?.signal as AbortSignal
    if (url.includes("/app-state")) {
      return json({
        idle: false,
        projects: [project({ project_id: "p1", recon: [recon("r1")] })],
      })
    }
    if (url.includes("/usage")) {
      usageCalls += 1
      if (usageCalls === 1) {
        return json(
          usage("p1", 300, 3, {
            a: { input_tokens: 100, output_tokens: 200, total_tokens: 300, calls: 3 },
          }),
        )
      }
      if (usageCalls === 2) return holdOpen(signal)
      return json(
        usage("p1", 500, 5, {
          a: { input_tokens: 200, output_tokens: 300, total_tokens: 500, calls: 5 },
        }),
      )
    }
    throw new Error(url)
  }) as typeof fetch
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await flush()
  await flush()
  expect(within(card("p1")).getByText("300")).toBeDefined()

  // Second read starts on the next tick, hangs, and hits the 10s deadline.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500)
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000)
  })
  await flush()
  // The last reading survives, marked stale - not replaced with zero.
  expect(within(card("p1")).getByText("300")).toBeDefined()
  expect(within(card("p1")).getByText(/not up to date/i)).toBeDefined()

  // The next allowed read succeeds and clears the marker.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500)
  })
  await flush()
  await flush()
  expect(within(card("p1")).getByText("500")).toBeDefined()
  expect(within(card("p1")).queryByText(/not up to date/i)).toBeNull()
})

test("an app-state timeout shows the page error and recovers next update", async () => {
  vi.useFakeTimers()
  let appCalls = 0
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    const signal = init?.signal as AbortSignal
    if (url.includes("/app-state")) {
      appCalls += 1
      // The first read hangs into its deadline; the retry answers a moment
      // later, so the error is observable before the recovery lands.
      if (appCalls === 1) return holdOpen(signal)
      return new Promise<Response>((resolve, reject) => {
        const timer = setTimeout(() => resolve(json({ idle: true, projects: [] })), 3000)
        signal.addEventListener("abort", () => {
          clearTimeout(timer)
          reject(abortError())
        })
      })
    }
    throw new Error(url)
  }) as typeof fetch
  render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await flush()

  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000)
  })
  await flush()
  expect(screen.getByRole("alert")).toBeDefined()
  expect(screen.getByText(/live state unavailable/i)).toBeDefined()

  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000)
  })
  await flush()
  expect(screen.queryByText(/live state unavailable/i)).toBeNull()
  expect(screen.getByText(/no projects in flight/i)).toBeDefined()
})

// --- unmount and StrictMode -----------------------------------------------------

test("unmount aborts every request and cancels every timer", async () => {
  vi.useFakeTimers()
  const signals: AbortSignal[] = []
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    const signal = init?.signal as AbortSignal
    if (url.includes("/app-state")) {
      return json({
        idle: false,
        projects: [project({ project_id: "p1", recon: [recon("r1")] })],
      })
    }
    if (url.includes("/usage")) {
      signals.push(signal)
      return holdOpen(signal)
    }
    throw new Error(url)
  }) as typeof fetch
  const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval")
  const { unmount } = render(
    <MemoryRouter>
      <LivePage />
    </MemoryRouter>,
  )
  await flush()
  await flush()
  // One poll interval plus at least one 10s deadline are outstanding.
  expect(vi.getTimerCount()).toBeGreaterThan(0)
  expect(signals[0].aborted).toBe(false)

  unmount()

  expect(clearIntervalSpy).toHaveBeenCalled()
  expect(signals[0].aborted).toBe(true)
  // Interval and deadlines are gone, so nothing can fire on the dead tree.
  expect(vi.getTimerCount()).toBe(0)
  await flush()
  expect(vi.getTimerCount()).toBe(0)
})

test("the board works under StrictMode's double-invoked effect", async () => {
  makeFetch((url, signal) => {
    if (url.includes("/app-state")) {
      return json({
        idle: false,
        projects: [project({ project_id: "p1", recon: [recon("r1")] })],
      })
    }
    if (url.includes("/usage")) {
      void signal
      return json(
        usage("p1", 300, 3, {
          a: { input_tokens: 100, output_tokens: 200, total_tokens: 300, calls: 3 },
        }),
      )
    }
    throw new Error(url)
  })
  render(
    <StrictMode>
      <MemoryRouter>
        <LivePage />
      </MemoryRouter>
    </StrictMode>,
  )

  // The mount/unmount/mount cycle still lands a single, correct board.
  await waitFor(() => expect(within(card("p1")).getByText("300")).toBeDefined())
  expect(screen.getByText("r1")).toBeDefined()
})

test("shows cached and reasoning tokens from the current backend contract", async () => {
  const counters = {
    context_tokens: { cached: 50, uncached: 75 },
    generated_tokens: { reasoning: 40, visible: 110 },
    total_tokens: 275, capped_tokens: 225, calls: 3,
  }
  routeFetch([
    ["/app-state", () => json({ idle: false, projects: [project({ project_id: "p1", recon: [recon("r1")] })] })],
    ["/projects/p1/usage", () => json({ project_id: "p1", ...counters, by_agent: { recon: counters } })],
  ])
  render(<MemoryRouter><LivePage /></MemoryRouter>)
  await waitFor(() => expect(within(card("p1")).getByText("275")).toBeDefined())
  expect(within(card("p1")).getByText("125")).toBeDefined()
  expect(within(card("p1")).getByText("150")).toBeDefined()
})
