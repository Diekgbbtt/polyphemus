import type { ReactElement } from "react"

// The store's materialization time, shown identically in the Target index and
// the Trial detail so the two views never disagree.
//
// The stored value is ISO-8601 with an explicit offset (or `Z`). It is only
// meaningful as an instant, so it is rendered on the reader's own clock, with
// the zone named, and kept verbatim in the machine-readable `dateTime`. A null
// or unparseable value says so rather than showing raw text or guessing a date.
//
// The formatter is built per render rather than cached at module load: a
// module-level formatter would freeze whatever timezone happened to be ambient
// when the module was imported.
function formatInstant(instant: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(instant)
}

export function SavedOn({ copiedAt }: { copiedAt: string | null }): ReactElement {
  const instant = copiedAt ? new Date(copiedAt) : null
  if (!copiedAt || !instant || Number.isNaN(instant.getTime())) {
    return <span className="eval-status">Data non disponibile</span>
  }
  return (
    <span className="trial-saved">
      Salvato il <time dateTime={copiedAt}>{formatInstant(instant)}</time>
    </span>
  )
}
