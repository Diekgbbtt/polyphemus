import { useEffect, useRef, useState } from "react"
import { getResolvedArtifact } from "./client"
import { podExportReasonFromDetail } from "./projectArtifacts"
import type { PodExportOutcome, PodExportReason } from "./projectArtifacts"
import type { ProjectArtifactEntry } from "./types"

// Bounded detail fan-out (spec 3): at most this many PodExport details are read
// at once, so a wide inventory can never open an unbounded number of requests.
export const POD_EXPORT_DETAIL_CONCURRENCY = 3
// Every detail request is bounded by a finite timeout.
export const POD_EXPORT_DETAIL_TIMEOUT_MS = 10_000

type CachedReason = PodExportReason | null

// A signal that aborts when either the caller's signal aborts or `ms` elapses.
function withTimeout(signal: AbortSignal, ms: number): { signal: AbortSignal; clear: () => void } {
  const controller = new AbortController()
  const onAbort = () => controller.abort()
  if (signal.aborted) controller.abort()
  else signal.addEventListener("abort", onAbort, { once: true })
  const timer = setTimeout(() => controller.abort(), ms)
  return {
    signal: controller.signal,
    clear: () => {
      clearTimeout(timer)
      signal.removeEventListener("abort", onAbort)
    },
  }
}

// Resolve each PodExport's outcome for presentation.
//
// The inventory carries no `terminal_reason`, so this reads the existing
// detail GET for kind=pod_export only - never content, never the filename or the
// verdict. Results are cached by the full trial identity + artifact id + sha256
// (a changed digest re-reads; an unchanged one is never re-downloaded on the
// 15s poll). A transient failure is shown as "unavailable" but not cached, so
// the next pass retries it. The identity change and unmount abort every
// in-flight request and drop any late response.
export function usePodExportOutcomes({
  targetId,
  targetRunId,
  trialId,
  exports,
  inventoryRevision,
}: {
  targetId: string
  targetRunId: string
  trialId: string
  exports: ProjectArtifactEntry[]
  // Changes on every successful inventory read: re-runs the pass (to retry
  // uncached entries) without re-downloading the cached ones.
  inventoryRevision: number
}): Map<string, PodExportOutcome> {
  const cache = useRef(new Map<string, CachedReason>())
  const [outcomes, setOutcomes] = useState<Map<string, PodExportOutcome>>(() => new Map())
  const exportsRef = useRef(exports)
  exportsRef.current = exports

  const identity = `${targetId}\u0000${targetRunId}\u0000${trialId}`
  const exportsKey = exports
    .map((entry) => `${entry.artifact_id}\u0000${entry.sha256}`)
    .sort()
    .join("\n")

  useEffect(() => {
    const current = exportsRef.current
    const keyOf = (entry: ProjectArtifactEntry) =>
      `${identity}\u0000${entry.artifact_id}\u0000${entry.sha256}`

    const seed = new Map<string, PodExportOutcome>()
    const pending: ProjectArtifactEntry[] = []
    for (const entry of current) {
      const key = keyOf(entry)
      if (cache.current.has(key)) {
        seed.set(entry.artifact_id, { state: "ready", reason: cache.current.get(key) ?? null })
      } else {
        seed.set(entry.artifact_id, { state: "pending" })
        pending.push(entry)
      }
    }
    setOutcomes(seed)

    if (pending.length === 0) return

    const controller = new AbortController()
    let disposed = false

    const show = (entry: ProjectArtifactEntry, reason: CachedReason, cacheIt: boolean) => {
      if (cacheIt) cache.current.set(keyOf(entry), reason)
      setOutcomes((previous) => {
        const next = new Map(previous)
        next.set(entry.artifact_id, { state: "ready", reason })
        return next
      })
    }

    let cursor = 0
    const worker = async () => {
      for (;;) {
        if (disposed) return
        const index = cursor++
        if (index >= pending.length) return
        const entry = pending[index]
        const box = withTimeout(controller.signal, POD_EXPORT_DETAIL_TIMEOUT_MS)
        try {
          const detail = await getResolvedArtifact(
            targetId,
            targetRunId,
            trialId,
            entry.artifact_id,
            box.signal,
          )
          if (disposed) return
          // A detail that does not match the inventory's id + digest is never
          // trusted (and never cached, so the next pass re-reads it).
          const matches =
            detail.entry.artifact_id === entry.artifact_id && detail.entry.sha256 === entry.sha256
          show(entry, matches ? podExportReasonFromDetail(detail.preview.parsed) : null, matches)
        } catch {
          if (disposed) return
          show(entry, null, false)
        } finally {
          box.clear()
        }
      }
    }

    void Promise.all(
      Array.from({ length: Math.min(POD_EXPORT_DETAIL_CONCURRENCY, pending.length) }, worker),
    )

    return () => {
      disposed = true
      controller.abort()
    }
  }, [identity, exportsKey, inventoryRevision, targetId, targetRunId, trialId])

  return outcomes
}
