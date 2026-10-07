import type { EvalTrial } from "./types"

// One Trial's results availability, tolerant of an older server/fixture that
// predates the metadata: an absent field reads as `available`, so no result is
// ever hidden behind a missing key. The two files are always independent.

export function verdictsAvailable(trial: EvalTrial): boolean {
  return trial.results_availability?.verdicts?.status !== "unavailable"
}

export function diagnosesAvailable(trial: EvalTrial): boolean {
  return trial.results_availability?.diagnoses?.status !== "unavailable"
}

export function resultsReason(
  trial: EvalTrial,
  which: "verdicts" | "diagnoses",
): string | null {
  return trial.results_availability?.[which]?.reason ?? null
}

// Whether the Trial was copied into the materialized store. Absent metadata
// reads as materialized, preserving the previous rendering exactly.
export function isMaterialized(trial: EvalTrial): boolean {
  return (trial.storage_source ?? "materialized") === "materialized"
}

// The hunting phase really recorded a timeout. A Trial-level `terminal:
// timeout` alone never claims the hunting phase timed out.
export function timeoutDuringHunting(trial: EvalTrial): boolean {
  return trial.phases.some(
    (phase) => phase.phase === "hunting" && phase.status === "timeout",
  )
}
