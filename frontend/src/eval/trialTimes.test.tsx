import { render } from "@testing-library/react"
import { expect, test } from "vitest"
import {
  FinishedOn,
  StartedOn,
  compareTrialsByStartedAt,
  parseInstant,
} from "./trialTimes"
import type { EvalTrial } from "./types"

function trial(
  overrides: Partial<EvalTrial> & {
    target_id: string
    target_run_id: string
    trial_id: string
  },
): EvalTrial {
  return {
    instance_id: "inst-1",
    project_id: "proj-1",
    start_phase: "recon",
    terminal: "complete",
    copied_at: "2024-01-01T00:00:00+00:00",
    phases: [],
    eval_sha: "sha-1",
    stack_fingerprint: "fp-1",
    verdicts: [],
    diagnoses: [],
    availability: "complete",
    reason: null,
    artifact_summary: { status: "available", hunting: 0, skills: 0 },
    project_graph_summary: { status: "available", nodes: 0, links: 0, captured_at: null },
    ...overrides,
  }
}

test("parseInstant reads aware instants and rejects the rest", () => {
  expect(parseInstant("2024-01-02T00:00:00+00:00")).toBe(
    Date.parse("2024-01-02T00:00:00+00:00"),
  )
  expect(parseInstant(null)).toBeNull()
  expect(parseInstant(undefined)).toBeNull()
  expect(parseInstant("")).toBeNull()
  expect(parseInstant("not-a-date")).toBeNull()
})

test("StartedOn renders a semantic <time> with seconds and a zone", () => {
  const { container } = render(<StartedOn value="2024-01-02T10:30:07+02:00" />)

  const time = container.querySelector("time")
  expect(time?.getAttribute("dateTime")).toBe("2024-01-02T10:30:07+02:00")
  expect(time?.textContent).toMatch(/\d{1,2}:\d{2}:\d{2}/)
  expect(container.textContent).toContain("Started at")
})

test("StartedOn and FinishedOn state a missing instant explicitly", () => {
  const started = render(<StartedOn value={null} />)
  expect(started.container.textContent).toContain("Started at")
  expect(started.container.textContent).toContain("Date unavailable")
  expect(started.container.querySelector("time")).toBeNull()

  const finished = render(<FinishedOn value="not-a-date" />)
  expect(finished.container.textContent).toContain("Finished at")
  expect(finished.container.textContent).toContain("Date unavailable")
})

test("orders by the real instant across offsets, never lexically", () => {
  // 10:00+02:00 is 08:00Z (earlier); 09:00Z is later - the opposite of the
  // lexical string order.
  const earlier = trial({
    target_id: "t",
    target_run_id: "r",
    trial_id: "a",
    started_at: "2024-01-02T10:00:00+02:00",
  })
  const later = trial({
    target_id: "t",
    target_run_id: "r",
    trial_id: "b",
    started_at: "2024-01-02T09:00:00+00:00",
  })

  expect([earlier, later].sort(compareTrialsByStartedAt).map((t) => t.trial_id)).toEqual([
    "b",
    "a",
  ])
})

test("valid starts precede missing ones and ties break on identity", () => {
  const missingZ = trial({ target_id: "t", target_run_id: "r", trial_id: "z", started_at: null })
  const missingA = trial({ target_id: "t", target_run_id: "r", trial_id: "a", started_at: null })
  const same2 = trial({
    target_id: "t",
    target_run_id: "r",
    trial_id: "m2",
    started_at: "2024-01-02T00:00:00+00:00",
  })
  const same1 = trial({
    target_id: "t",
    target_run_id: "r",
    trial_id: "m1",
    started_at: "2024-01-02T00:00:00+00:00",
  })

  const order = [missingZ, same2, missingA, same1]
    .sort(compareTrialsByStartedAt)
    .map((t) => t.trial_id)
  expect(order).toEqual(["m1", "m2", "a", "z"])
})

test("never falls back to copied_at", () => {
  const noStart = trial({
    target_id: "t",
    target_run_id: "r",
    trial_id: "a",
    started_at: null,
    copied_at: "2024-06-01T00:00:00+00:00",
  })
  const started = trial({
    target_id: "t",
    target_run_id: "r",
    trial_id: "b",
    started_at: "2024-01-01T00:00:00+00:00",
    copied_at: "2024-01-01T00:00:00+00:00",
  })

  // A newer copy time must not outrank a real (older) start.
  expect([noStart, started].sort(compareTrialsByStartedAt).map((t) => t.trial_id)).toEqual([
    "b",
    "a",
  ])
})
