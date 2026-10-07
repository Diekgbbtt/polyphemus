import { formatClockTime } from "../usePolledResource"
import { useEvalData } from "./EvalDataProvider"

// The one manual refresh control: a button plus the time of the last successful
// read. It is deliberately distinct from a Trial's recorded materialization
// time, so "updated just now" and "saved at ..." never read as the same fact.
export function EvalRefreshControls() {
  const { refresh, lastUpdatedAt } = useEvalData()
  return (
    <div className="eval-refresh-controls">
      <button type="button" className="eval-refresh" onClick={refresh}>
        Refresh
      </button>
      {lastUpdatedAt !== null && (
        <span className="eval-updated">
          Last updated {formatClockTime(lastUpdatedAt)}
        </span>
      )}
    </div>
  )
}
