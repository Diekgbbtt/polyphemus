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

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

// The blanket stub above answers every URL with the same body; the workspace
// needs the eval snapshot and the live graph told apart.
function stubRoutes(routes: Array<[string, () => Response]>): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: RequestInfo | URL) => {
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

test("a schema-v1 trial shows no graph or artifact counters", async () => {
  stubFetch(
    snapshot([
      trial({
        target_id: "t",
        target_run_id: "r",
        trial_id: "trial-1",
        artifact_summary: { status: "project_artifacts_unavailable", hunting: 0, skills: 0 },
        project_graph_summary: {
          status: "project_graph_unavailable",
          nodes: 0,
          links: 0,
          captured_at: null,
        },
      }),
    ]),
  )
  goto("/p/proj-a/evals")

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "trial-1" })).toBeDefined(),
  )
  const item = screen.getByRole("link", { name: "trial-1" }).closest("li") as HTMLElement
  // The core identity and outcome stay; the unavailable counters do not.
  expect(item.textContent).toMatch(/complete/)
  expect(item.textContent).toMatch(/0 identified \/ 0 partial \/ 0 missed/)
  expect(item.textContent).not.toMatch(/nodes \/ /)
  expect(item.textContent).not.toMatch(/Hunting/)
  expect(item.textContent).not.toMatch(/Skills/)
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

test("the workspace accepts the stopped-at-cap schema-v2 contract", async () => {
  stubFetch(
    snapshot([
      trial({
        target_id: "comfyui-1",
        target_run_id: "run-demo-real-shape",
        trial_id: "trial-stopped-cap-10",
        start_phase: "recon",
        terminal: "stopped",
        phases: [
          { phase: "recon", status: "complete", run_id: "demo-real-recon" },
          { phase: "hunting", status: "stopped", run_id: "demo-real-hunt" },
        ],
        verdicts: [
          {
            vuln_id: "DEMO-CVE-2024-5001",
            identified: "missed",
            confidence: 0,
            matched: { unit: null, fault_class: null, symptom: null },
            evidence: [],
          },
          {
            vuln_id: "DEMO-CVE-2024-5002",
            identified: "missed",
            confidence: 0,
            matched: { unit: null, fault_class: null, symptom: null },
            evidence: [],
          },
          {
            vuln_id: "DEMO-CVE-2024-5003",
            identified: "missed",
            confidence: 0,
            matched: { unit: null, fault_class: null, symptom: null },
            evidence: [],
          },
        ],
        artifact_summary: { status: "available", hunting: 21, skills: 0 },
        project_graph_summary: {
          status: "available",
          nodes: 3,
          links: 2,
          captured_at: "2024-01-01T00:00:00+00:00",
        },
      }),
    ]),
  )
  goto("/p/proj-a/evals/comfyui-1/run-demo-real-shape/trial-stopped-cap-10")

  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: /Trial trial-stopped-cap-10/ }),
    ).toBeDefined(),
  )
  expect(screen.getByText("stopped")).toBeDefined()
  expect(screen.getByText("0 identified / 0 partial / 3 missed")).toBeDefined()
  expect(screen.getByText("21 artifacts")).toBeDefined()
  expect(screen.getByText("0 artifacts")).toBeDefined()
  expect(screen.getByText(/available · 3 nodes \/ 2 links/)).toBeDefined()
})

test("the workspace hides unavailable graph and artifact sections", async () => {
  const calls = stubRoutes([
    [
      "/snapshot",
      () =>
        json(
          snapshot([
            trial({
              target_id: "t",
              target_run_id: "r",
              trial_id: "trial-1",
              artifact_summary: {
                status: "project_artifacts_unavailable",
                hunting: 0,
                skills: 0,
              },
              project_graph_summary: {
                status: "project_graph_unavailable",
                nodes: 0,
                links: 0,
                captured_at: null,
              },
            }),
          ]),
        ),
    ],
    [
      "/projects/proj-a/graph",
      () => json({ project_id: "proj-a", nodes: [], links: [] }),
    ],
  ])
  goto("/p/proj-a/evals/t/r/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /Trial trial-1/ })).toBeDefined(),
  )
  // All valid core content is still shown...
  expect(screen.getAllByText("complete").length).toBeGreaterThan(0)
  expect(screen.getByText("0 identified / 0 partial / 0 missed")).toBeDefined()
  // ... while the unavailable counters and sections are gone.
  expect(screen.queryByText(/nodes \/ /)).toBeNull()
  expect(screen.queryByRole("heading", { name: "Hunting" })).toBeNull()
  expect(screen.queryByRole("heading", { name: "Skills" })).toBeNull()
  // The historical graph is unavailable, so the current live one is offered.
  await waitFor(() =>
    expect(screen.getByText("No graph available")).toBeDefined(),
  )
  expect(calls.some((url) => url.includes("/projects/proj-a/graph"))).toBe(true)
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
