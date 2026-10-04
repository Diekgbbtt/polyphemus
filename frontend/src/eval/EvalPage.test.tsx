import { render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, expect, test } from "vitest"
import { App } from "../App"
import type { EvalSnapshot } from "./types"

// A minimal snapshot: enough for the dashboard shell and the shared states.
const SNAPSHOT: EvalSnapshot = {
  dataset: { id: "webexploitbench", name: "WebExploitBench" },
  summary: { targets: 1, trials: 1, identified: 1, partial: 1, missed: 1, degraded: 1 },
  targets: [
    { target_id: "comfyui-1", trial_count: 1, identified_count: 1, partial_count: 1, missed_count: 1 },
  ],
  trials: [
    {
      target_id: "comfyui-1",
      target_run_id: "run-demo-a",
      trial_id: "trial-1",
      instance_id: "inst-comfyui-1",
      project_id: "proj-comfyui-1",
      start_phase: "recon",
      terminal: "complete",
      copied_at: "2024-01-01T00:00:00+00:00",
      phases: [{ phase: "recon", status: "complete", run_id: "recon-1" }],
      eval_sha: "demo-sha-a",
      stack_fingerprint: "demo-env-x",
      verdicts: [
        {
          vuln_id: "DEMO-1",
          identified: "identified",
          confidence: 0.9,
          matched: { unit: "comfyui.manager", fault_class: "CWE-78", symptom: "rce" },
          evidence: [],
        },
      ],
      diagnoses: [],
      availability: "complete",
      reason: null,
      artifact_summary: { status: "available", hunting: 3, skills: 2 },
      project_graph_summary: {
        status: "available",
        nodes: 4,
        links: 3,
        captured_at: "2024-01-01T00:00:00+00:00",
      },
    },
  ],
  versions: [
    {
      eval_sha: "demo-sha-a",
      stack_fingerprint: "demo-env-x",
      targets: ["comfyui-1"],
      trial_count: 1,
      identified: 1,
      partial: 1,
      missed: 1,
      trials: [
        {
          target_id: "comfyui-1",
          target_run_id: "run-demo-a",
          trial_id: "trial-1",
          availability: "complete",
          identified: 1,
          partial: 1,
          missed: 1,
        },
      ],
    },
  ],
  coverage: {
    targets: { tested: 1, with_identified: 1, without_identified: 0 },
    vulnerabilities: { total: 3, found: 2, not_found: 1, partial: 1 },
  },
  successes: [
    {
      vuln_id: "DEMO-1",
      target_id: "comfyui-1",
      target_run_id: "run-demo-a",
      trial_id: "trial-1",
      eval_sha: "demo-sha-a",
      stack_fingerprint: "demo-env-x",
      confidence: 0.9,
      matched: { unit: "comfyui.manager", fault_class: "CWE-78", symptom: "rce" },
    },
  ],
  degraded_trials: [
    {
      target_id: "comfyui-1",
      target_run_id: "run-demo-a",
      trial_id: "trial-9",
      reason: "verdicts_missing",
    },
  ],
}

const EMPTY: EvalSnapshot = {
  dataset: { id: "webexploitbench", name: "WebExploitBench" },
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
}

function stubFetch(body: unknown, status = 200) {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(body), { status })) as typeof fetch
}

function goto(path: string) {
  window.history.pushState({}, "", path)
  render(<App />)
}

// The donut centre renders its value and caption as separate spans.
function expectDonutCenter(title: string, value: number, label: string) {
  const figure = screen.getByText(title).closest("figure")
  expect(figure).not.toBeNull()
  expect(
    within(figure as HTMLElement).getByText(String(value), { selector: ".eval-donut-value" }),
  ).toBeDefined()
  expect(
    within(figure as HTMLElement).getByText(label, { selector: ".eval-donut-caption" }),
  ).toBeDefined()
}

afterEach(() => {
  window.history.pushState({}, "", "/")
})

test("the /eval route renders the dataset dashboard", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "WebExploitBench" })).toBeDefined(),
  )
  expect(screen.getByText("webexploitbench")).toBeDefined()
  expect(screen.getByText("Target coverage")).toBeDefined()
  expect(screen.getByText("Vulnerability coverage")).toBeDefined()
})

test("the dashboard drops the numeric cards and the old charts", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() => expect(screen.getByText("Target coverage")).toBeDefined())
  for (const gone of [
    "Targets evaluated",
    "Targets with identified findings",
    "Targets without identified findings",
    "Verdict distribution",
    "Identification rate per Target (machine)",
    "Identification rate per version/environment",
    "exploited",
  ]) {
    expect(screen.queryByText(gone)).toBeNull()
  }
})

test("the donuts show their title, total, counts and textual percentages", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() => expect(screen.getByText("Target coverage")).toBeDefined())
  // Target donut: 1 tested, split with/without identified findings.
  expectDonutCenter("Target coverage", 1, "tested")
  expect(screen.getByText("With identified findings")).toBeDefined()
  expect(screen.getByText("Without identified findings")).toBeDefined()
  expect(screen.getByText("1 of 1 (100%)")).toBeDefined()
  expect(screen.getByText("0 of 1 (0%)")).toBeDefined()
  // Vulnerability donut: 3 evaluated, found/not-found, partial called out.
  expectDonutCenter("Vulnerability coverage", 3, "evaluated")
  expect(screen.getByRole("link", { name: "Found" })).toBeDefined()
  expect(screen.getByText("Not found")).toBeDefined()
  expect(screen.getByText("includes 1 partial")).toBeDefined()
  expect(screen.getByText("2 of 3 (67%)")).toBeDefined()
  expect(screen.getByText("1 of 3 (33%)")).toBeDefined()
})

test("a zero-total coverage renders without NaN or Infinity", async () => {
  stubFetch(EMPTY)
  goto("/eval")

  await waitFor(() => expect(screen.getByText("Target coverage")).toBeDefined())
  expectDonutCenter("Target coverage", 0, "tested")
  expectDonutCenter("Vulnerability coverage", 0, "evaluated")
  // Two segments per donut, both empty: no NaN, no Infinity, just zeros.
  expect(screen.getAllByText("0 of 0 (0%)")).toHaveLength(4)
  expect(document.body.textContent).not.toMatch(/NaN|Infinity/)
})

test("the eval section shows a loading state before the snapshot resolves", () => {
  globalThis.fetch = (() => new Promise(() => {})) as typeof fetch
  goto("/eval")

  expect(screen.getByText(/loading/i)).toBeDefined()
})

test("the eval section shows an error state when the API fails", async () => {
  stubFetch({ detail: "unavailable" }, 503)
  goto("/eval")

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
})

test("the eval section shows an empty state when there is nothing to report", async () => {
  stubFetch(EMPTY)
  goto("/eval")

  await waitFor(() => expect(screen.getByText(/no eval results/i)).toBeDefined())
})

test("the dashboard flags partial data and links the degraded trial", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Partial data" })).toBeDefined(),
  )
  expect(screen.getByRole("link", { name: /trial-9/ })).toBeDefined()
})

test("the non-eval routes are unchanged", async () => {
  stubFetch({ projects: [] })
  goto("/")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Targets" })).toBeDefined(),
  )
  expect(screen.queryByText("WebExploitBench")).toBeNull()
})
