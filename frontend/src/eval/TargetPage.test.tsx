import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, expect, test } from "vitest"
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

test("the Target page orders Trials newest first with an identity tie-break", async () => {
  routeFetch([
    [
      "/snapshot",
      () =>
        json(
          snapshot([
            trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-a", copied_at: "2024-01-01T00:00:00+00:00" }),
            trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-c", copied_at: "2024-01-03T00:00:00+00:00" }),
            trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-b", copied_at: "2024-01-01T00:00:00+00:00" }),
          ]),
        ),
    ],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "comfyui-1" })).toBeDefined(),
  )
  await waitFor(() => expect(rowOrder()).toHaveLength(3))
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

test("a row shows the outcome summary and the saved timestamp", async () => {
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
  expect(row.textContent).toContain("Salvato il")
  // The timestamp is a semantic <time> whose machine-readable value is the
  // stored instant; the visible text is its browser-local rendering.
  const saved = row.querySelector("time")
  expect(saved?.getAttribute("dateTime")).toBe("2024-01-02T00:00:00+00:00")
  expect(saved?.textContent).not.toBe("")
  expect(saved?.textContent).not.toBe("2024-01-02T00:00:00+00:00")
})

test("a row without a timestamp says the date is not available", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([
      trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-1", copied_at: null }),
    ]))],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() => expect(rowFor("trial-1")).toBeDefined())
  expect(rowFor("trial-1").textContent).toContain("Data non disponibile")
})

test("the Trial detail shows the same saved timestamp", async () => {
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
  goto("/targets/comfyui-1/trials/run-1/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  const section = screen.getByRole("region", { name: "Trial trial-1" })
  expect(within(section).getByText(/Salvato il/)).toBeDefined()
  const saved = section.querySelector("time")
  expect(saved?.getAttribute("dateTime")).toBe("2024-01-02T00:00:00+00:00")
  expect(saved?.textContent).not.toBe("2024-01-02T00:00:00+00:00")
})

test("the Trial detail without a timestamp says the date is not available", async () => {
  routeFetch([
    ["/snapshot", () => json(snapshot([
      trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-1", copied_at: null }),
    ]))],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1/trials/run-1/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  const section = screen.getByRole("region", { name: "Trial trial-1" })
  expect(within(section).getByText("Data non disponibile")).toBeDefined()
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
