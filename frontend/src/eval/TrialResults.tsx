import { useCallback, useState } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { targetPaths } from "../projectPaths"
import {
  GROUND_TRUTH_FALLBACK,
  type GroundTruthState,
} from "./operatorGroundTruth"
import { useEvidenceResolver } from "./ResolvedArtifactsProvider"
import { isSafeEvidenceReference } from "./projectArtifacts"
import type { EvidenceResolution } from "./projectArtifacts"
import { diagnosesAvailable, resultsReason, verdictsAvailable } from "./trialAvailability"
import type { EvalDiagnosis, EvalTrial, EvalVerdict } from "./types"

// One Trial's results: every materialized verdict as its own row, with the
// diagnoses that name the same vulnerability paired beneath it. The
// presentation is pure - it never modifies the wire data, merges rows, or
// fabricates a diagnosis that was not materialized.

// A reference the projection would never emit: absolute, escaping, or a URL.
// Belt and braces - the server already allows only relative, path-safe refs.
export function isSafeRef(ref: string): boolean {
  return isSafeEvidenceReference(ref)
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

// One verdict's evidence references. When the shared instrument is available a
// reference that resolves to exactly one artifact becomes a link to that
// artifact's detail route; the original reference stays the link text. A safe
// reference with no match is stated as unavailable, one still loading is stated
// as pending, and every other shape stays plain text. Callers without an
// inventory (the materialized artifact views) pass no resolver and get exactly
// the previous plain-text rendering.
export function EvidenceList({
  refs,
  resolve,
  detailPath,
}: {
  refs: string[]
  resolve?: (reference: string) => EvidenceResolution
  detailPath?: (artifactId: string) => string
}) {
  if (refs.length === 0) {
    return (
      <p className="eval-hint">
        No evidence references were materialized for this vulnerability.
      </p>
    )
  }
  return (
    <ul className="eval-evidence">
      {refs.map((ref) => {
        const resolution: EvidenceResolution = resolve ? resolve(ref) : { kind: "plain" }
        if (resolution.kind === "linked" && detailPath) {
          return (
            <li key={ref}>
              <Link to={detailPath(resolution.artifact_id)} className="eval-ref">
                {ref}
              </Link>
            </li>
          )
        }
        return (
          <li key={ref}>
            <span className="eval-ref">{ref}</span>
            {resolution.kind === "loading" && (
              <span className="eval-hint"> Verifica artifact in corso</span>
            )}
            {resolution.kind === "missing" && (
              <span className="eval-hint"> Artifact non disponibile</span>
            )}
          </li>
        )
      })}
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

// The operator's reference for one verdict row, matched by exact `vuln_id`.
//
// It is labelled as the *current* benchmark checkout: it was not captured with
// the Trial and may have changed since. A missing entry, an unavailable API, or
// a still-loading one never removes anything from the row - the materialized
// verdict, match and evidence stay exactly as they are.
function GroundTruthSection({
  vulnId,
  state,
}: {
  vulnId: string
  state: GroundTruthState
}) {
  const entry =
    state.status === "ready"
      ? state.data.vulnerabilities.find((item) => item.vuln_id === vulnId)
      : undefined
  return (
    <div className="trial-ground-truth">
      <h4>Ground truth (current benchmark)</h4>
      {state.status === "loading" ? (
        <p className="eval-hint">Loading ground truth…</p>
      ) : entry ? (
        <dl className="eval-match eval-ground-truth" aria-label={`Ground truth for ${vulnId}`}>
          <div>
            <dt>Location</dt>
            <dd>{entry.location}</dd>
          </div>
          <div>
            <dt>Vulnerability type</dt>
            <dd>{entry.type}</dd>
          </div>
          <div>
            <dt>Scoring signals</dt>
            <dd>{entry.scoring.length > 0 ? entry.scoring.join(", ") : "—"}</dd>
          </div>
        </dl>
      ) : (
        <p className="eval-hint">{GROUND_TRUTH_FALLBACK}</p>
      )}
    </div>
  )
}

const NO_OPEN_ROWS: ReadonlySet<string> = new Set()

// A stable, unique DOM id for one row's body. It is derived only from the row's
// stable `vuln_id#index` key - never from a label, an index alone, or a digest -
// and stays valid for vuln_ids that carry spaces or punctuation. Two rows that
// share a vuln_id resolve to two distinct keys, hence two distinct ids.
export function resultRowDomId(key: string): string {
  const slug = key
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
  let hash = 5381
  for (let index = 0; index < key.length; index += 1) {
    hash = ((hash << 5) + hash + key.charCodeAt(index)) >>> 0
  }
  return `result-row-${slug || "row"}-${hash.toString(36)}`
}

// Rows start closed. The open set is keyed by each row's stable `vuln_id#index`
// key, so a poll that recreates the same Trial keeps the reader's choices, a
// brand-new result starts closed, and two rows that share a vuln_id toggle
// independently. A change of Trial identity (target, target_run or trial -
// never project_id alone) resets the set synchronously during render, so the
// very first committed render of the new Trial already has every row closed and
// no effect is needed to hide the previous Trial's state.
function useOpenResultRows(identity: string) {
  const [state, setState] = useState<{ identity: string; open: ReadonlySet<string> }>(
    () => ({ identity, open: NO_OPEN_ROWS }),
  )
  if (state.identity !== identity) {
    setState({ identity, open: NO_OPEN_ROWS })
  }
  const open = state.identity === identity ? state.open : NO_OPEN_ROWS
  const toggle = useCallback(
    (key: string) => {
      setState((previous) => {
        const base = previous.identity === identity ? previous.open : NO_OPEN_ROWS
        const next = new Set(base)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return { identity, open: next }
      })
    },
    [identity],
  )
  return { open, toggle }
}

// One verdict row: the header stays visible (caret, row N, vuln_id, verdict and
// confidence) while the body holds exactly the presentation it always did. The
// body stays mounted but `hidden`, so a closed row keeps its ids and its state
// while none of its links remain focusable.
function VerdictRow({
  verdict,
  index,
  groundTruth,
  paired,
  open,
  onToggle,
  resolveEvidence,
  detailPath,
}: {
  verdict: EvalVerdict
  index: number
  groundTruth?: GroundTruthState
  paired: EvalDiagnosis[]
  open: boolean
  onToggle: () => void
  resolveEvidence: (reference: string) => EvidenceResolution
  detailPath: (artifactId: string) => string
}) {
  const bodyId = resultRowDomId(`${verdict.vuln_id}#${index}`)
  const needsDiagnosis = verdict.identified !== "identified"
  return (
    <li className="eval-artifact-entry trial-result-row">
      <h3 className="eval-result-head">
        <button
          type="button"
          className="eval-result-toggle"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={`row ${index + 1}, ${verdict.vuln_id}, ${verdict.identified}, ${percent(
            verdict.confidence,
          )}`}
          onClick={onToggle}
          onKeyDown={(event) => {
            // A native button activates on Enter/Space; own it here so the
            // control also works under jsdom and never toggles twice.
            if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
              event.preventDefault()
              onToggle()
            }
          }}
        >
          <span className="eval-result-caret" aria-hidden="true">
            {open ? "▾" : "▸"}
          </span>
          <span className="eval-row-index">row {index + 1}</span>
          <span className="eval-ref">{verdict.vuln_id}</span>
          <span className={`eval-badge eval-badge-${verdict.identified}`}>
            {verdict.identified}
          </span>
          <span className="eval-result-confidence">{percent(verdict.confidence)}</span>
        </button>
      </h3>
      <div id={bodyId} className="eval-result-body" hidden={!open}>
        <MatchList verdict={verdict} />
        {groundTruth && (
          <GroundTruthSection vulnId={verdict.vuln_id} state={groundTruth} />
        )}
        <h4>Evidence</h4>
        <EvidenceList
          refs={verdict.evidence.filter(isSafeRef)}
          resolve={resolveEvidence}
          detailPath={detailPath}
        />
        {(paired.length > 0 || needsDiagnosis) && <h4>Diagnosis</h4>}
        {paired.map((diagnosis) => (
          <DiagnosisArticle
            key={`${diagnosis.vuln}-${diagnosis.failure_mode}`}
            diagnosis={diagnosis}
          />
        ))}
        {paired.length === 0 && needsDiagnosis && (
          <p className="eval-hint">
            No diagnosis was materialized for this {verdict.identified} result.
          </p>
        )}
      </div>
    </li>
  )
}

// Every verdict, in order and with its cardinality: two rows that share a
// vuln_id stay two distinct entries. Only a partial or missed row may be
// missing a diagnosis, and that is stated rather than filled in. Each row is
// collapsible; it starts closed and keeps its own open state.
export function VerdictList({
  trial,
  groundTruth,
}: {
  trial: EvalTrial
  groundTruth?: GroundTruthState
}) {
  // One shared artifact index for the whole list: the link target is the
  // canonical Trial artifact route, never another Trial or project.
  const resolveEvidence = useEvidenceResolver(trial.project_id)
  const artifactDetailPath = (artifactId: string) =>
    targetPaths.trialArtifact(trial.target_id, trial.target_run_id, trial.trial_id, artifactId)
  // target + target_run + trial - never project_id alone: two Trials can share a
  // project and must still reset independently.
  const identity = `${trial.target_id}\u0000${trial.target_run_id}\u0000${trial.trial_id}`
  const { open, toggle } = useOpenResultRows(identity)

  if (trial.verdicts.length === 0) return null
  return (
    <ul className="eval-artifacts">
      {trial.verdicts.map((verdict, index) => {
        const key = `${verdict.vuln_id}#${index}`
        return (
          <VerdictRow
            key={key}
            verdict={verdict}
            index={index}
            groundTruth={groundTruth}
            paired={trial.diagnoses.filter((d) => d.vuln === verdict.vuln_id)}
            open={open.has(key)}
            onToggle={() => toggle(key)}
            resolveEvidence={resolveEvidence}
            detailPath={artifactDetailPath}
          />
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
export function TrialResults({
  trial,
  groundTruth,
}: {
  trial: EvalTrial
  groundTruth?: GroundTruthState
}) {
  const noVerdicts = !verdictsAvailable(trial)
  const noDiagnoses = !diagnosesAvailable(trial)
  const empty = trial.verdicts.length === 0 && trial.diagnoses.length === 0
  return (
    <section aria-label="Trial results" className="trial-results">
      <h2>Results</h2>
      {/* The two files are independent: a missing verdicts.yaml must not hide a
          present diagnoses.yaml, and neither is a synthetic zero. */}
      {noVerdicts && (
        <p className="eval-notice-line" data-availability="verdicts">
          Verdicts non disponibili
          {resultsReason(trial, "verdicts")
            ? ` (${resultsReason(trial, "verdicts")})`
            : ""}
          .
        </p>
      )}
      {noDiagnoses && (
        <p className="eval-notice-line" data-availability="diagnoses">
          Diagnoses non disponibili
          {resultsReason(trial, "diagnoses")
            ? ` (${resultsReason(trial, "diagnoses")})`
            : ""}
          .
        </p>
      )}
      {empty && !noVerdicts && !noDiagnoses ? (
        <p className="eval-empty">No results were materialized for this Trial.</p>
      ) : (
        <VerdictList trial={trial} groundTruth={groundTruth} />
      )}
      <UnmatchedDiagnoses trial={trial} />
    </section>
  )
}

export type { ReactNode }
