import { useParams } from "react-router-dom"
import { useEvalData } from "./EvalDataProvider"
import { TrialSection } from "./TrialSection"

// The canonical deep Trial route. It renders exactly the same Trial section the
// Target workspace embeds, so a bookmarked Trial is never a second, thinner
// view: same identity, results, resolved graph, and resolved artifacts.
export function TrialPage() {
  const { targetId = "", targetRunId = "", trialId = "" } = useParams()
  const { snapshot } = useEvalData()
  if (!snapshot) return null

  const trial = snapshot.trials.find(
    (item) =>
      item.target_id === targetId &&
      item.target_run_id === targetRunId &&
      item.trial_id === trialId,
  )
  if (!trial) {
    return (
      <div className="eval-page">
        <p className="eval-empty">Unknown trial “{trialId}”.</p>
      </div>
    )
  }

  return (
    <div className="eval-page">
      <TrialSection trial={trial} withBreadcrumbs />
    </div>
  )
}
