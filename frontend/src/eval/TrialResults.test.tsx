import { act, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, expect, test, vi } from "vitest"
import { ResolvedArtifactsProvider } from "./ResolvedArtifactsProvider"
import { TrialResults } from "./TrialResults"
import type { GroundTruthState } from "./operatorGroundTruth"
import type {
  EvalTrial,
  ProjectArtifactEntry,
  ProjectArtifactGroup,
  ResolvedArtifactInventory,
} from "./types"

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

// --- evidence -> artifact links -------------------------------------------------

const POLL = 15_000

function artifactEntry(id: string, relativePath: string): ProjectArtifactEntry {
  return {
    artifact_id: id,
    category: "hunting",
    kind: "test_spec",
    relative_path: relativePath,
    media_type: "application/yaml",
    size_bytes: 10,
    sha256: `sha-${id}`,
    representation: "yaml",
  }
}

function groupsOf(entries: ProjectArtifactEntry[], projectId = "proj-1"): ProjectArtifactGroup[] {
  return [
    {
      key: "g",
      label: "G",
      category: "hunting",
      entries,
      children: [],
    },
  ]
}

function availableInventory(
  entries: ProjectArtifactEntry[],
  projectId = "proj-1",
): ResolvedArtifactInventory {
  return {
    status: "available",
    source: "project_storage",
    project_id: projectId,
    fallback_reason: null,
    groups: groupsOf(entries, projectId),
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function trialWithEvidence(evidence: string[]): EvalTrial {
  return trial({
    verdicts: [
      {
        vuln_id: "V-1",
        identified: "partial",
        confidence: 0.5,
        matched: { unit: null, fault_class: null, symptom: null },
        evidence,
      },
    ],
    diagnoses: [],
  })
}

function stubInventory(body: unknown): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    if (url.endsWith("/resolved-artifacts")) return json(body)
    return json({ detail: "not_found" }, 404)
  }) as typeof fetch
  return calls
}

function renderInWorkspace(t: EvalTrial) {
  return render(
    <MemoryRouter>
      <ResolvedArtifactsProvider
        targetId={t.target_id}
        targetRunId={t.target_run_id}
        trialId={t.trial_id}
        expectedProjectId={t.project_id}
      >
        <TrialResults trial={t} />
      </ResolvedArtifactsProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.useRealTimers()
})

test("links a matching evidence reference to the canonical artifact route", async () => {
  const t = trialWithEvidence(["proj-1/hunting/x.yaml"])
  stubInventory(availableInventory([artifactEntry("a1", "hunting/x.yaml")]))

  renderInWorkspace(t)

  const link = await screen.findByRole("link", { name: "proj-1/hunting/x.yaml" })
  expect(link.getAttribute("href")).toBe("/targets/comfyui-1/trials/run-a/t1/artifacts/a1")
})

test("keeps a safe unmatched reference as text with Artifact non disponibile", async () => {
  const t = trialWithEvidence(["proj-1/hunting/nope.yaml"])
  stubInventory(availableInventory([artifactEntry("a1", "hunting/x.yaml")]))

  renderInWorkspace(t)

  await waitFor(() => expect(screen.getByText(/Artifact non disponibile/)).toBeDefined())
  expect(screen.getByText("proj-1/hunting/nope.yaml")).toBeDefined()
  expect(screen.queryByRole("link", { name: "proj-1/hunting/nope.yaml" })).toBeNull()
})

test("a directory reference (spec_dir) stays unlinked", async () => {
  const t = trialWithEvidence(["proj-1/hunting/hunter/test-specs/F"])
  stubInventory(
    availableInventory([
      artifactEntry("a1", "hunting/hunter/test-specs/F/produced/x.yaml"),
      artifactEntry("a2", "hunting/hunter/test-specs/F/consumed/y.yaml"),
    ]),
  )

  renderInWorkspace(t)

  await waitFor(() => expect(screen.getByText(/Artifact non disponibile/)).toBeDefined())
  expect(screen.queryByRole("link", { name: "proj-1/hunting/hunter/test-specs/F" })).toBeNull()
})

test("a different project's prefix is never linked", async () => {
  const t = trialWithEvidence(["proj-2/hunting/x.yaml"])
  stubInventory(availableInventory([artifactEntry("a1", "hunting/x.yaml")]))

  renderInWorkspace(t)

  await waitFor(() => expect(screen.getByText(/Artifact non disponibile/)).toBeDefined())
  expect(screen.queryByRole("link", { name: "proj-2/hunting/x.yaml" })).toBeNull()
})

test("shows Verifica artifact in corso while the first inventory load is pending", async () => {
  const t = trialWithEvidence(["proj-1/hunting/x.yaml"])
  globalThis.fetch = (async (_input: unknown, init?: RequestInit) =>
    await new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener(
        "abort",
        () => reject(new DOMException("aborted", "AbortError")),
        { once: true },
      )
    })) as typeof fetch

  renderInWorkspace(t)

  await waitFor(() => expect(screen.getByText(/Verifica artifact in corso/)).toBeDefined())
  expect(screen.getByText("proj-1/hunting/x.yaml")).toBeDefined()
  expect(screen.queryByRole("link", { name: "proj-1/hunting/x.yaml" })).toBeNull()
  expect(screen.queryByText(/Artifact non disponibile/)).toBeNull()
})

test("an inventory error keeps the results and never claims absence", async () => {
  const t = trialWithEvidence(["proj-1/hunting/x.yaml"])
  globalThis.fetch = (async () => json({ detail: "artifact_unsafe" }, 409)) as typeof fetch

  renderInWorkspace(t)

  await waitFor(() => expect(screen.getByText("proj-1/hunting/x.yaml")).toBeDefined())
  expect(screen.getAllByText("50%").length).toBeGreaterThan(0)
  expect(screen.queryByRole("link", { name: "proj-1/hunting/x.yaml" })).toBeNull()
  expect(screen.queryByText(/Artifact non disponibile/)).toBeNull()
  expect(screen.queryByText(/Verifica artifact in corso/)).toBeNull()
})

test("a reference that was missing becomes clickable after the inventory refreshes", async () => {
  vi.useFakeTimers()
  const t = trialWithEvidence(["proj-1/hunting/x.yaml"])
  let body: unknown = availableInventory([])
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    if (url.endsWith("/resolved-artifacts")) return json(body)
    return json({ detail: "not_found" }, 404)
  }) as typeof fetch

  renderInWorkspace(t)
  await act(async () => {})
  expect(screen.getByText(/Artifact non disponibile/)).toBeDefined()

  body = availableInventory([artifactEntry("a1", "hunting/x.yaml")])
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(screen.getByRole("link", { name: "proj-1/hunting/x.yaml" })).toBeDefined()
})

test("results used without a workspace provider stay plain and fetch nothing", () => {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    calls.push(String(input))
    return json({})
  }) as typeof fetch

  renderResults(trialWithEvidence(["proj-1/hunting/x.yaml"]))

  expect(screen.getByText("proj-1/hunting/x.yaml")).toBeDefined()
  expect(screen.queryByRole("link", { name: "proj-1/hunting/x.yaml" })).toBeNull()
  expect(calls).toHaveLength(0)
})

test("changing the Trial drops the previous links immediately", async () => {
  const first = trialWithEvidence(["proj-1/hunting/x.yaml"])
  stubInventory(availableInventory([artifactEntry("a1", "hunting/x.yaml")]))
  const { rerender } = renderInWorkspace(first)
  await screen.findByRole("link", { name: "proj-1/hunting/x.yaml" })

  // The next Trial's inventory never settles: no stale link may survive.
  globalThis.fetch = (async (_input: unknown, init?: RequestInit) =>
    await new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener(
        "abort",
        () => reject(new DOMException("aborted", "AbortError")),
        { once: true },
      )
    })) as typeof fetch
  const second = { ...trialWithEvidence(["proj-1/hunting/x.yaml"]), trial_id: "t2" }
  rerender(
    <MemoryRouter>
      <ResolvedArtifactsProvider
        targetId={second.target_id}
        targetRunId={second.target_run_id}
        trialId={second.trial_id}
        expectedProjectId={second.project_id}
      >
        <TrialResults trial={second} />
      </ResolvedArtifactsProvider>
    </MemoryRouter>,
  )

  await waitFor(() =>
    expect(screen.queryByRole("link", { name: "proj-1/hunting/x.yaml" })).toBeNull(),
  )
})
