import { useEffect, useRef, useState } from "react"
import type { Dispatch, SetStateAction } from "react"
import { getResolvedArtifact } from "./client"
import { podExportReasonFromDetail } from "./projectArtifacts"
import type { PodExportOutcome, PodExportReason } from "./projectArtifacts"
import type { ProjectArtifactEntry } from "./types"

// Bounded detail fan-out: at most this many PodExport details are read at once,
// so a wide inventory can never open an unbounded number of requests.
export const POD_EXPORT_DETAIL_CONCURRENCY = 3
// Every detail request is bounded by a finite timeout.
export const POD_EXPORT_DETAIL_TIMEOUT_MS = 10_000

type CachedReason = PodExportReason | null
type Ids = { targetId: string; targetRunId: string; trialId: string }
type Desired = { entry: ProjectArtifactEntry; cacheKey: string }

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

// The classification queue: a single long-lived pass over the pending exports.
//
// The pass deliberately outlives the 15s inventory poll. A poll only *reconciles*
// the desired set (add / drop / invalidate) and asks for one follow-up pass; it
// never aborts the in-flight work or restarts from the front. Every round
// attempts each pending export at most once with at most
// POD_EXPORT_DETAIL_CONCURRENCY workers, so a slow or failing head can never
// starve the tail. A failure is left uncached and retried only on a later round
// (the next poll), never in a tight loop.
function createPodExportMachine(
  setOutcomes: Dispatch<SetStateAction<Map<string, PodExportOutcome>>>,
  cache: Map<string, CachedReason>,
  getIds: () => Ids,
) {
  let identity = ""
  let epoch = 0
  let stopped = false
  let pumping = false
  let pumpingEpoch = -1
  let rerun = false
  let desired = new Map<string, Desired>()
  const inflight = new Map<string, AbortController>()

  const cacheKeyOf = (entry: ProjectArtifactEntry) =>
    `${identity}\u0000${entry.artifact_id}\u0000${entry.sha256}`

  const put = (id: string, outcome: PodExportOutcome) => {
    setOutcomes((previous) => {
      const next = new Map(previous)
      next.set(id, outcome)
      return next
    })
  }

  const drop = (id: string) => {
    setOutcomes((previous) => {
      if (!previous.has(id)) return previous
      const next = new Map(previous)
      next.delete(id)
      return next
    })
  }

  const abortAll = () => {
    for (const controller of inflight.values()) controller.abort()
    inflight.clear()
  }

  // A new trial identity: abandon the old work and show nothing from it.
  const reset = (nextIdentity: string) => {
    abortAll()
    epoch += 1
    identity = nextIdentity
    stopped = false
    rerun = false
    desired = new Map()
    setOutcomes(new Map())
  }

  // Unmount: abandon every in-flight request.
  const stop = () => {
    abortAll()
    epoch += 1
    stopped = true
    rerun = false
    desired = new Map()
  }

  const attempt = async (id: string, run: number) => {
    const target = desired.get(id)
    if (!target || stopped || epoch !== run) return
    if (cache.has(target.cacheKey) || inflight.has(id)) return
    const controller = new AbortController()
    inflight.set(id, controller)
    const box = withTimeout(controller.signal, POD_EXPORT_DETAIL_TIMEOUT_MS)
    try {
      const { targetId, targetRunId, trialId } = getIds()
      const detail = await getResolvedArtifact(
        targetId,
        targetRunId,
        trialId,
        target.entry.artifact_id,
        box.signal,
      )
      if (stopped || epoch !== run) return
      const current = desired.get(id)
      // The export was removed, or its digest was superseded: a late response
      // for the old request must never win.
      if (!current || current.cacheKey !== target.cacheKey) return
      const matches =
        detail.entry.artifact_id === target.entry.artifact_id &&
        detail.entry.sha256 === target.entry.sha256
      const reason = matches ? podExportReasonFromDetail(detail.preview.parsed) : null
      if (matches) cache.set(target.cacheKey, reason)
      put(id, { state: "ready", reason })
    } catch {
      if (stopped || epoch !== run) return
      const current = desired.get(id)
      if (!current || current.cacheKey !== target.cacheKey) return
      // A transient failure stays visible but is never cached: it is retried in
      // a later round, once the other exports have had their turn.
      put(id, { state: "ready", reason: null })
    } finally {
      box.clear()
      if (inflight.get(id) === controller) inflight.delete(id)
    }
  }

  const runRound = async (run: number) => {
    const round: string[] = []
    for (const [id, target] of desired) {
      if (cache.has(target.cacheKey) || inflight.has(id)) continue
      round.push(id)
    }
    if (round.length === 0) return
    let cursor = 0
    const worker = async () => {
      for (;;) {
        if (stopped || epoch !== run) return
        const index = cursor++
        if (index >= round.length) return
        await attempt(round[index], run)
      }
    }
    await Promise.all(
      Array.from({ length: Math.min(POD_EXPORT_DETAIL_CONCURRENCY, round.length) }, worker),
    )
  }

  const pump = async (): Promise<void> => {
    if (stopped) return
    // Only a pass on the SAME identity blocks a new one: a stale pass from a
    // superseded trial must never hold the queue hostage.
    if (pumping && pumpingEpoch === epoch) {
      rerun = true
      return
    }
    const run = epoch
    pumping = true
    pumpingEpoch = run
    try {
      while (!stopped && epoch === run) {
        rerun = false
        await runRound(run)
        if (stopped || epoch !== run) return
        if (!rerun) return
      }
    } finally {
      if (pumpingEpoch === run) pumping = false
    }
  }

  // Bring the queue in line with the current inventory without disturbing the
  // work that is already in flight: unchanged entries are left alone, new ones
  // are queued, removed ones are cancelled, and a changed digest invalidates the
  // old result. Then ask for a pass (a follow-up when one is already running).
  const reconcile = (entries: ProjectArtifactEntry[]) => {
    if (stopped) return
    const present = new Set<string>()
    for (const entry of entries) {
      present.add(entry.artifact_id)
      const key = cacheKeyOf(entry)
      const existing = desired.get(entry.artifact_id)
      if (existing && existing.cacheKey === key) continue
      if (existing) {
        inflight.get(entry.artifact_id)?.abort()
        inflight.delete(entry.artifact_id)
      }
      desired.set(entry.artifact_id, { entry, cacheKey: key })
      if (cache.has(key)) put(entry.artifact_id, { state: "ready", reason: cache.get(key) ?? null })
      else put(entry.artifact_id, { state: "pending" })
    }
    for (const id of [...desired.keys()]) {
      if (present.has(id)) continue
      inflight.get(id)?.abort()
      inflight.delete(id)
      desired.delete(id)
      drop(id)
    }
    void pump()
  }

  return {
    identity: () => identity,
    stopped: () => stopped,
    reset,
    stop,
    reconcile,
  }
}

// Resolve each PodExport's outcome for presentation.
//
// The inventory carries no `terminal_reason`, so this reads the existing detail
// GET for kind=pod_export only - never content, never the filename or the
// verdict. Results are cached by the full trial identity + artifact id + sha256
// (a changed digest re-reads; an unchanged one is never re-downloaded on the
// 15s poll). The queue is described on `createPodExportMachine`.
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
  // Changes on every successful inventory read, so a poll retries uncached
  // entries without touching the ones already classified.
  inventoryRevision: number
}): Map<string, PodExportOutcome> {
  const [outcomes, setOutcomes] = useState<Map<string, PodExportOutcome>>(() => new Map())
  const cacheRef = useRef(new Map<string, CachedReason>())
  const idsRef = useRef<Ids>({ targetId, targetRunId, trialId })
  idsRef.current = { targetId, targetRunId, trialId }
  const exportsRef = useRef(exports)
  exportsRef.current = exports

  const machineRef = useRef<ReturnType<typeof createPodExportMachine> | null>(null)
  if (machineRef.current === null) {
    machineRef.current = createPodExportMachine(setOutcomes, cacheRef.current, () => idsRef.current)
  }

  const identity = `${targetId}\u0000${targetRunId}\u0000${trialId}`
  const exportsKey = exports
    .map((entry) => `${entry.artifact_id}\u0000${entry.sha256}`)
    .sort()
    .join("\n")

  useEffect(() => {
    const machine = machineRef.current
    if (!machine) return
    if (machine.identity() !== identity || machine.stopped()) machine.reset(identity)
    machine.reconcile(exportsRef.current)
  }, [identity, exportsKey, inventoryRevision])

  useEffect(() => () => machineRef.current?.stop(), [])

  return outcomes
}
