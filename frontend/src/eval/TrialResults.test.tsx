import { useLayoutEffect } from "react"
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
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
    .queryAllByRole("listitem")
    .filter((item) => item.className.includes("trial-result-row"))
}

function rowToggle(row: HTMLElement): HTMLButtonElement {
  return within(row).getByRole("button") as HTMLButtonElement
}

function rowBody(row: HTMLElement): HTMLElement {
  return row.querySelector(".eval-result-body") as HTMLElement
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
  expect(within(first).getAllByText("90%").length).toBeGreaterThan(0)
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

  fireEvent.click(rowToggle(rows()[0]))
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
  fireEvent.click(rowToggle(rows()[0]))
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
  fireEvent.click(rowToggle(rows()[0]))
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


// --- collapsible result rows ---------------------------------------------------


function RowStateProbe({
  trial,
  log,
}: {
  trial: EvalTrial
  log: Array<{ id: string; expanded: string | null }>
}) {
  const id = `${trial.target_id}|${trial.target_run_id}|${trial.trial_id}`
  useLayoutEffect(() => {
    const toggle = document.querySelector<HTMLElement>(".eval-result-toggle")
    log.push({ id, expanded: toggle?.getAttribute("aria-expanded") ?? null })
  })
  return null
}

function renderProbe(t: EvalTrial) {
  const log: Array<{ id: string; expanded: string | null }> = []
  const tree = (next: EvalTrial) => (
    <MemoryRouter>
      <TrialResults trial={next} />
      <RowStateProbe trial={next} log={log} />
    </MemoryRouter>
  )
  const { rerender } = render(tree(t))
  return { log, rerender: (next: EvalTrial) => rerender(tree(next)) }
}

test("every result row starts closed with its key facts still visible", () => {
  renderResults(trial())

  const all = rows()
  expect(all).toHaveLength(4)
  for (const row of all) {
    expect(rowToggle(row).getAttribute("aria-expanded")).toBe("false")
    expect(rowBody(row).hasAttribute("hidden")).toBe(true)
  }
  const first = rowToggle(all[0])
  expect(within(first).getByText("row 1")).toBeDefined()
  expect(within(first).getByText("DEMO-1")).toBeDefined()
  expect(within(first).getByText("identified")).toBeDefined()
  expect(within(first).getByText("90%")).toBeDefined()
})

test("a closed row hides its body, including Evidence, from the accessibility tree", () => {
  renderResults(trial())

  const first = rows()[0]
  expect(rowBody(first).hasAttribute("hidden")).toBe(true)
  // `hidden` removes the subtree from role queries, i.e. from the tab order.
  expect(within(first).queryByRole("heading", { name: "Evidence" })).toBeNull()
  expect(within(first).queryByRole("link", { name: "demo/a.yaml" })).toBeNull()
})

test("click, Enter and Space each toggle exactly one row", () => {
  renderResults(trial())
  const toggle = rowToggle(rows()[0])

  fireEvent.click(toggle)
  expect(toggle.getAttribute("aria-expanded")).toBe("true")
  fireEvent.click(toggle)
  expect(toggle.getAttribute("aria-expanded")).toBe("false")

  fireEvent.keyDown(toggle, { key: "Enter" })
  expect(toggle.getAttribute("aria-expanded")).toBe("true")
  fireEvent.keyDown(toggle, { key: "Enter" })
  expect(toggle.getAttribute("aria-expanded")).toBe("false")

  fireEvent.keyDown(toggle, { key: " " })
  expect(toggle.getAttribute("aria-expanded")).toBe("true")
  fireEvent.keyDown(toggle, { key: " " })
  expect(toggle.getAttribute("aria-expanded")).toBe("false")
})

test("opening a row keeps match, ground truth, evidence and diagnosis reachable", () => {
  renderWithGroundTruth(trial(), GROUND_TRUTH_READY)

  const first = rows()[0]
  fireEvent.click(rowToggle(first))

  expect(rowBody(first).hasAttribute("hidden")).toBe(false)
  expect(within(first).getByText("comfyui.manager")).toBeDefined()
  expect(within(first).getByText("Ground truth (current benchmark)")).toBeDefined()
  expect(within(first).getByRole("heading", { name: "Evidence" })).toBeDefined()

  const second = rows()[1]
  fireEvent.click(rowToggle(second))
  expect(within(second).getByText(/spec_underspecified/)).toBeDefined()
})

test("an opened row keeps its canonical Evidence links", async () => {
  const t = trialWithEvidence(["proj-1/hunting/x.yaml"])
  stubInventory(availableInventory([artifactEntry("a1", "hunting/x.yaml")]))

  renderInWorkspace(t)
  fireEvent.click(rowToggle(rows()[0]))

  const link = await screen.findByRole("link", { name: "proj-1/hunting/x.yaml" })
  expect(link.getAttribute("href")).toBe("/targets/comfyui-1/trials/run-a/t1/artifacts/a1")
})

test("two rows with the same vuln_id toggle independently with distinct DOM ids", () => {
  renderResults(trial())

  const all = rows()
  const first = rowToggle(all[1])
  const second = rowToggle(all[2])
  const firstId = first.getAttribute("aria-controls")
  const secondId = second.getAttribute("aria-controls")
  expect(firstId).not.toBe(secondId)
  expect(document.getElementById(firstId!)).not.toBeNull()
  expect(document.getElementById(secondId!)).not.toBeNull()

  fireEvent.click(first)
  expect(first.getAttribute("aria-expanded")).toBe("true")
  expect(second.getAttribute("aria-expanded")).toBe("false")
  expect(rowBody(all[1]).hasAttribute("hidden")).toBe(false)
  expect(rowBody(all[2]).hasAttribute("hidden")).toBe(true)
})

test("a poll that recreates the Trial keeps choices and closes the new row", () => {
  const first = trial()
  const { rerender } = renderResults(first)
  fireEvent.click(rowToggle(rows()[1]))
  expect(rowToggle(rows()[1]).getAttribute("aria-expanded")).toBe("true")

  const refreshed = trial({
    verdicts: [
      ...first.verdicts,
      {
        vuln_id: "DEMO-5",
        identified: "missed",
        confidence: 0,
        matched: { unit: null, fault_class: null, symptom: null },
        evidence: [],
      },
    ],
  })
  rerender(
    <MemoryRouter>
      <TrialResults trial={refreshed} />
    </MemoryRouter>,
  )

  const after = rows()
  expect(after).toHaveLength(5)
  expect(rowToggle(after[1]).getAttribute("aria-expanded")).toBe("true")
  expect(rowToggle(after[4]).getAttribute("aria-expanded")).toBe("false")
})

function assertIdentityClosesEveryRow(makeSecond: () => EvalTrial) {
  const { log, rerender } = renderProbe(trial())
  fireEvent.click(rowToggle(rows()[0]))
  expect(rowToggle(rows()[0]).getAttribute("aria-expanded")).toBe("true")

  const second = makeSecond()
  log.length = 0
  rerender(second)

  // Every committed render of the new identity must already be closed: the
  // reset may not wait for an effect.
  const identity = `${second.target_id}|${second.target_run_id}|${second.trial_id}`
  const committed = log.filter((entry) => entry.id === identity)
  expect(committed.length).toBeGreaterThan(0)
  expect(committed.every((entry) => entry.expanded === "false")).toBe(true)
  expect(rowToggle(rows()[0]).getAttribute("aria-expanded")).toBe("false")
}

test("changing trial_id closes every row before the first commit", () => {
  assertIdentityClosesEveryRow(() => trial({ trial_id: "t2" }))
})

test("changing target_run_id closes every row before the first commit", () => {
  assertIdentityClosesEveryRow(() => trial({ target_run_id: "run-b" }))
})

test("changing target_id closes every row before the first commit", () => {
  assertIdentityClosesEveryRow(() => trial({ target_id: "comfyui-2" }))
})

test("empty results keep the existing empty notice", () => {
  renderResults(trial({ verdicts: [], diagnoses: [] }))

  expect(screen.getByText("No results were materialized for this Trial.")).toBeDefined()
  expect(rows()).toHaveLength(0)
})

test("a missing diagnosis keeps its notice once the row is open", () => {
  renderResults(
    trial({
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
    }),
  )

  fireEvent.click(rowToggle(rows()[0]))
  expect(screen.getByText(/no diagnosis was materialized/i)).toBeDefined()
})

test("unavailable ground truth keeps the fallback on every row", () => {
  renderWithGroundTruth(trial(), { status: "unavailable" })

  for (const row of rows()) {
    fireEvent.click(rowToggle(row))
    expect(within(row).getByText("Ground truth non disponibile")).toBeDefined()
  }
})
