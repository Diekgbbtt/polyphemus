import { render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { EvalDataProvider } from "./EvalDataProvider"
import { TrialSection } from "./TrialSection"
import type { ProjectUsage } from "../api/types"
import type { EvalSnapshot, EvalTrial, EvalVerdict } from "./types"

function verdict(identified: EvalVerdict["identified"]): EvalVerdict {
  return {
    vuln_id: `${identified}-1`,
    identified,
    confidence: 0.5,
    matched: { unit: "unit", fault_class: "CWE-1", symptom: "symptom" },
    evidence: [],
  }
}

function trial(overrides: Partial<EvalTrial> = {}): EvalTrial {
  return {
    target_id: "comfyui-1",
    target_run_id: "run-a",
    trial_id: "trial-1",
    instance_id: "inst-1",
    project_id: "proj-a",
    start_phase: "recon",
    terminal: "stopped",
    copied_at: "2024-01-01T00:00:00+00:00",
    phases: [],
    eval_sha: "sha-x",
    stack_fingerprint: "fp-x",
    verdicts: [],
    diagnoses: [],
    availability: "complete",
    reason: null,
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

const USAGE: ProjectUsage = {
  project_id: "proj-a",
  context_tokens: { cached: 200, uncached: 100 },
  generated_tokens: { reasoning: 50, visible: 150 },
  total_tokens: 500,
  capped_tokens: 300,
  calls: 7,
  by_agent: {
    recon: {
      context_tokens: { cached: 200, uncached: 100 },
      generated_tokens: { reasoning: 50, visible: 150 },
      total_tokens: 500,
      capped_tokens: 300,
      calls: 7,
    },
  },
}

// The eval snapshot and the project usage are separate sources: a route that
// does not name the other endpoints reads as a safely-unavailable section.
function stubEvalFetch(body: EvalSnapshot, usage: unknown = USAGE): void {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith("/snapshot")) {
      return new Response(JSON.stringify(body), { status: 200 })
    }
    if (url.includes("/usage")) {
      return new Response(JSON.stringify(usage), { status: 200 })
    }
    return new Response(
      JSON.stringify({
        status: "unavailable",
        source: null,
        project_id: null,
        captured_at: null,
        fallback_reason: null,
        reason: "not_captured",
        groups: [],
      }),
      { status: 200 },
    )
  }) as typeof fetch
}

function renderTrial(record: EvalTrial, usage: unknown = USAGE) {
  stubEvalFetch(snapshot([record]), usage)
  render(
    <MemoryRouter>
      <EvalDataProvider>
        <TrialSection trial={record} />
      </EvalDataProvider>
    </MemoryRouter>,
  )
}

test("keeps the identified / partial / missed outcome beside the project tokens", async () => {
  renderTrial(
    trial({
      verdicts: [verdict("identified"), verdict("partial"), verdict("missed")],
    }),
  )

  await waitFor(() => expect(screen.getByText("1 identified / 1 partial / 1 missed")).toBeDefined())
  // The project's cumulative total sits in the same summary row.
  await waitFor(() => expect(screen.getByText("Project tokens")).toBeDefined())
  const chip = screen.getByText("Project tokens").closest("li")!
  expect(chip.querySelector("[data-project-tokens]")?.textContent).toBe("500")
})

test("the per-agent breakdown is expandable and states the project scope", async () => {
  renderTrial(trial({ verdicts: [verdict("identified")] }))

  const summary = await screen.findByText("Usage by agent")
  expect(summary.closest("details")?.hasAttribute("open")).toBe(false)

  const row = screen.getByRole("row", { name: /recon/ })
  expect(within(row).getByText("500")).toBeDefined()
  expect(within(row).getByText("200")).toBeDefined()
  expect(within(row).getByText("100")).toBeDefined()
  expect(within(row).getByText("50")).toBeDefined()
  expect(within(row).getByText("150")).toBeDefined()
  expect(within(row).getByText("7")).toBeDefined()
  expect(screen.getByText(/cumulative tokens for this project since the backend started/i)).toBeDefined()
})

test("the trial no longer renders a recorded-spend block", async () => {
  renderTrial(trial({ verdicts: [verdict("identified")] }))

  await waitFor(() => expect(screen.getByText("Project tokens")).toBeDefined())
  expect(screen.queryByText(/Recorded spend/i)).toBeNull()
  expect(screen.queryByText(/Recorded breakdown/i)).toBeNull()
  expect(document.querySelector("[data-spend]")).toBeNull()
})

test("the workspace polls the resolved inventory exactly once", async () => {
  const record = trial()
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    if (url.endsWith("/snapshot")) {
      return new Response(JSON.stringify(snapshot([record])), { status: 200 })
    }
    if (url.includes("/usage")) {
      return new Response(JSON.stringify(USAGE), { status: 200 })
    }
    if (url.endsWith("/resolved-artifacts")) {
      return new Response(
        JSON.stringify({
          status: "available",
          source: "project_storage",
          project_id: "proj-a",
          fallback_reason: null,
          groups: [],
        }),
        { status: 200 },
      )
    }
    return new Response(
      JSON.stringify({
        status: "unavailable",
        source: null,
        project_id: null,
        captured_at: null,
        fallback_reason: null,
        reason: "not_captured",
        groups: [],
      }),
      { status: 200 },
    )
  }) as typeof fetch

  render(
    <MemoryRouter>
      <EvalDataProvider>
        <TrialSection trial={record} />
      </EvalDataProvider>
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getByText("Saved for project")).toBeDefined())
  expect(calls.filter((url) => url.endsWith("/resolved-artifacts"))).toHaveLength(1)
})
