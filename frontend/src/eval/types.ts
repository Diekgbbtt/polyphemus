// The eval read API's `/snapshot` wire shape (#278). Every field is allowlisted
// on the server: no host paths, ground truth, or raw evidence content here.

export interface EvalDataset {
  id: string
  name: string
}

export interface EvalSummary {
  targets: number
  trials: number
  identified: number
  partial: number
  missed: number
  degraded: number
}

export interface EvalTarget {
  target_id: string
  trial_count: number
  identified_count: number
  partial_count: number
  missed_count: number
}

export interface EvalMatched {
  unit: string | null
  fault_class: string | null
  symptom: string | null
}

export type VerdictKind = "identified" | "partial" | "missed"

// One verdict, exactly as the trial carries it. `evidence` holds only the
// sanitized, relative references the server was willing to expose.
export interface EvalVerdict {
  vuln_id: string
  identified: VerdictKind
  confidence: number
  matched: EvalMatched
  evidence: string[]
}

export interface EvalRootCause {
  type: string
  combination_of: string[]
  extended_description: string | null
}

export interface EvalClosestIssue {
  repo: string
  number: number
  title: string
  rationale: string
}

export interface EvalProposedIssue {
  title: string
  labels: string[]
}

export interface EvalDiagnosis {
  vuln: string
  failure_mode: string
  root_cause: EvalRootCause
  diagnosis_overview: string
  closest_issue: EvalClosestIssue | null
  proposed_issue: EvalProposedIssue | null
}

export interface EvalPhase {
  phase: string | null
  status: string | null
  run_id: string | null
}

export type EvalAvailability = "complete" | "degraded"

// The lightweight project-snapshot summaries the dashboard reads from
// `/snapshot`: counts and status only, never inventory entries or graph bodies.
export type ProjectArtifactStatus =
  | "available"
  | "project_artifacts_unavailable"
  | "project_snapshot_unavailable"

export interface ProjectArtifactSummary {
  status: ProjectArtifactStatus
  hunting: number
  skills: number
}

export type ProjectGraphStatus =
  | "available"
  | "project_graph_unavailable"
  | "project_snapshot_unavailable"

export interface ProjectGraphSummary {
  status: ProjectGraphStatus
  nodes: number
  links: number
  captured_at: string | null
}

export interface EvalTrial {
  target_id: string
  target_run_id: string
  trial_id: string
  instance_id: string | null
  project_id: string | null
  start_phase: string | null
  terminal: string | null
  copied_at: string | null
  phases: EvalPhase[]
  eval_sha: string | null
  stack_fingerprint: string | null
  verdicts: EvalVerdict[]
  diagnoses: EvalDiagnosis[]
  availability: EvalAvailability
  reason: string | null
  artifact_summary: ProjectArtifactSummary
  project_graph_summary: ProjectGraphSummary
}

export interface EvalVersionTrial {
  target_id: string
  target_run_id: string
  trial_id: string
  availability: EvalAvailability
  identified: number
  partial: number
  missed: number
}

// A version is ALWAYS the pair (eval_sha, stack_fingerprint): the same eval_sha
// under a different fingerprint is a different version.
export interface EvalVersion {
  eval_sha: string
  stack_fingerprint: string
  targets: string[]
  trial_count: number
  identified: number
  partial: number
  missed: number
  trials: EvalVersionTrial[]
}

export interface EvalSuccess {
  vuln_id: string
  target_id: string
  target_run_id: string
  trial_id: string
  eval_sha: string
  stack_fingerprint: string
  confidence: number
  matched: EvalMatched
}

export interface EvalDegradedTrial {
  target_id: string
  target_run_id: string
  trial_id: string
  reason: string
}

export interface EvalCoverageTargets {
  tested: number
  with_identified: number
  without_identified: number
}

// `partial` is an informational subset of `not_found`, never a third outcome.
export interface EvalCoverageVulnerabilities {
  total: number
  found: number
  not_found: number
  partial: number
}

export interface EvalCoverage {
  targets: EvalCoverageTargets
  vulnerabilities: EvalCoverageVulnerabilities
}

export interface EvalSnapshot {
  dataset: EvalDataset
  summary: EvalSummary
  targets: EvalTarget[]
  trials: EvalTrial[]
  versions: EvalVersion[]
  coverage: EvalCoverage
  successes: EvalSuccess[]
  degraded_trials: EvalDegradedTrial[]
}
