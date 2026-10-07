import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, expect, test } from "vitest"
import { App } from "../App"
import type { EvalDiagnosis, EvalSnapshot, EvalTrial, EvalVerdict } from "./types"

// An authoritative Trial read from a runs root, never copied into the store.
// Its terminal is a timeout and it wrote no results at all.
function runRecordTrial(overrides: Partial<EvalTrial> = {}): EvalTrial {
  return {
    target_id: "comfyui-1",
    target_run_id: "run-a",
    trial_id: "t-timeout",
    storage_source: "run_record",
    instance_id: "inst-1",
    project_id: "proj-timeout",
    start_phase: "hunting",
    terminal: "timeout",
    copied_at: null,
    phases: [
      { phase: "recon", status: "complete", run_id: "recon-1" },
      { phase: "hunting", status: "timeout", run_id: "hunt-1" },
    ],
    eval_sha: "sha-1",
    stack_fingerprint: "fp-1",
    verdicts: [],
    diagnoses: [],
    results_availability: {
      verdicts: { status: "unavailable", reason: "verdicts_missing" },
      diagnoses: { status: "unavailable", reason: "diagnoses_missing" },
    },
    availability: "degraded",
    reason: "verdicts_missing",
    artifact_summary: { status: "project_artifacts_unavailable", hunting: 0, skills: 0 },
    project_graph_summary: {
      status: "project_graph_unavailable",
      nodes: 0,
      links: 0,
      captured_at: null,
    },
    ...overrides,
  }
}

const VERDICT: EvalVerdict = {
  vuln_id: "V1",
  identified: "identified",
  confidence: 0.9,
  matched: { unit: "u", fault_class: "fc", symptom: "s" },
  evidence: [],
}

const DIAGNOSIS: EvalDiagnosis = {
  vuln: "V9",
  failure_mode: "fm",
  root_cause: { type: "cause", combination_of: [], extended_description: null },
  diagnosis_overview: "overview",
  closest_issue: { repo: "org/repo", number: 1, title: "t", rationale: "r" },
  proposed_issue: null,
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
    summary: { targets: targets.length, trials: trials.length, identified: 0, partial: 0, missed: 0, degraded: 1 },
    targets,
    trials,
    versions: [],
    coverage: {
      targets: { tested: 0, with_identified: 0, without_identified: 0 },
      vulnerabilities: { total: 0, found: 0, not_found: 0, partial: 0 },
    },
    successes: [],
    degraded_trials: [],
    issues: [],
  }
}

const INVENTORY_UNAVAILABLE = {
  status: "unavailable",
  source: "project_storage",
  project_id: "proj-timeout",
  fallback_reason: "trial_not_found",
  reason: "project_artifacts_unavailable",
  groups: [],
}

const GRAPH_UNAVAILABLE = {
  status: "unavailable",
  source: "project_storage",
  project_id: "proj-timeout",
  captured_at: null,
  fallback_reason: "trial_not_found",
  reason: "project_graph_unavailable",
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

let snapshotBody: EvalSnapshot
function stubFetch(): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    if (url.endsWith("/snapshot")) return json(snapshotBody)
    if (url.includes("/resolved-graph")) return json(GRAPH_UNAVAILABLE)
    if (url.includes("/resolved-artifacts")) return json(INVENTORY_UNAVAILABLE)
    if (url.includes("/ground-truth")) return new Response("", { status: 404 })
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

const DEEP = "/targets/comfyui-1/trials/run-a/t-timeout"

test("the Target index shows an unmaterialized Trial honestly", async () => {
  snapshotBody = snapshot([runRecordTrial()])
  stubFetch()
  goto("/targets/comfyui-1")

  await waitFor(() => expect(document.querySelector(".trial-index-row")).not.toBeNull())
  const row = document.querySelector(".trial-index-row") as HTMLElement
  // Not a synthetic 0 identified / 0 partial / 0 missed assessment.
  expect(within(row).getByText("Results unavailable")).toBeDefined()
  expect(within(row).getByText("Not materialized")).toBeDefined()
  expect(row.textContent).not.toContain("0 identified")
})

test("a deep link opens the unmaterialized workspace with independent warnings", async () => {
  snapshotBody = snapshot([runRecordTrial()])
  stubFetch()
  goto(DEEP)

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial t-timeout" })).toBeDefined(),
  )
  // Both files are missing: two independent warnings, never a count.
  expect(
    screen.getByText(/Verdicts unavailable/, { selector: ".eval-notice-line" }),
  ).toBeDefined()
  expect(
    screen.getByText(/Diagnoses unavailable/, { selector: ".eval-notice-line" }),
  ).toBeDefined()
  // The Trial is recognized as unmaterialized, and no materialized artifact
  // link is offered for files that do not exist.
  expect(screen.getByRole("heading", { name: "Not materialized" })).toBeDefined()
  expect(screen.queryByRole("heading", { name: "Materialized artifacts" })).toBeNull()
})

test("verdicts and diagnoses availability are independent", async () => {
  // Diagnoses present, verdicts missing: only the verdicts warning is shown,
  // and the diagnosis is rendered without inventing a verdict.
  snapshotBody = snapshot([
    runRecordTrial({
      diagnoses: [DIAGNOSIS],
      results_availability: {
        verdicts: { status: "unavailable", reason: "verdicts_missing" },
        diagnoses: { status: "available", reason: null },
      },
    }),
  ])
  stubFetch()
  goto(DEEP)

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial t-timeout" })).toBeDefined(),
  )
  expect(
    screen.getByText(/Verdicts unavailable/, { selector: ".eval-notice-line" }),
  ).toBeDefined()
  expect(
    screen.queryByText(/Diagnoses unavailable/, { selector: ".eval-notice-line" }),
  ).toBeNull()
  expect(screen.getByText("overview")).toBeDefined()
})

test("a timeout is not presented as the worker being stopped", async () => {
  snapshotBody = snapshot([runRecordTrial()])
  stubFetch()
  goto(DEEP)

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Timeout during hunting" })).toBeDefined(),
  )
  // The notice states the two are distinct; nothing calls the worker stopped.
  expect(screen.getByRole("region", { name: "Timeout trial" }).textContent).toContain(
    "worker",
  )
  const text = document.body.textContent ?? ""
  expect(text).not.toMatch(/worker\s+(è\s+)?fermo/i)
  expect(text).not.toMatch(/worker\s+(is\s+)?stopped/i)
})

test("a timeout without a hunting-phase confirmation stays generic", async () => {
  snapshotBody = snapshot([
    runRecordTrial({
      phases: [
        { phase: "recon", status: "complete", run_id: "recon-1" },
        { phase: "hunting", status: "stopped", run_id: "hunt-1" },
      ],
    }),
  ])
  stubFetch()
  goto(DEEP)

  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Trial timed out" }),
    ).toBeDefined(),
  )
  expect(screen.queryByRole("heading", { name: "Timeout during hunting" })).toBeNull()
})

test("open verdict rows survive a refresh and reset on a Trial change", async () => {
  const first = runRecordTrial({
    verdicts: [VERDICT],
    results_availability: {
      verdicts: { status: "available", reason: null },
      diagnoses: { status: "available", reason: null },
    },
  })
  const second = runRecordTrial({
    target_run_id: "run-b",
    trial_id: "t-other",
    verdicts: [VERDICT],
    results_availability: {
      verdicts: { status: "available", reason: null },
      diagnoses: { status: "available", reason: null },
    },
  })
  snapshotBody = snapshot([first, second])
  stubFetch()
  goto(DEEP)

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial t-timeout" })).toBeDefined(),
  )
  const toggle = await waitFor(() =>
    screen.getByRole("button", { name: /row 1, V1/ }),
  )
  expect(toggle.getAttribute("aria-expanded")).toBe("false")
  fireEvent.click(toggle)
  await waitFor(() => expect(toggle.getAttribute("aria-expanded")).toBe("true"))

  fireEvent.click(screen.getByRole("button", { name: "Refresh" }))
  await waitFor(() => expect(toggle.getAttribute("aria-expanded")).toBe("true"))

  // Navigating to the other Trial resets the open set.
  window.history.pushState({}, "", "/targets/comfyui-1/trials/run-b/t-other")
  fireEvent.popState(window)
  await waitFor(() =>
    expect(screen.getByRole("region", { name: "Trial t-other" })).toBeDefined(),
  )
  const otherToggle = screen.getByRole("button", { name: /row 1, V1/ })
  expect(otherToggle.getAttribute("aria-expanded")).toBe("false")
})
