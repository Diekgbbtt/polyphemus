import type { ReactElement } from "react"
import type { EvalTrial } from "./types"

// The Trial's real execution instants (started_at / finished_at), read from the
// authoritative record - not its copy time. Both the index and the detail use
// this one helper so they never disagree.

// The epoch milliseconds of an instant, or null when it is absent or
// unparseable. Comparing these numbers - never the ISO strings - is what makes
// two offsets order by their real instant rather than lexically.
export function parseInstant(value: string | null | undefined): number | null {
  if (typeof value !== "string" || value === "") return null
  const millis = Date.parse(value)
  return Number.isNaN(millis) ? null : millis
}

// Date, time with seconds, and the reader's zone name, in an explicit English
// (en-GB) locale. Built per call rather than cached at module load, so it never
// freezes an ambient timezone.
export function formatInstant(instant: Date): string {
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(instant)
}

// Newest execution first. A valid start always precedes a missing one, and ties
// break deterministically on the full identity. Never falls back to copied_at,
// captured_at, mtime or the trial id.
export function compareTrialsByStartedAt(a: EvalTrial, b: EvalTrial): number {
  const left = parseInstant(a.started_at)
  const right = parseInstant(b.started_at)
  if (left !== null && right !== null && left !== right) return right - left
  if (left !== null && right === null) return -1
  if (left === null && right !== null) return 1
  for (const key of ["target_id", "target_run_id", "trial_id"] as const) {
    if (a[key] !== b[key]) return a[key] < b[key] ? -1 : 1
  }
  return 0
}

function TimeLabel({
  label,
  value,
}: {
  label: string
  value: string | null | undefined
}): ReactElement {
  const text = typeof value === "string" && value !== "" ? value : null
  const millis = text === null ? null : parseInstant(text)
  if (text === null || millis === null) {
    return (
      <span className="trial-time">
        <span className="trial-time-label">{label}</span>{" "}
        <span className="eval-status">Date unavailable</span>
      </span>
    )
  }
  return (
    <span className="trial-time">
      <span className="trial-time-label">{label}</span>{" "}
      <time dateTime={text}>{formatInstant(new Date(millis))}</time>
    </span>
  )
}

export function StartedOn({ value }: { value: string | null | undefined }): ReactElement {
  return <TimeLabel label="Started at" value={value} />
}

export function FinishedOn({ value }: { value: string | null | undefined }): ReactElement {
  return <TimeLabel label="Finished at" value={value} />
}

// Both execution instants of one Trial, shared by the index and the detail.
export function TrialExecutionTimes({ trial }: { trial: EvalTrial }): ReactElement {
  return (
    <span className="trial-execution">
      <StartedOn value={trial.started_at} />
      <span className="trial-time-sep" aria-hidden="true">
        {" · "}
      </span>
      <FinishedOn value={trial.finished_at} />
    </span>
  )
}
