import { render, screen, waitFor, within } from "@testing-library/react"
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

function sectionOrder(): string[] {
  return [...document.querySelectorAll<HTMLElement>(".trial-section")].map(
    (section) => section.getAttribute("aria-label") ?? "",
  )
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
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "comfyui-1" })).toBeDefined(),
  )
  await waitFor(() => expect(sectionOrder()).toHaveLength(3))
  expect(sectionOrder()).toEqual([
    "Trial trial-c",
    "Trial trial-a",
    "Trial trial-b",
  ])
})

test("every Trial section shows identity, terminal, phases, project, and sections", async () => {
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
              terminal: "stopped",
              availability: "degraded",
              reason: "verdicts_missing",
              verdicts: [
                {
                  vuln_id: "DEMO-1",
                  identified: "missed",
                  confidence: 0,
                  matched: { unit: null, fault_class: null, symptom: null },
                  evidence: [],
                },
              ],
            }),
          ]),
        ),
    ],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  const section = screen.getByRole("region", { name: "Trial trial-1" })
  expect(within(section).getByRole("heading", { name: /^Trial trial-1$/ })).toBeDefined()
  expect(within(section).getByText("proj-1")).toBeDefined()
  expect(within(section).getByText("stopped", { selector: ".eval-chip-value" })).toBeDefined()
  expect(within(section).getByText(/recon complete → hunting stopped/)).toBeDefined()
  expect(within(section).getByRole("heading", { name: "Degraded trial" })).toBeDefined()
  expect(within(section).getByRole("heading", { name: "Results" })).toBeDefined()
  expect(within(section).getByRole("heading", { name: "Graph" })).toBeDefined()
  await waitFor(() =>
    expect(within(section).getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expect(within(section).getByRole("heading", { name: "Skills" })).toBeDefined()
})

test("a graph error never removes the results or artifacts", async () => {
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
              verdicts: [
                {
                  vuln_id: "DEMO-1",
                  identified: "identified",
                  confidence: 0.9,
                  matched: { unit: "u", fault_class: "c", symptom: "s" },
                  evidence: [],
                },
              ],
            }),
          ]),
        ),
    ],
    ["/resolved-graph", () => json({ detail: "project_graph_unavailable" }, 409)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  const section = screen.getByRole("region", { name: "Trial trial-1" })
  await waitFor(() => expect(within(section).getByRole("alert")).toBeDefined())
  expect(within(section).getByText("DEMO-1")).toBeDefined()
  expect(within(section).getByRole("heading", { name: "Hunting" })).toBeDefined()
})

test("an artifact error never removes the results or graph", async () => {
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
              verdicts: [
                {
                  vuln_id: "DEMO-1",
                  identified: "identified",
                  confidence: 0.9,
                  matched: { unit: "u", fault_class: "c", symptom: "s" },
                  evidence: [],
                },
              ],
            }),
          ]),
        ),
    ],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json({ detail: "artifact_unsafe" }, 409)],
  ])
  goto("/targets/comfyui-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  const section = screen.getByRole("region", { name: "Trial trial-1" })
  await waitFor(() => expect(within(section).getByRole("alert")).toBeDefined())
  expect(within(section).getByText("DEMO-1")).toBeDefined()
  expect(within(section).getByText("No graph available")).toBeDefined()
})

test("the canonical deep Trial URL renders the same section", async () => {
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
              verdicts: [
                {
                  vuln_id: "DEMO-1",
                  identified: "identified",
                  confidence: 0.9,
                  matched: { unit: "u", fault_class: "c", symptom: "s" },
                  evidence: [],
                },
              ],
            }),
          ]),
        ),
    ],
    ["/resolved-graph", () => json(GRAPH_UNAVAILABLE)],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/targets/comfyui-1/trials/run-1/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial trial-1" })).toBeDefined(),
  )
  const section = screen.getByRole("region", { name: "Trial trial-1" })
  expect(within(section).getByRole("heading", { name: "Results" })).toBeDefined()
  expect(within(section).getByText("DEMO-1")).toBeDefined()
})

test("legacy eval and project Trial URLs preserve the Trial identity", async () => {
  routeFetch([
    [
      "/snapshot",
      () =>
        json(
          snapshot([
            trial({ target_id: "comfyui-1", target_run_id: "run-1", trial_id: "trial-1" }),
          ]),
        ),
    ],
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
