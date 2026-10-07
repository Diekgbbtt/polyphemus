// The eval read API's `/snapshot` wire shape (#278). Every field is allowlisted
// on the server: no host paths, ground truth, or raw evidence content here.

import type { GraphData } from "../api/types"

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

// Where a projected Trial's data came from: the materialized store tree, or
// the authoritative record the harness wrote under a runs root (not yet
// copied). Absent on an older server/fixture and read as `materialized`.
export type TrialStorageSource = "materialized" | "run_record"

export interface ResultsAvailabilityEntry {
  status: "available" | "unavailable"
  reason: string | null
}

// The independent availability of the two results files. A missing file is
// `unavailable`; a present-but-empty file is `available` with no rows. Absent
// on an older server/fixture and read as `available`.
export interface ResultsAvailability {
  verdicts: ResultsAvailabilityEntry
  diagnoses: ResultsAvailabilityEntry
}

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

// The historical project graph one materialized Trial captured. Its `graph` is
// the same `GraphData` contract the live graph uses, but the two sources are
// never mixed.
export interface HistoricalProjectGraph {
  status: "available"
  captured_at: string
  sha256: string
  graph: GraphData
}

export type ProjectArtifactCategory = "hunting" | "skill"

export type ProjectArtifactKind =
  | "hunt_config"
  | "test_spec"
  | "pod_variant"
  | "experiment_log"
  | "pod_export"
  | "skill_procedure"
  | "skill_reference"
  | "skill_script"
  | "skill_asset"

export type ProjectArtifactRepresentation = "yaml" | "markdown" | "text" | "binary"

// Where a resolved artifact came from: `captured` (saved with the Trial, in its
// v1 store or v2 snapshot) or `current` (read from the live project root only).
// Optional: the strict manifest-backed endpoint and older payloads omit it.
export type ProjectArtifactOrigin = "captured" | "current"

// One inventory entry, exactly as the manifest carries it. No host path and no
// source handle ever appears here.
export interface ProjectArtifactEntry {
  artifact_id: string
  category: ProjectArtifactCategory
  kind: ProjectArtifactKind
  relative_path: string
  media_type: string
  size_bytes: number
  sha256: string
  representation: ProjectArtifactRepresentation
  origin?: ProjectArtifactOrigin
}

export interface ProjectArtifactGroup {
  key: string
  label: string
  category: ProjectArtifactCategory
  entries: ProjectArtifactEntry[]
  children: ProjectArtifactGroup[]
}

export interface ProjectArtifactInventory {
  status: "available"
  project_id: string
  groups: ProjectArtifactGroup[]
}

// `parsed` is whatever JSON-safe value the API decoded (object, array, scalar
// or null): never a filesystem handle.
export interface ProjectArtifactPreview {
  text: string | null
  parsed: unknown
  truncated: boolean
  parse_error: string | null
}

export interface ProjectArtifactDetail {
  entry: ProjectArtifactEntry
  preview: ProjectArtifactPreview
  content_url: string
}

// The recorded spend of a finished Trial, read from the harness's authoritative
// record - NOT the live in-memory project ledger (which has no per-run
// attribution and resets with the process). `null` is a missing field; `0` is a
// real value; the overshoot is reported separately and never added to spent.
export interface TrialSpend {
  status: "available" | "unavailable"
  spent_tokens: number | null
  spend_overshoot: number | null
  spend_by_agent: Record<string, Record<string, number>> | null
  reason: string | null
}

export interface EvalTrial {
  target_id: string
  target_run_id: string
  trial_id: string
  // Optional: an older snapshot predates the storage-source metadata.
  storage_source?: TrialStorageSource
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
  // Optional: an older snapshot predates the per-file results availability.
  results_availability?: ResultsAvailability | null
  // The producer's real execution instants (ISO-8601 with an explicit offset).
  // Optional: an older snapshot predates them; a null value has no instant.
  started_at?: string | null
  finished_at?: string | null
  availability: EvalAvailability
  reason: string | null
  artifact_summary: ProjectArtifactSummary
  project_graph_summary: ProjectGraphSummary
  // Optional: an older snapshot predates the recorded-spend block.
  spend?: TrialSpend | null
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

// --- resolved (unified Target -> Trial workspace) ------------------------------

// Which read-only source answered a resolved request. The UI labels these
// `Captured with Trial` and `Saved for project`; schema details never surface.
export type ResolvedSource = "trial_snapshot" | "project_storage"

// A path-free error from one resolved source: the current project storage could
// not be read while the Trial's stored artifacts are still shown. Optional on
// the wire; older server bodies omit it.
export interface ResolvedArtifactIssue {
  source: string
  reason: string
}

export interface ResolvedProjectGraphAvailable {
  status: "available"
  source: ResolvedSource
  project_id: string | null
  captured_at: string | null
  fallback_reason: string | null
  sha256: string | null
  graph: GraphData
}

export interface ResolvedProjectGraphUnavailable {
  status: "unavailable"
  source: ResolvedSource
  project_id: string | null
  captured_at: null
  fallback_reason: string | null
  reason: string
}

export type ResolvedProjectGraph =
  | ResolvedProjectGraphAvailable
  | ResolvedProjectGraphUnavailable

export interface ResolvedArtifactInventoryAvailable {
  status: "available"
  source: ResolvedSource
  project_id: string | null
  fallback_reason: string | null
  groups: ProjectArtifactGroup[]
  issues?: ResolvedArtifactIssue[]
}

export interface ResolvedArtifactInventoryUnavailable {
  status: "unavailable"
  source: ResolvedSource
  project_id: string | null
  fallback_reason: string | null
  reason: string
  groups: []
  issues?: ResolvedArtifactIssue[]
}

export type ResolvedArtifactInventory =
  | ResolvedArtifactInventoryAvailable
  | ResolvedArtifactInventoryUnavailable

// A resolved detail is the same wire shape as the strict one: the content URL
// it carries is already bound to the entry digest.
export type ResolvedArtifactDetail = ProjectArtifactDetail

// A raw project directory no projected Trial proves belongs to this instance.
export interface UnassignedSavedData {
  project_id: string
  status: "available" | "unavailable"
  hunting: number
  skills: number
  reason?: string
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
  // Optional for older fixtures/servers; the current backend always emits it.
  unassigned_saved_data?: UnassignedSavedData[]
  // Path-free catalogue issues (e.g. `run_record_ambiguous`); optional for
  // older fixtures/servers.
  issues?: string[]
}
