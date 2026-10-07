import { render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { EvalDataProvider } from "./EvalDataProvider"
import { TrialSection } from "./TrialSection"
import type { EvalSnapshot, EvalTrial, TrialSpend } from "./types"

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

function stubEvalFetch(body: EvalSnapshot): void {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith("/snapshot")) {
      return new Response(JSON.stringify(body), { status: 200 })
    }
    // Every other section is a separate, safely-unavailable source.
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

function renderTrial(spend: TrialSpend | undefined) {
  const record = trial(spend === undefined ? {} : { spend })
  stubEvalFetch(snapshot([record]))
  render(
    <MemoryRouter>
      <EvalDataProvider>
        <TrialSection trial={record} />
      </EvalDataProvider>
    </MemoryRouter>,
  )
}

function spendCell(field: "spent" | "overshoot"): HTMLElement {
  const cell = document.querySelector(`[data-spend="${field}"]`)
  if (!cell) throw new Error(`no spend cell ${field}`)
  return cell as HTMLElement
}

test("shows recorded consumption, overshoot and the per-agent breakdown", async () => {
  renderTrial({
    status: "available",
    spent_tokens: 500,
    spend_overshoot: 200,
    spend_by_agent: { recon: { total_tokens: 1500, calls: 4 } },
    reason: null,
  })

  await waitFor(() => expect(spendCell("spent").textContent).toBe("500"))
  // The overshoot is reported separately and never folded into the total.
  expect(spendCell("spent").textContent).not.toBe("700")
  expect(spendCell("overshoot").textContent).toBe("200")
  const row = screen.getByRole("row", { name: /recon/ })
  expect(within(row).getByText("1500")).toBeDefined()
})

test("zero is a value, not a missing field", async () => {
  renderTrial({
    status: "available",
    spent_tokens: 0,
    spend_overshoot: 0,
    spend_by_agent: null,
    reason: null,
  })

  await waitFor(() => expect(spendCell("spent").textContent).toBe("0"))
  expect(spendCell("overshoot").textContent).toBe("0")
})

test("a missing field is shown as Unavailable while zero stays zero", async () => {
  renderTrial({
    status: "available",
    spent_tokens: null,
    spend_overshoot: 0,
    spend_by_agent: null,
    reason: null,
  })

  await waitFor(() => expect(spendCell("spent").textContent).toBe("Unavailable"))
  expect(spendCell("overshoot").textContent).toBe("0")
})

test("an unavailable spend block is Unavailable", async () => {
  renderTrial({
    status: "unavailable",
    spent_tokens: null,
    spend_overshoot: null,
    spend_by_agent: null,
    reason: "spend_record_not_found",
  })

  await waitFor(() => expect(spendCell("spent").textContent).toBe("Unavailable"))
  expect(spendCell("overshoot").textContent).toBe("Unavailable")
})

test("a trial with no spend block at all is Unavailable", async () => {
  renderTrial(undefined)

  await waitFor(() => expect(spendCell("spent").textContent).toBe("Unavailable"))
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
