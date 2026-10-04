import type { ReactNode } from "react"
import type { EvalDiagnosis, EvalTrial, EvalVerdict } from "./types"

// One Trial's results: every materialized verdict as its own row, with the
// diagnoses that name the same vulnerability paired beneath it. The
// presentation is pure - it never modifies the wire data, merges rows, or
// fabricates a diagnosis that was not materialized.

// A reference the projection would never emit: absolute, escaping, or a URL.
// Belt and braces - the server already allows only relative, path-safe refs.
export function isSafeRef(ref: string): boolean {
  if (!ref || ref.startsWith("/") || ref.includes("\\") || ref.includes("://")) return false
  return !ref.split("/").some((part) => part === "..")
}

function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

export function MatchList({ verdict }: { verdict: EvalVerdict }) {
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

export function EvidenceList({ refs }: { refs: string[] }) {
  if (refs.length === 0) {
    return (
      <p className="eval-hint">
        No evidence references were materialized for this vulnerability.
      </p>
    )
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

export function DiagnosisArticle({ diagnosis }: { diagnosis: EvalDiagnosis }) {
  const cause = diagnosis.root_cause
  return (
    <article className="eval-diagnosis">
      <h4>
        <span className="eval-ref">{diagnosis.vuln}</span> — {diagnosis.failure_mode}
      </h4>
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

// Every verdict, in order and with its cardinality: two rows that share a
// vuln_id stay two distinct entries. Only a partial or missed row may be
// missing a diagnosis, and that is stated rather than filled in.
export function VerdictList({ trial }: { trial: EvalTrial }) {
  if (trial.verdicts.length === 0) return null
  return (
    <ul className="eval-artifacts">
      {trial.verdicts.map((verdict, index) => {
        const paired = trial.diagnoses.filter((d) => d.vuln === verdict.vuln_id)
        const needsDiagnosis = verdict.identified !== "identified"
        return (
          <li
            key={`${verdict.vuln_id}#${index}`}
            className="eval-artifact-entry trial-result-row"
          >
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
            {(paired.length > 0 || needsDiagnosis) && <h4>Diagnosis</h4>}
            {paired.map((diagnosis) => (
              <DiagnosisArticle key={`${diagnosis.vuln}-${diagnosis.failure_mode}`} diagnosis={diagnosis} />
            ))}
            {paired.length === 0 && needsDiagnosis && (
              <p className="eval-hint">
                No diagnosis was materialized for this {verdict.identified} result.
              </p>
            )}
          </li>
        )
      })}
    </ul>
  )
}

// The diagnoses artifact view: every materialized diagnosis, including any that
// names a vulnerability with no verdict row.
export function DiagnosesView({ trial }: { trial: EvalTrial }) {
  if (trial.diagnoses.length === 0) return null
  return (
    <>
      {trial.diagnoses.map((diagnosis) => (
        <DiagnosisArticle
          key={`${diagnosis.vuln}-${diagnosis.failure_mode}`}
          diagnosis={diagnosis}
        />
      ))}
    </>
  )
}

function UnmatchedDiagnoses({ trial }: { trial: EvalTrial }) {
  const verdictVulns = new Set(trial.verdicts.map((verdict) => verdict.vuln_id))
  const unmatched = trial.diagnoses.filter((diagnosis) => !verdictVulns.has(diagnosis.vuln))
  if (unmatched.length === 0) return null
  return (
    <section aria-label="Unmatched diagnoses" className="trial-results-unmatched">
      <h3>Unmatched diagnoses</h3>
      <p className="eval-hint">
        These diagnoses name a vulnerability with no materialized verdict in this
        Trial.
      </p>
      {unmatched.map((diagnosis) => (
        <DiagnosisArticle
          key={`${diagnosis.vuln}-${diagnosis.failure_mode}`}
          diagnosis={diagnosis}
        />
      ))}
    </section>
  )
}

// The reusable results section: the same presentation the canonical Trial
// workspace and the materialized verdicts/diagnoses views share.
export function TrialResults({ trial }: { trial: EvalTrial }) {
  const empty = trial.verdicts.length === 0 && trial.diagnoses.length === 0
  return (
    <section aria-label="Trial results" className="trial-results">
      <h2>Results</h2>
      {empty ? (
        <p className="eval-empty">No results were materialized for this Trial.</p>
      ) : (
        <VerdictList trial={trial} />
      )}
      <UnmatchedDiagnoses trial={trial} />
    </section>
  )
}

export type { ReactNode }
