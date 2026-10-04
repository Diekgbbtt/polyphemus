import { Link } from "react-router-dom"
import { targetPaths } from "../projectPaths"
import { EvalBreadcrumbs, evalPaths } from "./EvalBreadcrumbs"
import { useEvalData } from "./EvalDataProvider"
import { ResolvedArtifactsSection } from "./ResolvedArtifactsSection"
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

      <TrialResults trial={trial} />
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
      <MaterializedArtifacts trial={trial} />
    </section>
  )
}
