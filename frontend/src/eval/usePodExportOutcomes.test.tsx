import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, expect, test, vi } from "vitest"
import { POD_EXPORT_DETAIL_CONCURRENCY, usePodExportOutcomes } from "./usePodExportOutcomes"
import type { ProjectArtifactEntry, ResolvedArtifactDetail } from "./types"

function exportEntry(id: string, sha = `sha-${id}`): ProjectArtifactEntry {
  return {
    artifact_id: id,
    category: "hunting",
    kind: "pod_export",
    relative_path: `hunting/test-executor-pod/spec/${id}.yaml`,
    media_type: "application/yaml",
    size_bytes: 10,
    sha256: sha,
    representation: "yaml",
  }
}

function detail(
  entry: ProjectArtifactEntry,
  reason: string | null,
  extra: Partial<ResolvedArtifactDetail> = {},
): ResolvedArtifactDetail {
  return {
    entry,
    preview: {
      text: "raw",
      parsed: reason === null ? { verdict: "unsuccessful", evidence: {} } : { verdict: "unsuccessful", evidence: { terminal_reason: reason } },
      truncated: false,
      parse_error: null,
    },
    content_url: "/never-fetched",
    ...extra,
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

const abortError = () => new DOMException("aborted", "AbortError")

afterEach(() => {
  vi.useRealTimers()
})

test("classifies each export from its envelope detail and never fetches content", async () => {
  const exports = [exportEntry("e1"), exportEntry("e2")]
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    const id = url.split("/").pop() ?? ""
    const entry = exports.find((item) => item.artifact_id === id)!
    return json(detail(entry, id === "e1" ? "symptom-confirmed" : "budget-timeout"))
  }) as typeof fetch

  const { result } = renderHook(() =>
    usePodExportOutcomes({ targetId: "t", targetRunId: "r", trialId: "tr", exports, inventoryRevision: 1 }),
  )

  await waitFor(() =>
    expect(result.current.get("e1")).toEqual({ state: "ready", reason: "symptom-confirmed" }),
  )
  expect(result.current.get("e2")).toEqual({ state: "ready", reason: "budget-timeout" })
  expect(calls.some((url) => url.includes("/content"))).toBe(false)
  expect(calls).toHaveLength(2)
})

test("marks an unrecognized or missing reason as unavailable, never guessed from verdict", async () => {
  const exports = [exportEntry("e1")]
  globalThis.fetch = (async () =>
    json(detail(exports[0], null, {
      preview: { text: "raw", parsed: { verdict: "symptom-confirmed" }, truncated: false, parse_error: null },
    }))) as typeof fetch

  const { result } = renderHook(() =>
    usePodExportOutcomes({ targetId: "t", targetRunId: "r", trialId: "tr", exports, inventoryRevision: 1 }),
  )

  await waitFor(() => expect(result.current.get("e1")).toEqual({ state: "ready", reason: null }))
})

test("bounds concurrent detail requests", async () => {
  const exports = ["e1", "e2", "e3", "e4", "e5"].map((id) => exportEntry(id))
  let active = 0
  let maxActive = 0
  const releasers: Array<() => void> = []
  globalThis.fetch = (async (input: unknown) => {
    active += 1
    maxActive = Math.max(maxActive, active)
    await new Promise<void>((resolve) => releasers.push(resolve))
    active -= 1
    const id = String(input).split("/").pop() ?? ""
    return json(detail(exports.find((item) => item.artifact_id === id)!, "space-exhausted"))
  }) as typeof fetch

  const { result } = renderHook(() =>
    usePodExportOutcomes({ targetId: "t", targetRunId: "r", trialId: "tr", exports, inventoryRevision: 1 }),
  )

  await waitFor(() => expect(releasers.length).toBe(POD_EXPORT_DETAIL_CONCURRENCY))
  expect(maxActive).toBeLessThanOrEqual(POD_EXPORT_DETAIL_CONCURRENCY)

  while (releasers.length > 0) {
    const batch = releasers.splice(0)
    await act(async () => {
      batch.forEach((release) => release())
    })
  }

  await waitFor(() => expect(result.current.size).toBe(5))
  expect(maxActive).toBe(POD_EXPORT_DETAIL_CONCURRENCY)
})

test("does not re-request unchanged details across polls", async () => {
  const exports = [exportEntry("e1")]
  let calls = 0
  globalThis.fetch = (async () => {
    calls += 1
    return json(detail(exports[0], "symptom-confirmed"))
  }) as typeof fetch

  const { result, rerender } = renderHook(
    (props: { revision: number }) =>
      usePodExportOutcomes({ targetId: "t", targetRunId: "r", trialId: "tr", exports, inventoryRevision: props.revision }),
    { initialProps: { revision: 1 } },
  )
  await waitFor(() => expect(result.current.get("e1")).toEqual({ state: "ready", reason: "symptom-confirmed" }))
  expect(calls).toBe(1)

  rerender({ revision: 2 })
  rerender({ revision: 3 })
  await act(async () => {})
  expect(calls).toBe(1)
})

test("re-reads a detail whose digest changed", async () => {
  let entry = exportEntry("e1", "sha-1")
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    calls.push(String(input))
    return json(detail(entry, "symptom-confirmed"))
  }) as typeof fetch

  const { result, rerender } = renderHook(
    (props: { entry: ProjectArtifactEntry; revision: number }) =>
      usePodExportOutcomes({
        targetId: "t",
        targetRunId: "r",
        trialId: "tr",
        exports: [props.entry],
        inventoryRevision: props.revision,
      }),
    { initialProps: { entry, revision: 1 } },
  )
  await waitFor(() => expect(result.current.get("e1")).toEqual({ state: "ready", reason: "symptom-confirmed" }))
  expect(calls).toHaveLength(1)

  entry = exportEntry("e1", "sha-2")
  rerender({ entry, revision: 2 })
  await waitFor(() => expect(calls).toHaveLength(2))
})

test("retries a transient failure on the next poll and recovers", async () => {
  const exports = [exportEntry("e1")]
  let fail = true
  let calls = 0
  globalThis.fetch = (async () => {
    calls += 1
    if (fail) return json({ detail: "artifact_missing" }, 409)
    return json(detail(exports[0], "no-symptom-evidence"))
  }) as typeof fetch

  const { result, rerender } = renderHook(
    (props: { revision: number }) =>
      usePodExportOutcomes({ targetId: "t", targetRunId: "r", trialId: "tr", exports, inventoryRevision: props.revision }),
    { initialProps: { revision: 1 } },
  )
  await waitFor(() => expect(result.current.get("e1")).toEqual({ state: "ready", reason: null }))
  expect(calls).toBe(1)

  fail = false
  rerender({ revision: 2 })
  await waitFor(() =>
    expect(result.current.get("e1")).toEqual({ state: "ready", reason: "no-symptom-evidence" }),
  )
  expect(calls).toBeGreaterThanOrEqual(2)
})

test("never classifies from a detail whose id or digest does not match the inventory", async () => {
  const entry = exportEntry("e1")
  let calls = 0
  globalThis.fetch = (async () => {
    calls += 1
    // Same id, different digest, with a tempting reason attached.
    return json(detail({ ...entry, sha256: "other" }, "symptom-confirmed"))
  }) as typeof fetch

  const { result, rerender } = renderHook(
    (props: { revision: number }) =>
      usePodExportOutcomes({ targetId: "t", targetRunId: "r", trialId: "tr", exports: [entry], inventoryRevision: props.revision }),
    { initialProps: { revision: 1 } },
  )
  await waitFor(() => expect(result.current.get("e1")).toEqual({ state: "ready", reason: null }))

  // A mismatch is not cached: the next poll retries it.
  rerender({ revision: 2 })
  await waitFor(() => expect(calls).toBeGreaterThanOrEqual(2))
})

test("aborts an in-flight detail and ignores a late response after the trial changes", async () => {
  const entryA = exportEntry("eA")
  const entryB = exportEntry("eB")
  let resolveOld: ((value: Response) => void) | undefined
  let oldSignalAborted = false

  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    if (url.includes("/tA/")) {
      // Deliberately ignores the abort for resolution: this models a late
      // response that the hook itself must drop.
      return await new Promise<Response>((resolve) => {
        resolveOld = resolve
        init?.signal?.addEventListener("abort", () => {
          oldSignalAborted = true
        })
      })
    }
    return json(detail(entryB, "budget-timeout"))
  }) as typeof fetch

  const { result, rerender } = renderHook(
    (props: { trialId: string; entry: ProjectArtifactEntry }) =>
      usePodExportOutcomes({
        targetId: "t",
        targetRunId: "r",
        trialId: props.trialId,
        exports: [props.entry],
        inventoryRevision: 1,
      }),
    { initialProps: { trialId: "tA", entry: entryA } },
  )
  await waitFor(() => expect(resolveOld).toBeDefined())

  rerender({ trialId: "tB", entry: entryB })
  await waitFor(() => expect(result.current.get("eB")).toEqual({ state: "ready", reason: "budget-timeout" }))
  expect(oldSignalAborted).toBe(true)

  // The superseded trial's response arrives late: it must not contaminate.
  await act(async () => {
    resolveOld?.(json(detail(entryA, "symptom-confirmed")))
  })
  expect(result.current.has("eA")).toBe(false)
  expect(result.current.get("eB")).toEqual({ state: "ready", reason: "budget-timeout" })
})

test("starts every export as pending during the classification", async () => {
  const exports = [exportEntry("e1")]
  globalThis.fetch = (async (_input: unknown, init?: RequestInit) =>
    await new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(abortError()), { once: true })
    })) as typeof fetch

  const { result } = renderHook(() =>
    usePodExportOutcomes({ targetId: "t", targetRunId: "r", trialId: "tr", exports, inventoryRevision: 1 }),
  )

  await waitFor(() => expect(result.current.get("e1")).toEqual({ state: "pending" }))
  expect(result.current.size).toBe(1)
})
