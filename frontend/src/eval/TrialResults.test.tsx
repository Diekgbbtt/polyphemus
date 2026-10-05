import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, test } from "vitest"
import { TrialResults } from "./TrialResults"
import type { GroundTruthState } from "./operatorGroundTruth"
import type { EvalTrial } from "./types"

function trial(overrides: Partial<EvalTrial> = {}): EvalTrial {
  return {
    target_id: "comfyui-1",
    target_run_id: "run-a",
    trial_id: "t1",
    instance_id: "eval-server-1",
    project_id: "proj-1",
    start_phase: "recon",
    terminal: "complete",
    copied_at: "2024-01-01T00:00:00+00:00",
    phases: [],
    eval_sha: "sha",
    stack_fingerprint: "fp",
    verdicts: [
      {
        vuln_id: "DEMO-1",
        identified: "identified",
        confidence: 0.9,
        matched: { unit: "comfyui.manager", fault_class: "CWE-78", symptom: "rce" },
        // A path that escapes and a URL the server never emits: both rejected.
        evidence: ["demo/a.yaml", "/etc/passwd", "https://evil.invalid/x.yaml"],
      },
      {
        vuln_id: "DEMO-2",
        identified: "partial",
        confidence: 0.4,
        matched: { unit: "comfyui.nodes", fault_class: "CWE-94", symptom: "likely_rce" },
        evidence: ["demo/b.yaml"],
      },
      {
        vuln_id: "DEMO-2",
        identified: "partial",
        confidence: 0.35,
        matched: { unit: "comfyui.nodes.extra", fault_class: "CWE-94", symptom: "alt" },
        evidence: ["demo/c.yaml"],
      },
      {
        vuln_id: "DEMO-3",
        identified: "missed",
        confidence: 0,
        matched: { unit: null, fault_class: null, symptom: null },
        evidence: [],
      },
    ],
    diagnoses: [
      {
        vuln: "DEMO-2",
        failure_mode: "spec_underspecified",
        root_cause: { type: "kb_coverage_gap", combination_of: [], extended_description: null },
        diagnosis_overview: "the spec never pinned the loader",
        closest_issue: null,
        proposed_issue: null,
      },
      {
        vuln: "DEMO-3",
        failure_mode: "surface_gap",
        root_cause: { type: "recon_gap", combination_of: ["skill_defect"], extended_description: null },
        diagnosis_overview: "no surface covered",
        closest_issue: null,
        proposed_issue: null,
      },
      {
        vuln: "DEMO-9",
        failure_mode: "orphaned",
        root_cause: { type: "kb_coverage_gap", combination_of: [], extended_description: null },
        diagnosis_overview: "a diagnosis with no verdict row",
        closest_issue: null,
        proposed_issue: null,
      },
    ],
    availability: "complete",
    reason: null,
    artifact_summary: { status: "available", hunting: 1, skills: 0 },
    project_graph_summary: {
      status: "available",
      nodes: 1,
      links: 0,
      captured_at: "2024-01-01T00:00:00+00:00",
    },
    ...overrides,
  }
}

function renderResults(t: EvalTrial) {
  return render(
    <MemoryRouter>
      <TrialResults trial={t} />
    </MemoryRouter>,
  )
}

function rows(): HTMLElement[] {
  return screen
    .getAllByRole("listitem")
    .filter((item) => item.className.includes("trial-result-row"))
}

test("renders one distinct row per verdict, including repeats for one vulnerability", () => {
  renderResults(trial())

  const all = rows()
  expect(all).toHaveLength(4)
  const hasLabel = (row: HTMLElement, text: string) =>
    within(row).getAllByText(text).length > 0
  expect(hasLabel(all[0], "DEMO-1")).toBe(true)
  // Two rows share DEMO-2 and stay two distinct entries.
  expect(hasLabel(all[1], "DEMO-2")).toBe(true)
  expect(hasLabel(all[2], "DEMO-2")).toBe(true)
  expect(hasLabel(all[3], "DEMO-3")).toBe(true)
  // Each row carries an explicit textual verdict label, not colour alone.
  expect(within(all[0]).getAllByText("identified").length).toBeGreaterThan(0)
  expect(within(all[1]).getAllByText("partial").length).toBeGreaterThan(0)
  expect(within(all[3]).getAllByText("missed").length).toBeGreaterThan(0)
})

test("each row shows confidence, safe match fields and only safe evidence", () => {
  renderResults(trial())

  const first = rows()[0]
  expect(within(first).getByText("90%")).toBeDefined()
  expect(within(first).getByText("comfyui.manager")).toBeDefined()
  expect(within(first).getByText("CWE-78")).toBeDefined()
  expect(within(first).getByText("rce")).toBeDefined()
  expect(within(first).getByText("demo/a.yaml")).toBeDefined()
  expect(within(first).queryByText("/etc/passwd")).toBeNull()
  expect(within(first).queryByText("https://evil.invalid/x.yaml")).toBeNull()
})

test("pairs diagnoses by vulnerability and never invents a missing one", () => {
  renderResults(trial())

  const partialRow = rows()[1]
  expect(within(partialRow).getByText(/spec_underspecified/)).toBeDefined()
  const missedRow = rows()[3]
  expect(within(missedRow).getByText(/surface_gap/)).toBeDefined()

  const noDiagnosis = trial({
    verdicts: [
      {
        vuln_id: "DEMO-4",
        identified: "missed",
        confidence: 0,
        matched: { unit: null, fault_class: null, symptom: null },
        evidence: [],
      },
    ],
    diagnoses: [],
  })
  renderResults(noDiagnosis)
  expect(screen.getAllByText(/no diagnosis was materialized/i).length).toBeGreaterThan(0)
})

test("keeps an unmatched diagnosis visible and explicitly labelled", () => {
  renderResults(trial())

  const section = screen.getByRole("region", { name: /unmatched diagnoses/i })
  expect(within(section).getByText("DEMO-9")).toBeDefined()
  expect(within(section).getByText(/no materialized verdict/i)).toBeDefined()
})


// --- operator ground truth -----------------------------------------------------


const GROUND_TRUTH_READY: GroundTruthState = {
  status: "ready",
  data: {
    target_id: "comfyui-1",
    provenance: "current_benchmark_checkout",
    vulnerabilities: [
      {
        vuln_id: "DEMO-1",
        location: "http://comfyui-manager:8288/view",
        type: "Arbitrary File Read",
        scoring: ["LLM_judge"],
      },
      { vuln_id: "DEMO-2", location: "/api/v1/items", type: "Path Traversal", scoring: [] },
      {
        vuln_id: "OTHER-1",
        location: "http://other.invalid/",
        type: "Other",
        scoring: ["route_probe"],
      },
    ],
  },
}

function renderWithGroundTruth(t: EvalTrial, state: GroundTruthState) {
  return render(
    <MemoryRouter>
      <TrialResults trial={t} groundTruth={state} />
    </MemoryRouter>,
  )
}

test("shows the matching reference beneath the match cards and above Evidence", () => {
  renderWithGroundTruth(trial(), GROUND_TRUTH_READY)

  const first = rows()[0]
  expect(within(first).getByText("Ground truth (current benchmark)")).toBeDefined()
  expect(within(first).getByText("http://comfyui-manager:8288/view")).toBeDefined()
  expect(within(first).getByText("Arbitrary File Read")).toBeDefined()
  expect(within(first).getByText("LLM_judge")).toBeDefined()
  // Another vulnerability's reference is never borrowed.
  expect(first.textContent).not.toContain("other.invalid")

  // Position: after the match cards, before the Evidence heading.
  const labels = [...first.querySelectorAll("h4")].map((h) => h.textContent?.trim())
  expect(labels.indexOf("Ground truth (current benchmark)")).toBeGreaterThan(-1)
  expect(labels.indexOf("Ground truth (current benchmark)")).toBeLessThan(
    labels.indexOf("Evidence"),
  )
  expect(first.querySelector("dl.eval-match")).not.toBeNull()
})

test("two rows for the same vulnerability both receive the same reference", () => {
  renderWithGroundTruth(trial(), GROUND_TRUTH_READY)

  // DEMO-2 has two materialized rows; neither collapses nor borrows.
  expect(rows()[1].textContent).toContain("/api/v1/items")
  expect(rows()[2].textContent).toContain("/api/v1/items")
})

test("a missing reference shows the exact fallback without touching the verdict", () => {
  renderWithGroundTruth(trial(), GROUND_TRUTH_READY)
  const missing = rows()[3] // DEMO-3 has no reference entry
  expect(within(missing).getByText("Ground truth non disponibile")).toBeDefined()
  // The verdict itself is untouched.
  expect(within(missing).getAllByText("missed").length).toBeGreaterThan(0)
})


test("an unavailable API shows the fallback on every row and hides nothing", () => {
  renderWithGroundTruth(trial(), { status: "unavailable" })
  for (const row of rows()) {
    expect(within(row).getByText("Ground truth non disponibile")).toBeDefined()
  }
  // Rejection never hides the materialized results.
  expect(screen.getAllByText("90%").length).toBeGreaterThan(0)
  expect(screen.getAllByText("demo/a.yaml").length).toBeGreaterThan(0)
})

test("empty scoring signals render as an em dash", () => {
  renderWithGroundTruth(trial(), GROUND_TRUTH_READY)

  const second = rows()[1]
  expect(within(second).getByText("—")).toBeDefined()
})

test("no reference panel is rendered when a caller supplies no state", () => {
  renderResults(trial())

  expect(screen.queryByText("Ground truth (current benchmark)")).toBeNull()
  expect(screen.queryByText("Ground truth non disponibile")).toBeNull()
})
