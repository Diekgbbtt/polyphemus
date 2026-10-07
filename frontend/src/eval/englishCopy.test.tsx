import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, expect, test, vi } from "vitest"
import { EvalDataProvider } from "./EvalDataProvider"
import { EvalRefreshControls } from "./EvalRefreshControls"
import { GROUND_TRUTH_FALLBACK } from "./operatorGroundTruth"
import { SavedOn } from "./SavedOn"
import { StartedOn } from "./trialTimes"
import { TrialResults } from "./TrialResults"
import type { EvalSnapshot, EvalTrial } from "./types"

afterEach(() => {
  vi.unstubAllEnvs()
})

const SNAPSHOT: EvalSnapshot = {
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

test("the ground-truth fallback text is English", () => {
  expect(GROUND_TRUTH_FALLBACK).toBe("Ground truth unavailable")
})

test("dates render in en-GB on the reader's clock and keep the machine value", () => {
  vi.stubEnv("TZ", "UTC")

  const saved = render(<SavedOn copiedAt="2024-01-02T08:30:00Z" />)
  const savedTime = saved.container.querySelector("time")
  // en-GB is day-first and 24-hour (en-US would be "Jan 2, 2024, 08:30 AM UTC").
  expect(savedTime?.textContent).toMatch(/2 Jan 2024/)
  expect(savedTime?.textContent).not.toMatch(/Jan 2, 2024/)
  expect(savedTime?.textContent).toMatch(/08:30/)
  expect(savedTime?.textContent).toMatch(/UTC/)
  expect(savedTime?.getAttribute("dateTime")).toBe("2024-01-02T08:30:00Z")

  const started = render(<StartedOn value="2024-01-02T10:30:07+02:00" />)
  const startedTime = started.container.querySelector("time")
  expect(startedTime?.textContent).toMatch(/2 Jan 2024/)
  expect(startedTime?.textContent).toMatch(/08:30:07/)
  // The original offset-bearing value stays in `dateTime`, unchanged.
  expect(startedTime?.getAttribute("dateTime")).toBe("2024-01-02T10:30:07+02:00")
})

test("the refresh control's accessible name matches its visible English text", async () => {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(SNAPSHOT), { status: 200 })) as typeof fetch

  render(
    <EvalDataProvider>
      <EvalRefreshControls />
    </EvalDataProvider>,
  )

  const button = await screen.findByRole("button", { name: "Refresh" })
  expect(button.textContent).toBe("Refresh")
  await waitFor(() => expect(screen.getByText(/Last updated/)).toBeDefined())
})

test("stored Italian content is rendered verbatim, never translated", async () => {
  const trial: EvalTrial = {
    target_id: "t",
    target_run_id: "r",
    trial_id: "trial-1",
    instance_id: "i",
    project_id: "p",
    start_phase: "recon",
    terminal: "complete",
    copied_at: "2024-01-01T00:00:00+00:00",
    started_at: "2024-01-01T00:00:00+00:00",
    finished_at: "2024-01-01T01:00:00+00:00",
    phases: [],
    eval_sha: "s",
    stack_fingerprint: "f",
    verdicts: [
      {
        vuln_id: "IT-1",
        identified: "identified",
        confidence: 0.9,
        matched: {
          unit: "servizio.italiano",
          fault_class: "classe.difetto",
          symptom: "sintomo.italiano",
        },
        evidence: [],
      },
    ],
    diagnoses: [
      {
        vuln: "IT-2",
        failure_mode: "modalità.guasto",
        root_cause: {
          type: "tipo.causa",
          combination_of: [],
          extended_description: "descrizione estesa",
        },
        diagnosis_overview: "panoramica diagnosi",
        closest_issue: {
          repo: "org/repo",
          number: 1,
          title: "titolo",
          rationale: "motivazione",
        },
        proposed_issue: null,
      },
    ],
    availability: "complete",
    reason: null,
    artifact_summary: { status: "available", hunting: 0, skills: 0 },
    project_graph_summary: { status: "available", nodes: 0, links: 0, captured_at: null },
  }

  render(
    <MemoryRouter>
      <TrialResults trial={trial} />
    </MemoryRouter>,
  )

  // The unmatched diagnosis (stored data) shows its Italian overview verbatim.
  expect(screen.getByText("panoramica diagnosi")).toBeDefined()

  // The verdict row's stored match values are shown unchanged once expanded.
  fireEvent.click(screen.getByRole("button", { name: /row 1/ }))
  await waitFor(() => expect(screen.getByText("servizio.italiano")).toBeDefined())
  expect(screen.getByText("classe.difetto")).toBeDefined()
  expect(screen.getByText("sintomo.italiano")).toBeDefined()
})
