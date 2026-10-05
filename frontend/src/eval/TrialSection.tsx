import { Link } from "react-router-dom"
import { targetPaths } from "../projectPaths"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import { useOperatorGroundTruth } from "./operatorGroundTruth"
import { ResolvedArtifactsProvider } from "./ResolvedArtifactsProvider"
import { ResolvedArtifactsSection } from "./ResolvedArtifactsSection"
import { SavedOn } from "./SavedOn"
import { TrialProjectGraph } from "./TrialProjectGraph"
import { TrialResults } from "./TrialResults"
import { ARTIFACT_LABELS, ARTIFACT_ORDER, summarizeArtifact } from "./TrialArtifactPage"
import type { EvalTrial } from "./types"

// A stable DOM anchor for one Trial, keyed by the full (run, trial) identity so
// two Targets or TargetRuns that reuse a trial id never collide.
export function trialAnchor(targetRunId: string, trialId: string): string {
  const safe = (value: string) => value.replace(/[^A-Za-z0-9_-]/g, "-")
  return `trial-${safe(targetRunId)}-${safe(trialId)}`
}

function outcomeCounts(trial: EvalTrial): { identified: number; partial: number; missed: number } {
  const counts = { identified: 0, partial: 0, missed: 0 }
  for (const verdict of trial.verdicts) counts[verdict.identified] += 1
  return counts
}

function phasesLabel(trial: EvalTrial): string {
  const phases = trial.phases
    .map((phase) => (phase.phase ? `${phase.phase} ${phase.status}` : ""))
    .filter(Boolean)
  return phases.length > 0 ? phases.join(" → ") : "—"
}

// Kept as a re-export for callers that still import the timestamp from here;
// the component itself now lives in its own module.
export { SavedOn }

// The one "not available" string the recorded-spend block uses; a missing field
// and an unavailable association read the same to an operator.
const SPEND_MISSING = "non disponibile"

// One Trial's RECORDED spend, read from the harness's authoritative record.
//
// This is distinct from the live runs page: the live page shows the app's
// cumulative, per-project, in-memory usage; this block shows what the finished
// Trial actually recorded against its budget. `spent_tokens` is the recorded
// consumption, `spend_overshoot` is the tokens spent past the bound (reported
// separately and never added to the total), and `spend_by_agent` is the
// recorded breakdown. Zero is shown as zero; a missing field is "non
// disponibile", so the two are never confused.
function RecordedSpend({ trial }: { trial: EvalTrial }) {
  const spend = trial.spend
  const available = spend?.status === "available"
  const value = (raw: number | null | undefined): string =>
    available && typeof raw === "number" ? String(raw) : SPEND_MISSING
  const agents = available && spend?.spend_by_agent ? Object.entries(spend.spend_by_agent) : []

  return (
    <section className="eval-spend" aria-label="Recorded spend">
      <h2>Recorded spend</h2>
      <dl className="eval-spend-totals">
        <div>
          <dt>Consumo registrato</dt>
          <dd data-spend="spent">{value(spend?.spent_tokens)}</dd>
        </div>
        <div>
          <dt>Sforamento</dt>
          <dd data-spend="overshoot">{value(spend?.spend_overshoot)}</dd>
        </div>
      </dl>
      {agents.length > 0 ? (
        <table className="eval-spend-agents">
          <caption>Breakdown registrato</caption>
          <thead>
            <tr>
              <th scope="col">Agente</th>
              <th scope="col">Token</th>
            </tr>
          </thead>
          <tbody>
            {agents
              .slice()
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([agent, entry]) => (
                <tr key={agent}>
                  <th scope="row">{agent}</th>
                  <td>{entry.total_tokens ?? SPEND_MISSING}</td>
                </tr>
              ))}
          </tbody>
        </table>
      ) : (
        <p className="eval-spend-unavailable">Breakdown registrato: {SPEND_MISSING}</p>
      )}
    </section>
  )
}

// The materialized-artifact index. It lists the four files the store wrote and
// links each to its own readable view; it never loads their contents.
function MaterializedArtifacts({ trial }: { trial: EvalTrial }) {
  return (
    <section aria-label="Artifacts">
      <h2>Materialized artifacts</h2>
      <ul className="eval-artifacts">
        {ARTIFACT_ORDER.map((artifact) => {
          const summary = summarizeArtifact(trial, artifact)
          return (
            <li key={artifact}>
              <Link
                to={evalPaths.trialArtifact(
                  trial.target_id,
                  trial.target_run_id,
                  trial.trial_id,
                  artifact,
                )}
              >
                <span className="eval-ref">{ARTIFACT_LABELS[artifact]}</span>
              </Link>
              <span className="eval-artifact-status">{summary.statusLabel}</span>
              <p className="eval-artifact-summary">{summary.summary}</p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

// One Trial inside a Target workspace.
//
// Every Trial is the same continuous workspace regardless of the schema it was
// captured under: its identity and phase sequence, its results and diagnoses,
// its resolved L0/L1 graph, and its resolved Hunting/Skill inventory. The
// sections mount independently, so a graph or artifact failure stays inside its
// own section and never blanks the results.
export function TrialSection({
  trial,
  withBreadcrumbs = false,
}: {
  trial: EvalTrial
  withBreadcrumbs?: boolean
}) {
  const counts = outcomeCounts(trial)
  const anchor = trialAnchor(trial.target_run_id, trial.trial_id)
  const { snapshot } = useEvalData()
  // One operator request per displayed Trial with results; the reference is
  // never fetched by the pure result views themselves.
  const groundTruth = useOperatorGroundTruth(trial.target_id, trial.verdicts.length > 0)
  const crumbs = [
    { label: "Eval", to: evalPaths.dashboard },
    ...(snapshot
      ? [{ label: snapshot.dataset.name, to: evalPaths.dataset(snapshot.dataset.id) }]
      : []),
    { label: trial.target_id, to: targetPaths.target(trial.target_id) },
    {
      label: trial.target_run_id,
      to: `${targetPaths.target(trial.target_id)}#targetrun-${trial.target_run_id.replace(
        /[^A-Za-z0-9_-]/g,
        "-",
      )}`,
    },
    { label: trial.trial_id },
  ]

  return (
    <section id={anchor} className="trial-section" aria-label={`Trial ${trial.trial_id}`}>
      {withBreadcrumbs && <EvalBreadcrumbs items={crumbs} />}
      <header className="eval-header eval-trial-header">
        <h3>
          Trial <span className="eval-ref">{trial.trial_id}</span>
        </h3>
        <p className="project-trial-identity">
          <span className="eval-ref">{trial.target_id}</span> /{" "}
          <span className="eval-ref">{trial.target_run_id}</span> /{" "}
          <span className="eval-ref">{trial.trial_id}</span> · project{" "}
          <span className="eval-ref">{trial.project_id ?? "unassigned"}</span>
        </p>
        <p className="trial-saved">
          <SavedOn copiedAt={trial.copied_at} />
        </p>
        <ul className="eval-chips">
          <li>
            <span className="eval-chip-label">Terminal</span>
            <span className="eval-chip-value">{trial.terminal ?? "—"}</span>
          </li>
          <li>
            <span className="eval-chip-label">Availability</span>
            <span className="eval-chip-value">{trial.availability}</span>
          </li>
          <li>
            <span className="eval-chip-label">Outcome</span>
            <span className="eval-chip-value">
              {counts.identified} identified / {counts.partial} partial / {counts.missed} missed
            </span>
          </li>
        </ul>
        <p className="trial-phases">
          <span className="eval-chip-label">Phases</span> {phasesLabel(trial)}
        </p>
      </header>

      {trial.availability === "degraded" && (
        <section className="eval-notice" aria-label="Degraded trial">
          <h2>Degraded trial</h2>
          <p>
            This trial could not be fully projected (reason:{" "}
            <span className="eval-ref">{trial.reason ?? "unknown"}</span>).
          </p>
        </section>
      )}

      <RecordedSpend trial={trial} />
      {/* One resolved-inventory poll feeds both the verdict evidence links and
          the artifact list, so the two never fetch the same endpoint twice. */}
      <ResolvedArtifactsProvider
        targetId={trial.target_id}
        targetRunId={trial.target_run_id}
        trialId={trial.trial_id}
        expectedProjectId={trial.project_id}
      >
        <TrialResults trial={trial} groundTruth={groundTruth} />
        <TrialProjectGraph
          targetId={trial.target_id}
          targetRunId={trial.target_run_id}
          trialId={trial.trial_id}
        />
        <ResolvedArtifactsSection
          targetId={trial.target_id}
          targetRunId={trial.target_run_id}
          trialId={trial.trial_id}
          expectedProjectId={trial.project_id}
          detailPath={(artifactId) =>
            targetPaths.trialArtifact(
              trial.target_id,
              trial.target_run_id,
              trial.trial_id,
              artifactId,
            )
          }
        />
      </ResolvedArtifactsProvider>
      <MaterializedArtifacts trial={trial} />
    </section>
  )
}
