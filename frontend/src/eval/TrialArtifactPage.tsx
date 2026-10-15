import type { ReactNode } from "react"
import { Link, useParams } from "react-router-dom"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import type { EvalDiagnosis, EvalTrial, EvalVerdict, VerdictKind } from "./types"

// Must match the id TargetPage puts on each TargetRun group.
function targetRunAnchor(targetRunId: string): string {
  return `targetrun-${targetRunId.replace(/[^A-Za-z0-9_-]/g, "-")}`
}

export const TRIAL_ARTIFACTS = ["manifest", "verdicts", "diagnoses", "evidence"] as const
export type TrialArtifact = (typeof TRIAL_ARTIFACTS)[number]

// The artifact filenames, exactly as the store materializes them.
export const ARTIFACT_LABELS: Record<TrialArtifact, string> = {
  manifest: "run-manifest.yaml",
  verdicts: "verdicts.yaml",
  diagnoses: "diagnoses.yaml",
  evidence: "evidence/",
}

export const ARTIFACT_ORDER: TrialArtifact[] = [...TRIAL_ARTIFACTS]

const PRECEDENCE: Record<VerdictKind, number> = { identified: 3, partial: 2, missed: 1 }

export interface Vulnerability {
  vuln_id: string
  verdict: EvalVerdict
  evidence: string[]
}

// A reference the projection would never emit: absolute, escaping, or a URL.
// Belt and braces - the server already allows only relative, path-safe refs.
function isSafeRef(ref: string): boolean {
  if (!ref || ref.startsWith("/") || ref.includes("\\") || ref.includes("://")) return false
  return !ref.split("/").some((part) => part === "..")
}

// One entry per vulnerability. A vuln repeated within the trial keeps its
// strongest verdict and the union of its OWN safe evidence refs.
export function groupVulnerabilities(trial: EvalTrial): Vulnerability[] {
  const byId = new Map<string, Vulnerability>()
  for (const verdict of trial.verdicts) {
    const refs = verdict.evidence.filter(isSafeRef)
    const existing = byId.get(verdict.vuln_id)
    if (!existing) {
      byId.set(verdict.vuln_id, { vuln_id: verdict.vuln_id, verdict, evidence: [...refs] })
      continue
    }
    if (PRECEDENCE[verdict.identified] > PRECEDENCE[existing.verdict.identified]) {
      existing.verdict = verdict
    }
    for (const ref of refs) {
      if (!existing.evidence.includes(ref)) existing.evidence.push(ref)
    }
  }
  return [...byId.values()]
    .map((entry) => ({ ...entry, evidence: [...entry.evidence].sort() }))
    .sort((a, b) => a.vuln_id.localeCompare(b.vuln_id))
}

function safeRefs(trial: EvalTrial): string[] {
  return [...new Set(groupVulnerabilities(trial).flatMap((entry) => entry.evidence))].sort()
}

function plural(count: number, singular: string, pluralForm?: string): string {
  return `${count} ${count === 1 ? singular : (pluralForm ?? `${singular}s`)}`
}

export type ArtifactStatus = "available" | "empty" | "not-required" | "unavailable"

export interface ArtifactSummary {
  status: ArtifactStatus
  statusLabel: string
  summary: string
}

const STATUS_LABELS: Record<ArtifactStatus, string> = {
  available: "Available",
  empty: "Empty",
  "not-required": "Not required",
  unavailable: "Not materialized",
}

function hasManifest(trial: EvalTrial): boolean {
  return Boolean(
    trial.terminal ||
      trial.start_phase ||
      trial.phases.length > 0 ||
      trial.eval_sha ||
      trial.stack_fingerprint ||
      trial.instance_id ||
      trial.project_id ||
      trial.copied_at,
  )
}

function needingDiagnosis(trial: EvalTrial): number {
  return groupVulnerabilities(trial).filter(
    (entry) => entry.verdict.identified !== "identified",
  ).length
}

// The one place that decides how each artifact is summarized, shared by the
// Trial index and its detail views.
export function summarizeArtifact(trial: EvalTrial, artifact: TrialArtifact): ArtifactSummary {
  switch (artifact) {
    case "manifest": {
      if (!hasManifest(trial)) {
        return {
          status: "unavailable",
          statusLabel: STATUS_LABELS.unavailable,
          summary: "No run-manifest.yaml was materialized for this trial.",
        }
      }
      const version =
        trial.eval_sha && trial.stack_fingerprint
          ? `${trial.eval_sha} · ${trial.stack_fingerprint}`
          : "version not recorded"
      return {
        status: "available",
        statusLabel: STATUS_LABELS.available,
        summary: `terminal ${trial.terminal ?? "—"} · ${plural(trial.phases.length, "phase")} · ${version}`,
      }
    }
    case "verdicts": {
      if (trial.verdicts.length === 0) {
        return {
          status: "unavailable",
          statusLabel: STATUS_LABELS.unavailable,
          summary:
            trial.availability === "degraded"
              ? `No verdicts.yaml was materialized (${trial.reason ?? "unknown"}).`
              : "verdicts.yaml is empty.",
        }
      }
      const counts = { identified: 0, partial: 0, missed: 0 }
      for (const verdict of trial.verdicts) counts[verdict.identified] += 1
      return {
        status: "available",
        statusLabel: STATUS_LABELS.available,
        summary: `${plural(trial.verdicts.length, "verdict row")} · identified ${counts.identified} · partial ${counts.partial} · missed ${counts.missed}`,
      }
    }
    case "diagnoses": {
      const required = needingDiagnosis(trial)
      if (required === 0 && trial.verdicts.length === 0 && trial.availability === "degraded") {
        return {
          status: "unavailable",
          statusLabel: STATUS_LABELS.unavailable,
          summary: `Cannot be determined: verdicts.yaml was not materialized (${trial.reason ?? "unknown"}).`,
        }
      }
      if (required === 0) {
        return {
          status: "not-required",
          statusLabel: STATUS_LABELS["not-required"],
          summary: "Every verdict is identified; no diagnoses are required.",
        }
      }
      if (trial.diagnoses.length === 0) {
        return {
          status: "unavailable",
          statusLabel: STATUS_LABELS.unavailable,
          summary: `${plural(required, "partial/missed vulnerability", "partial/missed vulnerabilities")} need a diagnosis, but none was materialized${
            trial.reason ? ` (${trial.reason})` : ""
          }.`,
        }
      }
      return {
        status: "available",
        statusLabel: STATUS_LABELS.available,
        summary: `${plural(trial.diagnoses.length, "diagnosis", "diagnoses")} · required for ${plural(required, "partial/missed vulnerability", "partial/missed vulnerabilities")}`,
      }
    }
    case "evidence": {
      const refs = safeRefs(trial)
      if (refs.length === 0) {
        return {
          status: "empty",
          statusLabel: STATUS_LABELS.empty,
          summary: "No safe evidence references were materialized.",
        }
      }
      const covered = groupVulnerabilities(trial).filter((entry) => entry.evidence.length > 0).length
      return {
        status: "available",
        statusLabel: STATUS_LABELS.available,
        summary: `${plural(refs.length, "reference")} · covering ${plural(covered, "vulnerability", "vulnerabilities")}`,
      }
    }
  }
}

function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

function MatchList({ verdict }: { verdict: EvalVerdict }) {
  const { unit, fault_class, symptom } = verdict.matched
  return (
    <dl className="eval-match" aria-label={`Match for ${verdict.vuln_id}`}>
      <div>
        <dt>Verdict</dt>
        <dd>{verdict.identified}</dd>
      </div>
      <div>
        <dt>Confidence</dt>
        <dd>{percent(verdict.confidence)}</dd>
      </div>
      <div>
        <dt>Unit</dt>
        <dd>{unit ?? "—"}</dd>
      </div>
      <div>
        <dt>Fault class</dt>
        <dd>{fault_class ?? "—"}</dd>
      </div>
      <div>
        <dt>Symptom</dt>
        <dd>{symptom ?? "—"}</dd>
      </div>
    </dl>
  )
}

function EvidenceList({ refs }: { refs: string[] }) {
  if (refs.length === 0) {
    return <p className="eval-hint">No evidence references were materialized for this vulnerability.</p>
  }
  return (
    <ul className="eval-evidence">
      {refs.map((ref) => (
        <li key={ref}>
          <span className="eval-ref">{ref}</span>
        </li>
      ))}
    </ul>
  )
}

function DiagnosisArticle({ diagnosis }: { diagnosis: EvalDiagnosis }) {
  const cause = diagnosis.root_cause
  return (
    <article className="eval-diagnosis">
      <h3>
        <span className="eval-ref">{diagnosis.vuln}</span> — {diagnosis.failure_mode}
      </h3>
      <p>{diagnosis.diagnosis_overview}</p>
      <p className="eval-diagnosis-cause">
        Root cause: <strong>{cause.type}</strong>
        {cause.combination_of.length > 0 && <> + {cause.combination_of.join(" + ")}</>}
      </p>
      {cause.extended_description && <p>{cause.extended_description}</p>}
      {diagnosis.closest_issue && (
        <p className="eval-diagnosis-issue">
          Closest issue: {diagnosis.closest_issue.repo}#{diagnosis.closest_issue.number} —{" "}
          {diagnosis.closest_issue.title}
        </p>
      )}
      {diagnosis.proposed_issue && (
        <p className="eval-diagnosis-issue">
          Proposed issue: {diagnosis.proposed_issue.title}
          {diagnosis.proposed_issue.labels.length > 0 &&
            ` [${diagnosis.proposed_issue.labels.join(", ")}]`}
        </p>
      )}
    </article>
  )
}

// The artifact's own content. An unavailable, not-required or empty artifact
// renders nothing here: the header's status line already states it plainly.
function ArtifactBody({ trial, artifact }: { trial: EvalTrial; artifact: TrialArtifact }) {
  if (artifact === "manifest") {
    if (!hasManifest(trial)) return null
    const versionPath =
      trial.eval_sha && trial.stack_fingerprint
        ? evalPaths.version(trial.eval_sha, trial.stack_fingerprint)
        : null
    const rows: [string, ReactNode][] = [
      ["Target (machine)", trial.target_id],
      ["TargetRun", trial.target_run_id],
      ["Trial", trial.trial_id],
      ["Availability", trial.availability],
    ]
    if (trial.reason) rows.push(["Reason", trial.reason])
    if (trial.instance_id) rows.push(["Instance", trial.instance_id])
    if (trial.project_id) rows.push(["Project", trial.project_id])
    if (trial.start_phase) rows.push(["Start phase", trial.start_phase])
    if (trial.terminal) rows.push(["Terminal", trial.terminal])
    if (trial.eval_sha) {
      rows.push([
        "eval_sha",
        versionPath ? (
          <Link to={versionPath}>
            <span className="eval-ref">{trial.eval_sha}</span>
          </Link>
        ) : (
          <span className="eval-ref">{trial.eval_sha}</span>
        ),
      ])
    }
    if (trial.stack_fingerprint) {
      rows.push(["stack_fingerprint", <span className="eval-ref">{trial.stack_fingerprint}</span>])
    }
    if (trial.copied_at) rows.push(["Copied at", trial.copied_at])

    return (
      <>
        <dl className="eval-context">
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {trial.phases.length > 0 && (
          <table className="eval-table">
            <caption>Phases</caption>
            <thead>
              <tr>
                <th scope="col">Phase</th>
                <th scope="col">Status</th>
                <th scope="col">Run id</th>
              </tr>
            </thead>
            <tbody>
              {trial.phases.map((phase, index) => (
                <tr key={`${phase.phase}-${index}`}>
                  <th scope="row">{phase.phase ?? "—"}</th>
                  <td>{phase.status ?? "—"}</td>
                  <td>
                    <span className="eval-ref">{phase.run_id ?? "—"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </>
    )
  }

  if (artifact === "verdicts") {
    if (trial.verdicts.length === 0) return null
    // Every materialized row, in order and with its cardinality: two rows that
    // share a vuln_id stay two distinct entries, each with its own verdict,
    // confidence, match and evidence. The row number is a render-time
    // identifier only - the data itself is never modified or merged.
    return (
      <ul className="eval-artifacts">
        {trial.verdicts.map((verdict, index) => (
          <li key={`${verdict.vuln_id}#${index}`} className="eval-artifact-entry">
            <h3>
              <span className="eval-row-index">row {index + 1}</span>
              <span className="eval-ref">{verdict.vuln_id}</span>
              <span className={`eval-badge eval-badge-${verdict.identified}`}>
                {verdict.identified}
              </span>
            </h3>
            <MatchList verdict={verdict} />
            <h4>Evidence</h4>
            <EvidenceList refs={verdict.evidence.filter(isSafeRef)} />
          </li>
        ))}
      </ul>
    )
  }

  if (artifact === "diagnoses") {
    if (trial.diagnoses.length === 0) return null
    return (
      <>
        {trial.diagnoses.map((diagnosis) => (
          <DiagnosisArticle key={diagnosis.vuln} diagnosis={diagnosis} />
        ))}
      </>
    )
  }

  const groups = groupVulnerabilities(trial).filter((entry) => entry.evidence.length > 0)
  if (groups.length === 0) return null
  return (
    <>
      {groups.map((entry) => (
        <section key={entry.vuln_id} aria-label={`Evidence for ${entry.vuln_id}`}>
          <h3>
            <span className="eval-ref">{entry.vuln_id}</span>
          </h3>
          <EvidenceList refs={entry.evidence} />
        </section>
      ))}
    </>
  )
}

// One materialized artifact, rendered as a readable view (never a JSON dump).
export function TrialArtifactPage({ artifact }: { artifact: TrialArtifact }) {
  const { targetId = "", targetRunId = "", trialId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const trial = snapshot.trials.find(
    (item) =>
      item.target_id === targetId &&
      item.target_run_id === targetRunId &&
      item.trial_id === trialId,
  )
  const crumbs = [
    { label: "Eval", to: evalPaths.dashboard },
    { label: snapshot.dataset.name, to: evalPaths.dataset(snapshot.dataset.id) },
    { label: targetId, to: evalPaths.target(targetId) },
    {
      label: targetRunId,
      to: `${evalPaths.target(targetId)}#${targetRunAnchor(targetRunId)}`,
    },
    { label: trialId, to: evalPaths.trial(targetId, targetRunId, trialId) },
    { label: ARTIFACT_LABELS[artifact] },
  ]
  if (!trial) {
    return (
      <div className="eval-page">
        <EvalBreadcrumbs items={crumbs} />
        <p className="eval-empty">Unknown trial “{trialId}”.</p>
      </div>
    )
  }

  const summary = summarizeArtifact(trial, artifact)

  return (
    <div className="eval-page">
      <EvalBreadcrumbs items={crumbs} />
      <header className="eval-header">
        <h1 className="eval-ref">{ARTIFACT_LABELS[artifact]}</h1>
        <p className="eval-dataset-id">
          Trial <span className="eval-ref">{trial.trial_id}</span> · Target (machine){" "}
          {trial.target_id} · TargetRun {trial.target_run_id}
        </p>
        <p className="eval-artifact-summary">
          <span className="eval-artifact-status">{summary.statusLabel}</span> {summary.summary}
        </p>
      </header>

      <ArtifactBody trial={trial} artifact={artifact} />
    </div>
  )
}
