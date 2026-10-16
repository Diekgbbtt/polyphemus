import type { ProjectState } from "./api/types"

// The three run classes the platform expresses, in display order.
export const RUN_KINDS = ["recon", "analysis", "hunting"] as const
export type RunKind = (typeof RUN_KINDS)[number]

// One normalized run row: every run class has its own id field and only recon
// carries a liveness verdict, so the views read this shape, not three.
export interface RunRow {
  id: string
  status: string
  liveness: "live" | "stalled" | null
  phase: number | null
}

// The active runs of one project, grouped by class. A class with no runs is
// dropped entirely so a project shows only what is actually executing.
export function activeRuns(project: ProjectState, kind: RunKind): RunRow[] {
  if (kind === "recon") {
    return project.recon.map((run) => ({
      id: run.run_id,
      status: run.status,
      liveness: run.liveness,
      phase: run.current_phase,
    }))
  }
  if (kind === "analysis") {
    return project.analysis.map((run) => ({
      id: run.analysis_run_id,
      status: run.status,
      liveness: null,
      phase: null,
    }))
  }
  return project.hunting.map((run) => ({
    id: run.hunting_run_id,
    status: run.status,
    liveness: null,
    phase: null,
  }))
}
