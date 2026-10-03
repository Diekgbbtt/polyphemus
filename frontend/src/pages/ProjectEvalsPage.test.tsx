import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, expect, test } from "vitest"
import { App } from "../App"
import { projectPaths } from "../projectPaths"
import type { EvalSnapshot, EvalTrial } from "../eval/types"

// --- fixtures ------------------------------------------------------------------

function trial(
  overrides: Partial<EvalTrial> & {
    target_id: string
    target_run_id: string
    trial_id: string
  },
): EvalTrial {
  return {
    instance_id: "inst-1",
    project_id: "proj-a",
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
    project_graph_summary: {
      status: "available",
      nodes: 0,
      links: 0,
      captured_at: null,
    },
    ...overrides,
  }
}

function snapshot(trials: EvalTrial[]): EvalSnapshot {
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

function stubFetch(body: unknown, status = 200): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input))
    return new Response(JSON.stringify(body), { status })
  }) as typeof fetch
  return calls
}

function stubPendingFetch(): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input))
    return new Promise<Response>(() => {})
  }) as typeof fetch
  return calls
}

function goto(path: string) {
  window.history.pushState({}, "", path)
  return render(<App />)
}

function trialHrefs(): string[] {
  return screen
    .getAllByRole("link")
    .map((link) => link.getAttribute("href") ?? "")
    .filter((href) => href.includes("/evals/"))
}

afterEach(() => {
  window.history.pushState({}, "", "/")
})

// --- projectPaths ---------------------------------------------------------------

test("projectPaths encodes every identifier separately", () => {
  expect(projectPaths.live("a b/c")).toBe("/p/a%20b%2Fc")
  expect(projectPaths.runs("a b/c")).toBe("/p/a%20b%2Fc/runs")
  expect(projectPaths.evals("a b/c")).toBe("/p/a%20b%2Fc/evals")
  expect(projectPaths.trial("p/#", "t 1", "r/2", "x?y")).toBe(
    "/p/p%2F%23/evals/t%201/r%2F2/x%3Fy",
  )
  expect(projectPaths.artifacts("p", "t", "r", "x")).toBe(
    "/p/p/evals/t/r/x/artifacts",
  )
  expect(projectPaths.artifact("p", "t", "r", "x", "a/b")).toBe(
    "/p/p/evals/t/r/x/artifacts/a%2Fb",
  )
})

// --- the project eval list -------------------------------------------------------

test("the list is isolated to the exact project id", async () => {
  stubFetch(
    snapshot([
      trial({ target_id: "comfyui-1", target_run_id: "run-a", trial_id: "trial-1" }),
      trial({ target_id: "comfyui-1", target_run_id: "run-a", trial_id: "trial-2" }),
      trial({
        target_id: "other-1",
        target_run_id: "run-z",
        trial_id: "other-trial",
        project_id: "proj-b",
      }),
    ]),
  )
  goto("/p/proj-a/evals")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Eval Trials" })).toBeDefined(),
  )
  expect(screen.getByRole("link", { name: "trial-1" })).toBeDefined()
  expect(screen.getByRole("link", { name: "trial-2" })).toBeDefined()
  expect(screen.queryByText("other-trial")).toBeNull()
})

test("a degraded materialized trial stays visible", async () => {
  stubFetch(
    snapshot([
      trial({
        target_id: "white-jotter-1",
        target_run_id: "run-b",
        trial_id: "trial-2",
        availability: "degraded",
        reason: "verdicts_missing",
      }),
    ]),
  )
  goto("/p/proj-a/evals")

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "trial-2" })).toBeDefined(),
  )
  const item = screen.getByRole("link", { name: "trial-2" }).closest("li") as HTMLElement
  expect(item.textContent).toMatch(/degraded/i)
  expect(item.textContent).toMatch(/verdicts_missing/)
})

test("orders by captured_at, then copied_at, then the full tuple", async () => {
  stubFetch(
    snapshot([
      trial({
        target_id: "t",
        target_run_id: "r",
        trial_id: "captured-old",
        project_graph_summary: {
          status: "available",
          nodes: 1,
          links: 0,
          captured_at: "2024-01-02T00:00:00+00:00",
        },
      }),
      trial({
        target_id: "t",
        target_run_id: "r",
        trial_id: "fallback-newest",
        copied_at: "2024-01-04T00:00:00+00:00",
        project_graph_summary: {
          status: "available",
          nodes: 1,
          links: 0,
          captured_at: null,
        },
      }),
      trial({
        target_id: "t",
        target_run_id: "r",
        trial_id: "captured-new",
        project_graph_summary: {
          status: "available",
          nodes: 1,
          links: 0,
          captured_at: "2024-01-03T00:00:00+00:00",
        },
      }),
    ]),
  )
  goto("/p/proj-a/evals")

  await waitFor(() => expect(trialHrefs()).toHaveLength(3))
  expect(trialHrefs()).toEqual([
    projectPaths.trial("proj-a", "t", "r", "fallback-newest"),
    projectPaths.trial("proj-a", "t", "r", "captured-new"),
    projectPaths.trial("proj-a", "t", "r", "captured-old"),
  ])
})

test("duplicate trial ids under different runs produce distinct links", async () => {
  stubFetch(
    snapshot([
      trial({ target_id: "t", target_run_id: "run-a", trial_id: "trial-1" }),
      trial({ target_id: "t", target_run_id: "run-b", trial_id: "trial-1" }),
    ]),
  )
  goto("/p/proj-a/evals")

  await waitFor(() =>
    expect(screen.getAllByRole("link", { name: "trial-1" })).toHaveLength(2),
  )
  const hrefs = screen
    .getAllByRole("link", { name: "trial-1" })
    .map((link) => link.getAttribute("href"))
  expect(new Set(hrefs).size).toBe(2)
})

test("the list shows an explicit empty state", async () => {
  stubFetch(snapshot([]))
  goto("/p/proj-a/evals")

  await waitFor(() =>
    expect(screen.getByText(/No eval Trials for this project/i)).toBeDefined(),
  )
})

test("the subtree shows the loading state", async () => {
  stubPendingFetch()
  goto("/p/proj-a/evals")

  expect(screen.getByRole("status").textContent).toMatch(/Loading eval results/i)
})

test("the subtree shows the shared error state", async () => {
  stubFetch({ detail: "boom" }, 500)
  goto("/p/proj-a/evals")

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/Failed to load eval results/i)
})

// --- the provider is shared across the subtree -----------------------------------

test("list to detail navigation keeps one /snapshot request", async () => {
  const calls = stubFetch(
    snapshot([trial({ target_id: "t", target_run_id: "r", trial_id: "trial-1" })]),
  )
  goto("/p/proj-a/evals")

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "trial-1" })).toBeDefined(),
  )
  fireEvent.click(screen.getByRole("link", { name: "trial-1" }))

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /Trial trial-1/ })).toBeDefined(),
  )
  expect(calls.filter((url) => url.endsWith("/snapshot"))).toHaveLength(1)
  // The workspace loads its historical (eval) graph, never the live one.
  expect(calls.some((url) => url.includes("/projects/"))).toBe(false)
  expect(calls.some((url) => url.includes("artifacts"))).toBe(false)
})

test("a direct refresh of the detail URL resolves the trial", async () => {
  stubFetch(snapshot([trial({ target_id: "t", target_run_id: "r", trial_id: "trial-1" })]))

  goto("/p/proj-a/evals/t/r/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /Trial trial-1/ })).toBeDefined(),
  )
})

test("an unknown trial shows a generic not-found state", async () => {
  stubFetch(snapshot([trial({ target_id: "t", target_run_id: "r", trial_id: "trial-1" })]))

  goto("/p/proj-a/evals/t/r/missing")

  await waitFor(() => expect(screen.getByText(/Trial not found/i)).toBeDefined())
})

test("a trial from another project is not leaked", async () => {
  stubFetch(
    snapshot([
      trial({
        target_id: "t",
        target_run_id: "r",
        trial_id: "trial-1",
        project_id: "proj-b",
      }),
    ]),
  )

  goto("/p/proj-a/evals/t/r/trial-1")

  await waitFor(() => expect(screen.getByText(/Trial not found/i)).toBeDefined())
  expect(screen.queryByText("proj-b")).toBeNull()
})

// --- cross links -----------------------------------------------------------------

test("the project trial links to the existing eval Trial route", async () => {
  stubFetch(
    snapshot([
      trial({
        target_id: "t",
        target_run_id: "r",
        trial_id: "trial-1",
        artifact_summary: { status: "available", hunting: 15, skills: 4 },
        project_graph_summary: {
          status: "available",
          nodes: 4,
          links: 3,
          captured_at: "2024-01-03T00:00:00+00:00",
        },
      }),
    ]),
  )
  goto("/p/proj-a/evals/t/r/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "Open eval Trial" })).toBeDefined(),
  )
  expect(
    screen.getByRole("link", { name: "Open eval Trial" }).getAttribute("href"),
  ).toBe("/eval/trials/t/r/trial-1")
  // Placeholder sections exist; no artifact links yet.
  expect(screen.getByRole("heading", { name: "Graph" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Skills" })).toBeDefined()
})

// --- the project shell -----------------------------------------------------------

test("GraphPage and RunsPage expose the shared project navigation", async () => {
  stubFetch({ nodes: [], links: [] })
  goto("/p/p%20x")

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "Graph" })).toBeDefined(),
  )
  expect(screen.getByRole("link", { name: "Runs" }).getAttribute("href")).toBe(
    "/p/p%20x/runs",
  )
  expect(screen.getByRole("link", { name: "Eval Trials" }).getAttribute("href")).toBe(
    "/p/p%20x/evals",
  )
})

test("RunsPage exposes encoded project navigation", async () => {
  stubFetch({ liveness_ttl_seconds: 30, runs: [] })
  goto("/p/p%20x/runs")

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "Graph" })).toBeDefined(),
  )
  expect(screen.getByRole("link", { name: "Graph" }).getAttribute("href")).toBe(
    "/p/p%20x",
  )
  expect(screen.getByRole("link", { name: "Eval Trials" }).getAttribute("href")).toBe(
    "/p/p%20x/evals",
  )
})
