import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, expect, test, vi } from "vitest"
import { App } from "../App"
import type { EvalSnapshot, EvalTrial } from "./types"

function trial(overrides: Partial<EvalTrial> & {
  target_id: string
  target_run_id: string
  trial_id: string
}): EvalTrial {
  return {
    instance_id: "inst-1",
    project_id: "proj-1",
    start_phase: "recon",
    terminal: "complete",
    copied_at: "2024-01-01T00:00:00+00:00",
    phases: [
      { phase: "recon", status: "complete", run_id: "recon-1" },
      { phase: "hunting", status: "stopped", run_id: "hunt-1" },
    ],
    eval_sha: "sha-1",
    stack_fingerprint: "fp-1",
    verdicts: [],
    diagnoses: [],
    availability: "complete",
    reason: null,
    artifact_summary: { status: "available", hunting: 0, skills: 0 },
    project_graph_summary: {
      status: "project_graph_unavailable",
      nodes: 0,
      links: 0,
      captured_at: null,
    },
    ...overrides,
  }
}

function snapshot(trials: EvalTrial[]): EvalSnapshot {
  const targets = [...new Set(trials.map((t) => t.target_id))].map((target_id) => ({
    target_id,
    trial_count: trials.filter((t) => t.target_id === target_id).length,
    identified_count: 0,
    partial_count: 0,
    missed_count: 0,
  }))
  return {
    dataset: { id: "webexploitbench", name: "WebExploitBench" },
    summary: { targets: targets.length, trials: trials.length, identified: 0, partial: 0, missed: 0, degraded: 0 },
    targets,
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

const GRAPH_UNAVAILABLE = {
  status: "unavailable",
  source: "project_storage",
  project_id: "proj-1",
  captured_at: null,
  fallback_reason: null,
  reason: "project_graph_empty",
}

const INVENTORY = {
  status: "available",
  source: "project_storage",
  project_id: "proj-1",
  fallback_reason: null,
  groups: [
    {
      key: "hunt-configs",
      label: "Hunt configs",
      category: "hunting",
      entries: [],
      children: [],
    },
    { key: "skills", label: "Procedure", category: "skill", entries: [], children: [] },
  ],
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function routeFetch(
  routes: Array<[string, () => Response | Promise<Response>]>,
): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    for (const [needle, handler] of routes) {
      if (url.includes(needle)) return handler()
    }
    throw new Error(`unexpected fetch: ${url}`)
  }) as typeof fetch
  return calls
}

function goto(path: string) {
  window.history.pushState({}, "", path)
  return render(<App />)
}

afterEach(() => {
  vi.useRealTimers()
  window.history.pushState({}, "", "/")
})

// The index rows in DOM order; each row links its Trial, so the link text is
// the Trial identity.
function rowOrder(): string[] {
  return [...document.querySelectorAll<HTMLElement>(".trial-index-row")].map(
    (row) => row.querySelector("a")?.textContent?.trim() ?? "",
  )
}

function rowFor(trialId: string): HTMLElement {
  const row = [...document.querySelectorAll<HTMLElement>(".trial-index-row")].find((item) =>
    item.querySelector("a")?.textContent?.includes(trialId),
  )
  if (!row) throw new Error(`no index row for ${trialId}`)
  return row
}

test("the Target page orders Trials by real start, newest first", async () => {
  routeFetch([
    [
      "/snapshot",
      () =>
        json(
          snapshot([
            trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-a", started_at: "2024-01-01T00:00:00+00:00" }),
            trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-c", started_at: "2024-01-03T00:00:00+00:00" }),
            trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-b", started_at: "2024-01-01T00:00:00+00:00" }),
          ]),
        ),
    ],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "comfyui-1" })).toBeDefined(),
  )
  await waitFor(() => expect(rowOrder()).toHaveLength(3))
  // trial-a and trial-b share a start instant, so the full identity breaks the
  // tie; trial-c is newest by its real start.
  expect(rowOrder()).toEqual(["trial-c", "trial-a", "trial-b"])
  // The TargetRun grouping (and its anchor) is preserved.
  expect(screen.getByRole("heading", { name: /run-1/ })).toBeDefined()
  expect(document.getElementById("targetrun-run-1")).not.toBeNull()
})

test("the Target page is an index: no graph or artifact section is expanded", async () => {
  const calls = routeFetch([
    [
      "/snapshot",
      () =>
        json(
          snapshot([
            trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-1" }),
          ]),
        ),
    ],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() => expect(rowOrder()).toEqual(["trial-1"]))
  // Nothing on the index expands a Trial: no embedded workspace, and therefore
  // no resolved graph or artifact request leaves the page.
  expect(screen.queryByRole("region", { name: "Trial trial-1" })).toBeNull()
  expect(screen.queryByRole("heading", { name: "Graph" })).toBeNull()
  expect(screen.queryByRole("heading", { name: "Hunting" })).toBeNull()
  expect(screen.queryByRole("heading", { name: "Skills" })).toBeNull()
  expect(screen.queryByRole("heading", { name: "Results" })).toBeNull()
  expect(calls.some((url) => url.includes("/resolved-graph"))).toBe(false)
  expect(calls.some((url) => url.includes("/resolved-artifacts"))).toBe(false)
  expect(calls.some((url) => url.includes("/ground-truth/"))).toBe(false)
  // `/snapshot` is the only request the index makes.
  expect(calls.every((url) => url.endsWith("/snapshot"))).toBe(true)
})

test("each index row links to the canonical Trial detail", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([
      trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-1" }),
    ]))],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() => expect(rowFor("trial-1")).toBeDefined())
  const link = within(rowFor("trial-1")).getByRole("link", { name: "trial-1" })
  expect(link.getAttribute("href")).toBe("/targets/comfyui-1/trials/run-1/trial-1")

  fireEvent.click(link)
  await waitFor(() =>
    expect(window.location.pathname).toBe("/targets/comfyui-1/trials/run-1/trial-1"),
  )
  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
})

test("a row shows the outcome summary and the execution timestamps", async () => {
  routeFetch([
    [
      "/snapshot",
      () =>
        json(
          snapshot([
            trial({
              target_id: "comfyui-1",
              target_run_id: "run-1",
              trial_id: "trial-1",
              copied_at: "2024-01-02T00:00:00+00:00",
              started_at: "2024-01-02T00:00:00+00:00",
              finished_at: "2024-01-02T02:30:00+00:00",
              verdicts: [
                { vuln_id: "V1", identified: "identified", confidence: 0.9, matched: { unit: null, fault_class: null, symptom: null }, evidence: [] },
                { vuln_id: "V2", identified: "missed", confidence: 0, matched: { unit: null, fault_class: null, symptom: null }, evidence: [] },
                { vuln_id: "V3", identified: "missed", confidence: 0, matched: { unit: null, fault_class: null, symptom: null }, evidence: [] },
              ],
            }),
          ]),
        ),
    ],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() => expect(rowFor("trial-1")).toBeDefined())
  const row = rowFor("trial-1")
  expect(row.textContent).toContain("1 identified / 0 partial / 2 missed")
  expect(row.textContent).toContain("Avviato il")
  expect(row.textContent).toContain("Terminato il")
  // Each instant is a semantic <time> whose machine-readable value is the
  // recorded one; the visible text is its browser-local rendering with seconds.
  const times = row.querySelectorAll("time")
  expect(times).toHaveLength(2)
  expect(times[0]?.getAttribute("dateTime")).toBe("2024-01-02T00:00:00+00:00")
  expect(times[1]?.getAttribute("dateTime")).toBe("2024-01-02T02:30:00+00:00")
  expect(times[0]?.textContent).toMatch(/\d{1,2}:\d{2}:\d{2}/)
  expect(times[0]?.textContent).not.toBe("2024-01-02T00:00:00+00:00")
})

test("a row without an execution timestamp says the date is not available", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([
      trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-1", started_at: null, finished_at: null }),
    ]))],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() => expect(rowFor("trial-1")).toBeDefined())
  expect(rowFor("trial-1").textContent).toContain("data non disponibile")
})

test("the Trial detail shows the same execution timestamps", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([
      trial({
        target_id: "comfyui-1",
        target_run_id: "run-1",
        trial_id: "trial-1",
        copied_at: "2024-01-02T00:00:00+00:00",
        started_at: "2024-01-02T00:00:00+00:00",
        finished_at: "2024-01-02T02:30:00+00:00",
      }),
    ]))],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1/trials/run-1/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  const section = screen.getByRole("region", { name: "Trial trial-1" })
  expect(within(section).getByText(/Avviato il/)).toBeDefined()
  expect(within(section).getByText(/Terminato il/)).toBeDefined()
  const started = section.querySelector("time")
  expect(started?.getAttribute("dateTime")).toBe("2024-01-02T00:00:00+00:00")
  expect(started?.textContent).not.toBe("2024-01-02T00:00:00+00:00")
})

test("the Trial detail without an execution timestamp says the date is not available", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([
      trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-1", started_at: null, finished_at: null }),
    ]))],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1/trials/run-1/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  const section = screen.getByRole("region", { name: "Trial trial-1" })
  expect(within(section).getAllByText("data non disponibile").length).toBeGreaterThan(0)
})

const GROUND_TRUTH = {
  target_id: "comfyui-1",
  provenance: "current_benchmark_checkout",
  vulnerabilities: [
    {
      vuln_id: "V1",
      location: "http://comfyui-manager:8288/view",
      type: "Arbitrary File Read",
      scoring: ["LLM_judge"],
    },
  ],
}

function verdictTrial() {
  return trial({
    target_id: "comfyui-1",
    target_run_id: "run-1",
    trial_id: "trial-1",
    verdicts: [
      {
        vuln_id: "V1",
        identified: "identified",
        confidence: 0.9,
        matched: { unit: null, fault_class: null, symptom: null },
        evidence: [],
      },
      {
        vuln_id: "V2",
        identified: "missed",
        confidence: 0,
        matched: { unit: null, fault_class: null, symptom: null },
        evidence: [],
      },
    ],
  })
}

test("the Trial detail pairs each verdict with the current-benchmark reference", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([verdictTrial()]))],
    ["/ground-truth/targets/", () => json(GROUND_TRUTH)],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1/trials/run-1/trial-1")

  await waitFor(() =>
    expect(screen.getByText("http://comfyui-manager:8288/view")).toBeDefined(),
  )
  // The trial with the missing entry says so instead of borrowing V1's reference.
  expect(screen.getAllByText("Ground truth non disponibile").length).toBeGreaterThan(0)
})

test("a rejected ground-truth request leaves the results readable", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([verdictTrial()]))],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1/trials/run-1/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  await waitFor(() =>
    expect(screen.getAllByText("Ground truth non disponibile").length).toBeGreaterThan(0),
  )
  // Verdicts stay visible; a missing reference never hides them.
  expect(screen.getAllByText("V1").length).toBeGreaterThan(0)
  expect(screen.getAllByText("identified").length).toBeGreaterThan(0)
})

test("the materialized verdicts artifact view makes no operator request", async () => {
  const calls = routeFetch([["/snapshot", () => json(snapshot([verdictTrial()]))]])
  goto("/eval/trials/comfyui-1/run-1/trial-1/verdicts")

  await waitFor(() => expect(screen.getAllByText("V1").length).toBeGreaterThan(0))
  expect(calls.some((url) => url.includes("/ground-truth/"))).toBe(false)
  expect(screen.queryByText("Ground truth (current benchmark)")).toBeNull()
})

test("legacy eval and project Trial URLs preserve the Trial identity", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([
      trial({
        target_id: "comfyui-1",
        target_run_id: "run-1",
        trial_id: "trial-1",
        copied_at: "2024-01-02T00:00:00+00:00",
      }),
    ]))],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/eval/trials/comfyui-1/run-1/trial-1")

  await waitFor(() =>
    expect(window.location.pathname).toBe("/targets/comfyui-1/trials/run-1/trial-1"),
  )
  expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined()

  window.history.pushState({}, "", "/p/proj-1/evals/comfyui-1/run-1/trial-1")
  render(<App />)
  await waitFor(() =>
    expect(screen.getAllByRole("region", { name: "Trial trial-1" }).length).toBeGreaterThan(0),
  )
  expect(window.location.pathname).toBe("/p/proj-1/evals/comfyui-1/run-1/trial-1")
})

const POLL = 15_000

test("an unmaterialized Trial still shows its real execution dates", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([
      trial({
        target_id: "comfyui-1",
        target_run_id: "run-1",
        trial_id: "t-timeout",
        storage_source: "run_record",
        copied_at: null,
        started_at: "2026-10-06T08:12:15+00:00",
        finished_at: "2026-10-06T10:41:29+00:00",
      }),
    ]))],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() => expect(rowFor("t-timeout")).toBeDefined())
  const row = rowFor("t-timeout")
  const times = row.querySelectorAll("time")
  expect(times[0]?.getAttribute("dateTime")).toBe("2026-10-06T08:12:15+00:00")
  expect(times[1]?.getAttribute("dateTime")).toBe("2026-10-06T10:41:29+00:00")
  // The provenance marker stays separate from the dates.
  expect(row.textContent).toContain("Non materializzato")
})

test("a refresh updates the execution dates without duplicating the Trial", async () => {
  vi.useFakeTimers()
  const record = (started: string, finished: string) =>
    trial({
      target_id: "comfyui-1",
      target_run_id: "run-1",
      trial_id: "trial-1",
      started_at: started,
      finished_at: finished,
    })
  let body = snapshot([record("2024-01-02T00:00:00+00:00", "2024-01-02T01:00:00+00:00")])
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    if (url.endsWith("/snapshot")) return json(body)
    throw new Error(`unexpected fetch: ${url}`)
  }) as typeof fetch
  goto("/targets/comfyui-1")

  await act(async () => {})
  expect(rowOrder()).toEqual(["trial-1"])
  expect(rowFor("trial-1").querySelector("time")?.getAttribute("dateTime")).toBe(
    "2024-01-02T00:00:00+00:00",
  )

  body = snapshot([record("2024-01-03T00:00:00+00:00", "2024-01-03T01:00:00+00:00")])
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(rowOrder()).toEqual(["trial-1"])
  expect(rowFor("trial-1").querySelector("time")?.getAttribute("dateTime")).toBe(
    "2024-01-03T00:00:00+00:00",
  )
})
