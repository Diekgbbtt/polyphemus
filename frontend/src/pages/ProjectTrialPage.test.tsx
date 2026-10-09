import { render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, expect, test } from "vitest"
import { App } from "../App"
import type { ProjectUsage } from "../api/types"
import type { EvalSnapshot, EvalTrial, EvalVerdict } from "../eval/types"

afterEach(() => {
  window.history.pushState({}, "", "/")
})

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

function verdict(identified: EvalVerdict["identified"]): EvalVerdict {
  return {
    vuln_id: `${identified}-1`,
    identified,
    confidence: 0.5,
    matched: { unit: "unit", fault_class: "CWE-1", symptom: "symptom" },
    evidence: [],
  }
}

const TRIAL: EvalTrial = {
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
  verdicts: [verdict("identified"), verdict("partial"), verdict("missed")],
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
}

const SNAPSHOT: EvalSnapshot = {
  dataset: { id: "webexploitbench", name: "WebExploitBench" },
  summary: { targets: 1, trials: 1, identified: 1, partial: 1, missed: 1, degraded: 0 },
  targets: [],
  trials: [TRIAL],
  versions: [],
  coverage: {
    targets: { tested: 0, with_identified: 0, without_identified: 0 },
    vulnerabilities: { total: 0, found: 0, not_found: 0, partial: 0 },
  },
  successes: [],
  degraded_trials: [],
}

const UNAVAILABLE_SECTION = {
  status: "unavailable",
  source: null,
  project_id: null,
  captured_at: null,
  fallback_reason: null,
  reason: "not_captured",
  groups: [],
}

function stub(): void {
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    const body = url.endsWith("/snapshot")
      ? SNAPSHOT
      : url.includes("/usage")
        ? USAGE
        : UNAVAILABLE_SECTION
    return new Response(JSON.stringify(body), { status: 200 })
  }) as typeof fetch
}

function goto(path: string): void {
  stub()
  window.history.pushState({}, "", path)
  render(<App />)
}

async function trialSection(): Promise<HTMLElement> {
  const section = await screen.findByRole("region", { name: "Trial trial-1" })
  return section
}

test("the compatible project Trial view shows project tokens beside the outcome", async () => {
  goto("/p/proj-a/evals/comfyui-1/run-a/trial-1")
  const section = await trialSection()

  expect(within(section).getByText("1 identified / 1 partial / 1 missed")).toBeDefined()
  await waitFor(() => expect(within(section).getByText("Project tokens")).toBeDefined())
  expect(document.querySelector("[data-project-tokens]")?.textContent).toBe("500")
  expect(within(section).getByText("Usage by agent")).toBeDefined()
})

test("the canonical Trial view shows the same project tokens", async () => {
  goto("/targets/comfyui-1/trials/run-a/trial-1")
  const section = await trialSection()

  expect(within(section).getByText("1 identified / 1 partial / 1 missed")).toBeDefined()
  await waitFor(() => expect(within(section).getByText("Project tokens")).toBeDefined())
  expect(document.querySelector("[data-project-tokens]")?.textContent).toBe("500")
})

test("neither Trial view renders a recorded-spend block", async () => {
  goto("/p/proj-a/evals/comfyui-1/run-a/trial-1")
  await trialSection()

  expect(screen.queryByText(/Recorded spend/i)).toBeNull()
  expect(screen.queryByText(/Recorded breakdown/i)).toBeNull()
  expect(document.querySelector("[data-spend]")).toBeNull()
})
