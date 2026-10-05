import { formatClockTime } from "../usePolledResource"
import { useEvalData } from "./EvalDataProvider"

// The one manual refresh control: a button plus the time of the last successful
// read. It is deliberately distinct from a Trial's recorded materialization
// time, so "aggiornato adesso" and "salvato il ..." never read as the same fact.
export function EvalRefreshControls() {
  const { refresh, lastUpdatedAt } = useEvalData()
  return (
    <div className="eval-refresh-controls">
      <button type="button" className="eval-refresh" onClick={refresh}>
        Aggiorna
      </button>
      {lastUpdatedAt !== null && (
        <span className="eval-updated">
          Ultimo aggiornamento {formatClockTime(lastUpdatedAt)}
        </span>
      )}
    </div>
  )
}
