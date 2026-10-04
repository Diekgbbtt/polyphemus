import { useParams } from "react-router-dom"
import { useEvalData } from "../eval/EvalDataProvider"
import { TrialSection } from "../eval/TrialSection"

// The legacy project-scoped Trial URL. It stays a thin wrapper around the same
// shared Trial section the canonical Target workspace renders. The Trial still
// resolves by its full identity and must belong to the route's project, so an
// unknown or cross-project match is a generic not-found and never leaks another
// Trial.
export function ProjectTrialPage() {
  const { projectId = "", targetId = "", targetRunId = "", trialId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const trial = snapshot.trials.find(
    (item) =>
      item.target_id === targetId &&
      item.target_run_id === targetRunId &&
      item.trial_id === trialId,
  )
  if (!trial || trial.project_id !== projectId) {
    return (
      <div className="eval-page project-trial">
        <p className="eval-empty" role="status">
          Trial not found.
        </p>
      </div>
    )
  }

  return (
    <div className="eval-page project-trial">
      <TrialSection trial={trial} />
    </div>
  )
}
