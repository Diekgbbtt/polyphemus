import { act, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, expect, test, vi } from "vitest"
import type { ProjectUsage, UsageTokens } from "../api/types"
import { ProjectUsageSummary } from "./ProjectUsageSummary"

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function agent(over: Partial<UsageTokens> = {}): UsageTokens {
  return {
    context_tokens: { cached: 10, uncached: 20 },
    generated_tokens: { reasoning: 5, visible: 15 },
    total_tokens: 50,
    capped_tokens: 40,
    calls: 3,
    ...over,
  }
}

function usageBody(projectId: string, over: Partial<ProjectUsage> = {}): ProjectUsage {
  return {
    project_id: projectId,
    context_tokens: { cached: 10, uncached: 20 },
    generated_tokens: { reasoning: 5, visible: 15 },
    total_tokens: 50,
    capped_tokens: 40,
    calls: 3,
    by_agent: { recon: agent() },
    ...over,
  }
}

// A request the test can leave open across a poll, so the loading and
// no-previous-project states are observable.
function holdOpen(signal: AbortSignal): Promise<Response> {
  return new Promise((_resolve, reject) => {
    if (signal.aborted) return reject(new Error("aborted"))
    signal.addEventListener("abort", () => reject(new Error("aborted")))
  })
}

function stubUsage(
  handler: (url: string, signal: AbortSignal) => Response | Promise<Response>,
): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    calls.push(url)
    return handler(url, init?.signal as AbortSignal)
  }) as typeof fetch
  return calls
}

function chipValue(): string {
  const el = document.querySelector("[data-project-tokens]")
  if (!el) throw new Error("no project tokens chip")
  return el.textContent ?? ""
}

function chipValues(): string[] {
  return [...document.querySelectorAll("[data-project-tokens]")].map((el) => el.textContent ?? "")
}

function renderSummary(projectId: string | null) {
  return render(
    <ul>
      <ProjectUsageSummary projectId={projectId} />
    </ul>,
  )
}

afterEach(() => {
  vi.useRealTimers()
})

test("shows the project's total tokens when the reading is available", async () => {
  stubUsage(() => json(usageBody("p1", { total_tokens: 900 })))
  renderSummary("p1")

  await waitFor(() => expect(chipValue()).toBe("900"))
  expect(screen.getByText("Project tokens")).toBeDefined()
})

test("a valid zero is shown as zero", async () => {
  stubUsage(() => json(usageBody("p1", { total_tokens: 0, by_agent: {} })))
  renderSummary("p1")

  await waitFor(() => expect(chipValue()).toBe("0"))
})

test("an absent or invalid body is Unavailable, never zero", async () => {
  const invalid: unknown[] = [
    { project_id: "p1" },
    { project_id: "p1", total_tokens: "900" },
    { project_id: "", total_tokens: 900 },
    { ...usageBody("p1"), by_agent: { recon: { total_tokens: 1 } } },
    { ...usageBody("p1"), total_tokens: -1 },
  ]
  for (const body of invalid) {
    stubUsage(() => json(body))
    const view = renderSummary("p1")
    await waitFor(() => expect(chipValue()).toBe("Unavailable"))
    expect(chipValue()).not.toBe("0")
    view.unmount()
  }
})

test("a failing first read is Unavailable, not zero", async () => {
  stubUsage(() => json({ detail: "boom" }, 500))
  renderSummary("p1")

  await waitFor(() => expect(chipValue()).toBe("Unavailable"))
  expect(chipValue()).not.toBe("0")
})

test("a trial with no project never fetches and is Unavailable", async () => {
  const calls = stubUsage(() => json(usageBody("p1")))
  renderSummary(null)

  expect(chipValue()).toBe("Unavailable")
  expect(calls).toEqual([])
})

test("shows a loading state before the first read settles", async () => {
  stubUsage((_url, signal) => holdOpen(signal))
  renderSummary("p1")

  expect(chipValue()).toBe("Loading…")
  expect(screen.getByText(/loading project usage/i)).toBeDefined()
})

test("the expandable breakdown gives one row per agent with every counter", async () => {
  stubUsage(() =>
    json(
      usageBody("p1", {
        total_tokens: 900,
        by_agent: {
          beta: agent({
            total_tokens: 800,
            context_tokens: { cached: 400, uncached: 100 },
            generated_tokens: { reasoning: 100, visible: 200 },
            calls: 9,
          }),
          alpha: agent({
            total_tokens: 100,
            context_tokens: { cached: 1, uncached: 2 },
            generated_tokens: { reasoning: 3, visible: 4 },
            calls: 5,
          }),
        },
      }),
    ),
  )
  renderSummary("p1")

  await waitFor(() => expect(screen.getByText("Usage by agent")).toBeDefined())
  // The disclosure starts closed; its content is present but collapsed.
  expect(screen.getByText("Usage by agent").closest("details")?.hasAttribute("open")).toBe(false)

  const rows = screen.getAllByRole("row")
  // Header row plus one row per agent, sorted by name.
  expect(rows).toHaveLength(3)
  const alpha = screen.getByRole("row", { name: /alpha/ })
  expect(within(alpha).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
    "100", // total tokens
    "1", // cached input
    "2", // uncached input
    "3", // reasoning output
    "4", // visible output
    "5", // calls
  ])
  const beta = screen.getByRole("row", { name: /beta/ })
  expect(within(beta).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
    "800",
    "400",
    "100",
    "100",
    "200",
    "9",
  ])
})

test("isolates two projects and never shows another project's counters", async () => {
  stubUsage((url, signal) => {
    if (url.includes("/projects/p1/usage")) return json(usageBody("p1", { total_tokens: 111 }))
    if (url.includes("/projects/p2/usage")) return holdOpen(signal)
    return json({ detail: "unknown" }, 404)
  })
  const view = renderSummary("p1")
  await waitFor(() => expect(chipValue()).toBe("111"))

  // Switching the project mounts a fresh reader: the previous project's total
  // is never shown under the new project, even while the new read is pending.
  view.rerender(
    <ul>
      <ProjectUsageSummary projectId="p2" />
    </ul>,
  )
  expect(chipValue()).toBe("Loading…")
  expect(screen.queryByText("111")).toBeNull()
})

test("two summaries read their own project independently", async () => {
  stubUsage((url) =>
    url.includes("/projects/p1/usage")
      ? json(usageBody("p1", { total_tokens: 11 }))
      : json(usageBody("p2", { total_tokens: 22 })),
  )
  render(
    <ul>
      <ProjectUsageSummary projectId="p1" />
      <ProjectUsageSummary projectId="p2" />
    </ul>,
  )

  await waitFor(() => expect(chipValues()).toEqual(["11", "22"]))
})

test("encodes the project id in the usage URL", async () => {
  const calls = stubUsage(() => json(usageBody("proj/2", { total_tokens: 5 })))
  renderSummary("proj/2")

  await waitFor(() => expect(chipValue()).toBe("5"))
  expect(calls.some((url) => url.includes("/projects/proj%2F2/usage"))).toBe(true)
})

test("a failed refresh shows the previous total and a warning beside it", async () => {
  vi.useFakeTimers()
  let n = 0
  stubUsage(() => {
    n += 1
    if (n === 1) return json(usageBody("p1", { total_tokens: 500 }))
    if (n === 2) return json({ detail: "boom" }, 500)
    return json(usageBody("p1", { total_tokens: 700 }))
  })
  renderSummary("p1")

  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  expect(chipValue()).toBe("500")
  expect(screen.queryByText(/not up to date/i)).toBeNull()

  // The refresh fails: the last reading survives, flagged stale.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000)
  })
  expect(chipValue()).toBe("500")
  const warning = screen.getByText(/not up to date/i)
  // The warning sits beside the total, not inside the collapsed breakdown.
  expect(warning.closest("details")).toBeNull()
  expect(screen.getByText("Usage by agent").closest("details")?.hasAttribute("open")).toBe(false)
  // It is never duplicated into the per-agent panel.
  expect(screen.getAllByText(/not up to date/i)).toHaveLength(1)

  // The next successful poll replaces the total and clears the warning.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000)
  })
  expect(chipValue()).toBe("700")
  expect(screen.queryByText(/not up to date/i)).toBeNull()
})
