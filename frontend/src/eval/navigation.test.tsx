import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, expect, test } from "vitest"
import { App } from "../App"
import type { EvalSnapshot } from "./types"

// A compact corpus that mirrors the demo generator: a shared eval_sha under two
// fingerprints, two TargetRuns on one Target, one complete partial/missed pair
// (each diagnosed), and one degraded trial with no verdicts at all.
const SNAPSHOT: EvalSnapshot = {
  dataset: { id: "webexploitbench", name: "WebExploitBench" },
  summary: { targets: 2, trials: 3, identified: 2, partial: 1, missed: 1, degraded: 1 },
  targets: [
    { target_id: "comfyui-1", trial_count: 2, identified_count: 2, partial_count: 1, missed_count: 1 },
    { target_id: "white-jotter-1", trial_count: 1, identified_count: 0, partial_count: 0, missed_count: 0 },
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
      phases: [
        { phase: "recon", status: "complete", run_id: "recon-1" },
        { phase: "hunting", status: "complete", run_id: "hunt-1" },
      ],
      eval_sha: "demo-sha-a",
      stack_fingerprint: "demo-env-x",
      verdicts: [
        {
          vuln_id: "DEMO-1",
          identified: "identified",
          confidence: 0.9,
          matched: { unit: "comfyui.manager", fault_class: "CWE-78", symptom: "rce" },
          // The last two are the kind of ref the server never emits: the UI must
          // still refuse to show them.
          evidence: [
            "demo/comfyui-1/trial-1/hunt-config.yaml",
            "demo/comfyui-1/trial-1/export.yaml",
            "/etc/passwd",
            "https://evil.invalid/export.yaml",
          ],
        },
        {
          vuln_id: "DEMO-2",
          identified: "partial",
          confidence: 0.4,
          matched: { unit: "comfyui.nodes", fault_class: "CWE-94", symptom: "likely_rce" },
          evidence: ["demo/comfyui-1/trial-1/spec"],
        },
        // A second materialized row for the same vuln, with its own confidence,
        // match and evidence: the verdicts view must show both rows distinctly.
        {
          vuln_id: "DEMO-2",
          identified: "partial",
          confidence: 0.35,
          matched: { unit: "comfyui.nodes.extra", fault_class: "CWE-94", symptom: "alt_rce" },
          evidence: ["demo/comfyui-1/trial-1/spec-extra"],
        },
      ],
      diagnoses: [
        {
          vuln: "DEMO-2",
          failure_mode: "spec_underspecified",
          root_cause: {
            type: "kb_coverage_gap",
            combination_of: ["skill_defect"],
            extended_description: "the fault KB had no entry for a vendored node pack",
          },
          diagnosis_overview: "the spec never pinned the loader version",
          closest_issue: { repo: "org/demo", number: 7, title: "[demo] issue", rationale: "synthetic" },
          proposed_issue: null,
        },
      ],
      availability: "complete",
      reason: null,
      artifact_summary: { status: "available", hunting: 5, skills: 4 },
      project_graph_summary: {
        status: "available",
        nodes: 3,
        links: 2,
        captured_at: "2024-01-01T00:00:00+00:00",
      },
    },
    {
      target_id: "comfyui-1",
      target_run_id: "run-demo-b",
      trial_id: "trial-1",
      instance_id: "inst-comfyui-1",
      project_id: "proj-comfyui-1",
      start_phase: "recon",
      terminal: "complete",
      copied_at: "2024-01-02T00:00:00+00:00",
      phases: [{ phase: "hunting", status: "complete", run_id: "hunt-2" }],
      eval_sha: "demo-sha-b",
      stack_fingerprint: "demo-env-y",
      verdicts: [
        {
          vuln_id: "DEMO-3",
          identified: "identified",
          confidence: 0.8,
          matched: { unit: "comfyui.queue", fault_class: "CWE-22", symptom: "traversal" },
          evidence: ["demo/comfyui-1/trial-1-b/export.yaml"],
        },
        {
          vuln_id: "DEMO-4",
          identified: "missed",
          confidence: 0,
          matched: { unit: null, fault_class: null, symptom: null },
          evidence: [],
        },
      ],
      diagnoses: [
        {
          vuln: "DEMO-4",
          failure_mode: "surface_gap",
          root_cause: {
            type: "missing_component",
            combination_of: [],
            extended_description: null,
          },
          diagnosis_overview: "the surface was never enumerated",
          closest_issue: null,
          proposed_issue: { title: "Enumerate it", labels: ["recon"] },
        },
      ],
      availability: "complete",
      reason: null,
      artifact_summary: { status: "available", hunting: 2, skills: 1 },
      project_graph_summary: {
        status: "available",
        nodes: 2,
        links: 1,
        captured_at: "2024-01-02T00:00:00+00:00",
      },
    },
    {
      target_id: "white-jotter-1",
      target_run_id: "run-demo-a",
      trial_id: "trial-1",
      instance_id: null,
      project_id: null,
      start_phase: null,
      terminal: null,
      copied_at: null,
      phases: [],
      eval_sha: "demo-sha-a",
      stack_fingerprint: "demo-env-z",
      verdicts: [],
      diagnoses: [],
      availability: "degraded",
      reason: "verdicts_missing",
      artifact_summary: { status: "project_artifacts_unavailable", hunting: 0, skills: 0 },
      project_graph_summary: {
        status: "project_graph_unavailable",
        nodes: 0,
        links: 0,
        captured_at: null,
      },
    },
    {
      target_id: "comfyui-1",
      target_run_id: "run-demo-c",
      trial_id: "trial-1",
      instance_id: "inst-comfyui-1",
      project_id: "proj-comfyui-1",
      start_phase: "recon",
      terminal: "complete",
      copied_at: "2024-01-03T00:00:00+00:00",
      phases: [{ phase: "recon", status: "complete", run_id: "recon-9" }],
      eval_sha: "demo-sha-c",
      stack_fingerprint: "demo-env-x",
      verdicts: [
        {
          vuln_id: "DEMO-9",
          identified: "identified",
          confidence: 0.95,
          matched: { unit: "comfyui.api", fault_class: "CWE-78", symptom: "rce" },
          evidence: ["demo/comfyui-1/run-demo-c/DEMO-9/export.yaml"],
        },
      ],
      diagnoses: [],
      availability: "complete",
      reason: null,
      artifact_summary: { status: "available", hunting: 1, skills: 0 },
      project_graph_summary: {
        status: "available",
        nodes: 1,
        links: 0,
        captured_at: "2024-01-03T00:00:00+00:00",
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
      missed: 0,
      trials: [
        {
          target_id: "comfyui-1",
          target_run_id: "run-demo-a",
          trial_id: "trial-1",
          availability: "complete",
          identified: 1,
          partial: 1,
          missed: 0,
        },
      ],
    },
    {
      eval_sha: "demo-sha-a",
      stack_fingerprint: "demo-env-z",
      targets: ["white-jotter-1"],
      trial_count: 1,
      identified: 0,
      partial: 0,
      missed: 0,
      trials: [
        {
          target_id: "white-jotter-1",
          target_run_id: "run-demo-a",
          trial_id: "trial-1",
          availability: "degraded",
          identified: 0,
          partial: 0,
          missed: 0,
        },
      ],
    },
    {
      eval_sha: "demo-sha-b",
      stack_fingerprint: "demo-env-y",
      targets: ["comfyui-1"],
      trial_count: 1,
      identified: 1,
      partial: 0,
      missed: 1,
      trials: [
        {
          target_id: "comfyui-1",
          target_run_id: "run-demo-b",
          trial_id: "trial-1",
          availability: "complete",
          identified: 1,
          partial: 0,
          missed: 1,
        },
      ],
    },
  ],
  coverage: {
    targets: { tested: 2, with_identified: 1, without_identified: 1 },
    vulnerabilities: { total: 4, found: 2, not_found: 2, partial: 1 },
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
    {
      vuln_id: "DEMO-3",
      target_id: "comfyui-1",
      target_run_id: "run-demo-b",
      trial_id: "trial-1",
      eval_sha: "demo-sha-b",
      stack_fingerprint: "demo-env-y",
      confidence: 0.8,
      matched: { unit: "comfyui.queue", fault_class: "CWE-22", symptom: "traversal" },
    },
  ],
  degraded_trials: [
    {
      target_id: "white-jotter-1",
      target_run_id: "run-demo-a",
      trial_id: "trial-1",
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

// --- dashboard -----------------------------------------------------------------

test("the dashboard shows the two coverage donuts", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "WebExploitBench" })).toBeDefined(),
  )
  // First donut: Target coverage, centred on the tested count.
  expect(screen.getByText("Target coverage")).toBeDefined()
  expectDonutCenter("Target coverage", 2, "tested")
  expect(screen.getByText("With identified findings")).toBeDefined()
  expect(screen.getByText("Without identified findings")).toBeDefined()
  // Second donut: vulnerability coverage, centred on the evaluated count.
  expect(screen.getByText("Vulnerability coverage")).toBeDefined()
  expectDonutCenter("Vulnerability coverage", 4, "evaluated")
  expect(screen.getByRole("link", { name: "Found" })).toBeDefined()
  expect(screen.getByText("Not found")).toBeDefined()
  // The legend carries the label, count, percentage and total as text.
  expect(screen.getAllByText("1 of 2 (50%)")).toHaveLength(2)
  expect(screen.getAllByText("2 of 4 (50%)")).toHaveLength(2)
})

test("the dashboard drops the old cards and charts", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() => expect(screen.getByText("Target coverage")).toBeDefined())
  for (const gone of [
    "Targets evaluated",
    "Targets with identified findings",
    "Verdict distribution",
    "Identification rate per Target (machine)",
    "Identification rate per version/environment",
    "exploited",
  ]) {
    expect(screen.queryByText(gone)).toBeNull()
  }
})

test("the vulnerability donut states partial as a subset of not found", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() => expect(screen.getByText("Vulnerability coverage")).toBeDefined())
  expect(screen.getByText("includes 1 partial")).toBeDefined()
})

test("the Found legend links to the successful vulnerabilities page", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() => expect(screen.getByText("Vulnerability coverage")).toBeDefined())
  fireEvent.click(screen.getByRole("link", { name: "Found" }))
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Successfully identified vulnerabilities" }),
    ).toBeDefined(),
  )
})

test("the dashboard flags partial data with a link to the degraded trial", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Partial data" })).toBeDefined(),
  )
  expect(screen.getByText(/verdicts_missing/)).toBeDefined()
})

// --- navigation ----------------------------------------------------------------

test("dataset to Target to Trial navigation works", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")
  await waitFor(() => expect(screen.getByText("Targets (machines)")).toBeDefined())

  fireEvent.click(
    within(screen.getByRole("table")).getByRole("link", { name: "comfyui-1" }),
  )
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "comfyui-1" })).toBeDefined(),
  )

  fireEvent.click(screen.getAllByRole("link", { name: "trial-1" })[0])
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /trial-1/ })).toBeDefined(),
  )
})

test("breadcrumbs link back through the hierarchy", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval/trials/comfyui-1/run-demo-a/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /trial-1/ })).toBeDefined(),
  )
  const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
  expect(within(crumbs).getByRole("link", { name: "Eval" })).toBeDefined()
  expect(within(crumbs).getByRole("link", { name: "WebExploitBench" })).toBeDefined()
  expect(within(crumbs).getByRole("link", { name: "comfyui-1" })).toBeDefined()
  expect(within(crumbs).getByText("trial-1")).toBeDefined()
})

test("browser back and forward move through the eval routes", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval")
  await waitFor(() => expect(screen.getByText("Targets (machines)")).toBeDefined())

  fireEvent.click(
    within(screen.getByRole("table")).getByRole("link", { name: "comfyui-1" }),
  )
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "comfyui-1" })).toBeDefined(),
  )

  window.history.back()
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "WebExploitBench" })).toBeDefined(),
  )
  window.history.forward()
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "comfyui-1" })).toBeDefined(),
  )
})

// --- Target page ---------------------------------------------------------------

test("the Target page groups its Trials by TargetRun", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval/targets/comfyui-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "comfyui-1" })).toBeDefined(),
  )
  expect(screen.getByRole("heading", { name: /run-demo-a/ })).toBeDefined()
  expect(screen.getByRole("heading", { name: /run-demo-b/ })).toBeDefined()
  expect(screen.getByText("Target (machine)")).toBeDefined()
})

// --- Trial page ----------------------------------------------------------------

const TRIAL_A = "/eval/trials/comfyui-1/run-demo-a/trial-1"

async function gotoEval(path: string, heading: string | RegExp) {
  stubFetch(SNAPSHOT)
  goto(path)
  await waitFor(() => expect(screen.getByRole("heading", { name: heading })).toBeDefined())
}

function artifactsRegion(): HTMLElement {
  return screen.getByRole("region", { name: "Artifacts" })
}

function artifactEntry(label: string): HTMLElement {
  const found = within(artifactsRegion())
    .getAllByRole("listitem")
    .find((item) => item.textContent?.includes(label))
  if (!found) throw new Error(`no artifact entry for ${label}`)
  return found
}

test("the Trial page is an index of exactly four materialized artifacts", async () => {
  await gotoEval(TRIAL_A, /^Trial trial-1$/)

  const entries = within(artifactsRegion()).getAllByRole("listitem")
  expect(entries).toHaveLength(4)
  expect(entries.map((entry) => entry.querySelector("a")?.textContent)).toEqual([
    "run-manifest.yaml",
    "verdicts.yaml",
    "diagnoses.yaml",
    "evidence/",
  ])
  // Each entry carries its own summary line.
  const text = artifactsRegion().textContent ?? ""
  expect(text).toContain("terminal complete")
  expect(text).toContain("2 phases")
  expect(text).toContain("demo-sha-a · demo-env-x")
  expect(text).toContain("3 verdict rows")
  expect(text).toContain("identified 1")
  expect(text).toContain("partial 2")
  expect(text).toContain("missed 0")
  expect(text).toContain("1 diagnosis")
  expect(text).toContain("required for 1 partial/missed vulnerability")
  expect(text).toContain("4 references")
  expect(text).toContain("covering 2 vulnerabilities")
  // Every state is spelled out in words, never colour alone.
  expect(within(artifactsRegion()).getAllByText("Available")).toHaveLength(4)
})

test("the Trial header still labels terminal and availability separately", async () => {
  await gotoEval(TRIAL_A, /^Trial trial-1$/)

  expect(screen.getByText("Terminal", { selector: ".eval-chip-label" })).toBeDefined()
  expect(screen.getByText("Availability", { selector: ".eval-chip-label" })).toBeDefined()
  expect(screen.getAllByText("complete", { selector: ".eval-chip-value" })).toHaveLength(2)
})

test("each artifact entry links to its dedicated route", async () => {
  await gotoEval(TRIAL_A, /^Trial trial-1$/)

  const href = (label: string) => artifactEntry(label).querySelector("a")?.getAttribute("href")
  expect(href("run-manifest.yaml")).toBe(`${TRIAL_A}/manifest`)
  expect(href("verdicts.yaml")).toBe(`${TRIAL_A}/verdicts`)
  expect(href("diagnoses.yaml")).toBe(`${TRIAL_A}/diagnoses`)
  expect(href("evidence/")).toBe(`${TRIAL_A}/evidence`)
})

test("the manifest view shows exactly the projected fields", async () => {
  await gotoEval(`${TRIAL_A}/manifest`, "run-manifest.yaml")

  const labels = [...document.querySelectorAll(".eval-context dt")].map(
    (node) => node.textContent,
  )
  expect(labels).toEqual([
    "Target (machine)",
    "TargetRun",
    "Trial",
    "Availability",
    "Instance",
    "Project",
    "Start phase",
    "Terminal",
    "eval_sha",
    "stack_fingerprint",
    "Copied at",
  ])
  expect(screen.getAllByText("recon").length).toBeGreaterThan(0)
  expect(screen.getByText("hunt-1")).toBeDefined()
  const text = (document.body.textContent ?? "").toLowerCase()
  for (const absent of [
    "duration",
    "started_at",
    "finished_at",
    "hunt_config_budget",
    "cap_hit",
    "workflow",
  ]) {
    expect(text).not.toContain(absent)
  }
})

test("the verdicts view shows every materialized row, in order, unmerged", async () => {
  await gotoEval(`${TRIAL_A}/verdicts`, "verdicts.yaml")

  const entries = [...document.querySelectorAll<HTMLElement>(".eval-artifact-entry")]
  // Three raw rows: DEMO-1, DEMO-2, DEMO-2 - the duplicates stay distinct.
  expect(entries).toHaveLength(3)
  expect(entries.map((item) => item.querySelector("h3 .eval-ref")?.textContent)).toEqual([
    "DEMO-1",
    "DEMO-2",
    "DEMO-2",
  ])
  // A stable row identifier distinguishes them without touching the data.
  expect(entries.map((item) => item.querySelector(".eval-row-index")?.textContent)).toEqual([
    "row 1",
    "row 2",
    "row 3",
  ])

  // Row 1: identified, its own match and its own (safe) refs only.
  expect(within(entries[0]).getByText("90%")).toBeDefined()
  expect(within(entries[0]).getByText("comfyui.manager")).toBeDefined()
  expect(within(entries[0]).getByText("demo/comfyui-1/trial-1/hunt-config.yaml")).toBeDefined()
  expect(within(entries[0]).getByText("demo/comfyui-1/trial-1/export.yaml")).toBeDefined()
  expect(within(entries[0]).queryByText("demo/comfyui-1/trial-1/spec")).toBeNull()

  // Rows 2 and 3 share the vuln_id but keep their own details.
  expect(within(entries[1]).getByText("40%")).toBeDefined()
  expect(within(entries[1]).getByText("comfyui.nodes")).toBeDefined()
  expect(within(entries[1]).getByText("likely_rce")).toBeDefined()
  expect(within(entries[1]).getByText("demo/comfyui-1/trial-1/spec")).toBeDefined()
  expect(within(entries[1]).queryByText("demo/comfyui-1/trial-1/spec-extra")).toBeNull()

  expect(within(entries[2]).getByText("35%")).toBeDefined()
  expect(within(entries[2]).getByText("comfyui.nodes.extra")).toBeDefined()
  expect(within(entries[2]).getByText("alt_rce")).toBeDefined()
  expect(within(entries[2]).getByText("demo/comfyui-1/trial-1/spec-extra")).toBeDefined()
  expect(within(entries[2]).queryByText("demo/comfyui-1/trial-1/spec")).toBeNull()
})

test("the diagnoses view pairs each diagnosis with its vulnerability", async () => {
  await gotoEval(`${TRIAL_A}/diagnoses`, "diagnoses.yaml")

  const cards = [...document.querySelectorAll<HTMLElement>(".eval-diagnosis")]
  expect(cards).toHaveLength(1)
  expect(within(cards[0]).getByText("DEMO-2")).toBeDefined()
  expect(within(cards[0]).getByText(/spec_underspecified/)).toBeDefined()
  expect(within(cards[0]).getByText("kb_coverage_gap", { selector: "strong" })).toBeDefined()
  expect(within(cards[0]).getByText(/org\/demo#7/)).toBeDefined()
})

test("a missed verdict's diagnosis shows its proposed issue", async () => {
  await gotoEval(
    "/eval/trials/comfyui-1/run-demo-b/trial-1/diagnoses",
    "diagnoses.yaml",
  )

  const cards = [...document.querySelectorAll<HTMLElement>(".eval-diagnosis")]
  expect(cards).toHaveLength(1)
  expect(within(cards[0]).getByText("DEMO-4")).toBeDefined()
  expect(within(cards[0]).getByText(/surface_gap/)).toBeDefined()
  expect(within(cards[0]).getByText(/Enumerate it/)).toBeDefined()
  expect(within(cards[0]).queryByText(/Closest issue/)).toBeNull()
})

test("the diagnoses view reports not required when every verdict is identified", async () => {
  await gotoEval("/eval/trials/comfyui-1/run-demo-c/trial-1/diagnoses", "diagnoses.yaml")

  expect(screen.getByText("Not required", { selector: ".eval-artifact-status" })).toBeDefined()
  expect(screen.getByText(/no diagnoses are required/i)).toBeDefined()
})

test("the evidence view dedupes, groups by vulnerability, and drops unsafe refs", async () => {
  await gotoEval(`${TRIAL_A}/evidence`, "evidence/")

  const groups = [
    ...document.querySelectorAll<HTMLElement>('section[aria-label^="Evidence for "]'),
  ]
  expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
    "Evidence for DEMO-1",
    "Evidence for DEMO-2",
  ])
  const demo1 = groups[0]
  expect(within(demo1).getByText("demo/comfyui-1/trial-1/hunt-config.yaml")).toBeDefined()
  expect(within(demo1).getByText("demo/comfyui-1/trial-1/export.yaml")).toBeDefined()
  // Host paths and URLs are never rendered.
  const text = document.body.textContent ?? ""
  expect(text).not.toContain("/etc/passwd")
  expect(text).not.toContain("evil.invalid")
  // DEMO-2's refs stay under DEMO-2, deduped from its two rows.
  const demo2 = groups[1]
  expect(within(demo2).getByText("demo/comfyui-1/trial-1/spec")).toBeDefined()
  expect(within(demo2).getByText("demo/comfyui-1/trial-1/spec-extra")).toBeDefined()
  expect(demo2.querySelectorAll("li")).toHaveLength(2)
})

test("a degraded Trial shows explicit artifact states", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval/trials/white-jotter-1/run-demo-a/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Degraded trial" })).toBeDefined(),
  )
  expect(screen.getByText("degraded", { selector: ".eval-chip-value" })).toBeDefined()
  const text = artifactsRegion().textContent ?? ""
  expect(text).toContain("No verdicts.yaml was materialized (verdicts_missing)")
  expect(text).toContain("Cannot be determined")
  expect(text).toContain("No safe evidence references were materialized")
  expect(within(artifactsRegion()).getAllByText("Not materialized").length).toBe(2)
})

test("a missing artifact view states it explicitly", async () => {
  await gotoEval("/eval/trials/white-jotter-1/run-demo-a/trial-1/verdicts", "verdicts.yaml")

  expect(screen.getByText("Not materialized", { selector: ".eval-artifact-status" })).toBeDefined()
  expect(screen.getByText(/No verdicts.yaml was materialized/)).toBeDefined()
  expect(document.querySelectorAll(".eval-artifact-entry")).toHaveLength(0)
})

test("the artifact breadcrumb links back to the Trial", async () => {
  await gotoEval(`${TRIAL_A}/evidence`, "evidence/")

  const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
  const trialLink = within(crumbs).getByRole("link", { name: "trial-1" })
  expect(trialLink.getAttribute("href")).toBe(TRIAL_A)
  expect(within(crumbs).getByText("evidence/")).toBeDefined()

  fireEvent.click(trialLink)
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /^Trial trial-1$/ })).toBeDefined(),
  )
  expect(artifactsRegion()).toBeDefined()
})

test("the Trial breadcrumb reaches the TargetRun group by anchor", async () => {
  await gotoEval(TRIAL_A, /^Trial trial-1$/)

  const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
  const runLink = within(crumbs).getByRole("link", { name: "run-demo-a" })
  expect(runLink.getAttribute("href")).toBe(
    "/eval/targets/comfyui-1#targetrun-run-demo-a",
  )

  fireEvent.click(runLink)
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "comfyui-1" })).toBeDefined(),
  )
  expect(document.getElementById("targetrun-run-demo-a")).not.toBeNull()
})

// --- Version page --------------------------------------------------------------

test("the version view identifies and separates the fingerprint", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval/versions/demo-sha-a/demo-env-z")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Version" })).toBeDefined(),
  )
  expect(screen.getByText("demo-env-z")).toBeDefined()
  expect(screen.queryByText("demo-env-x")).toBeNull()
  expect(screen.getByRole("link", { name: "white-jotter-1" })).toBeDefined()
})

// --- Successful vulnerabilities ------------------------------------------------

test("successful vulnerabilities exclude partial and missed", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval/vulnerabilities")

  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Successfully identified vulnerabilities" }),
    ).toBeDefined(),
  )
  expect(screen.getByText("DEMO-1")).toBeDefined()
  expect(screen.getByText("DEMO-3")).toBeDefined()
  expect(screen.queryByText("DEMO-2")).toBeNull()
  expect(screen.queryByText("DEMO-4")).toBeNull()
})

// --- shared states -------------------------------------------------------------

test("shows a loading state before the snapshot resolves", () => {
  globalThis.fetch = (() => new Promise(() => {})) as typeof fetch
  goto("/eval")

  expect(screen.getByText(/loading/i)).toBeDefined()
})

test("shows an error state when the API fails", async () => {
  stubFetch({ detail: "unavailable" }, 503)
  goto("/eval")

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
})

test("shows an empty state when there is nothing to report", async () => {
  stubFetch(EMPTY)
  goto("/eval")

  await waitFor(() => expect(screen.getByText(/no eval results/i)).toBeDefined())
})

// --- non-eval routes -----------------------------------------------------------

test("the non-eval routes still render", async () => {
  stubFetch({ projects: [] })
  goto("/")

  await waitFor(() => expect(screen.getByText("Projects")).toBeDefined())
  expect(screen.queryByText("Targets (machines)")).toBeNull()
})

// --- reciprocal link to the project workspace ----------------------------------

test("the eval Trial links to the project workspace with the full identity", async () => {
  stubFetch(SNAPSHOT)
  goto("/eval/trials/comfyui-1/run-demo-a/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "Open project workspace" })).toBeDefined(),
  )
  expect(
    screen.getByRole("link", { name: "Open project workspace" }).getAttribute("href"),
  ).toBe("/p/proj-comfyui-1/evals/comfyui-1/run-demo-a/trial-1")
})

test("the eval Trial shows no project link when project_id is null", async () => {
  stubFetch(SNAPSHOT)
  // The degraded trial in the corpus carries no project_id.
  goto("/eval/trials/white-jotter-1/run-demo-a/trial-1")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: /Trial trial-1/ })).toBeDefined(),
  )
  expect(screen.queryByRole("link", { name: "Open project workspace" })).toBeNull()
})
