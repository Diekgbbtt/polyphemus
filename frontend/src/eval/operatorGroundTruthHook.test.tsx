import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, expect, test, vi } from "vitest"
import { useOperatorGroundTruth } from "./operatorGroundTruth"

afterEach(() => vi.unstubAllEnvs())

function payload(targetId: string, vulnId = "V-1") {
  return {
    target_id: targetId,
    provenance: "current_benchmark_checkout",
    vulnerabilities: [
      { vuln_id: vulnId, location: "/view", type: "Type", scoring: ["LLM_judge"] },
    ],
  }
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

test("requests the reference once when enabled", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  const calls: string[] = []
  globalThis.fetch = (async (url: unknown) => {
    calls.push(String(url))
    return jsonResponse(payload("comfyui-1"))
  }) as typeof fetch

  const { result } = renderHook(() => useOperatorGroundTruth("comfyui-1", true))

  await waitFor(() => expect(result.current.status).toBe("ready"))
  expect(calls).toHaveLength(1)
  expect(calls[0]).toContain("/ground-truth/targets/comfyui-1")
})

test("does not request anything when disabled", () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  const calls: string[] = []
  globalThis.fetch = (async (url: unknown) => {
    calls.push(String(url))
    return jsonResponse(payload("comfyui-1"))
  }) as typeof fetch

  const { result } = renderHook(() => useOperatorGroundTruth("comfyui-1", false))

  expect(result.current).toEqual({ status: "disabled" })
  expect(calls).toEqual([])
})

test("an identity change aborts the old request and never shows its data", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  const inits: RequestInit[] = []
  globalThis.fetch = (async (url: unknown, init?: RequestInit) => {
    inits.push(init ?? {})
    const id = String(url).endsWith("comfyui-1") ? "comfyui-1" : "jetlinks-1"
    return jsonResponse(payload(id, id === "comfyui-1" ? "V-OLD" : "V-NEW"))
  }) as typeof fetch

  const { result, rerender } = renderHook(
    ({ id }: { id: string }) => useOperatorGroundTruth(id, true),
    { initialProps: { id: "comfyui-1" } },
  )
  await waitFor(() => expect(result.current.status).toBe("ready"))

  rerender({ id: "jetlinks-1" })

  // The prior target's ready state is not shown for the new target, even in
  // the render before the effect cleanup runs.
  expect(result.current.status).toBe("loading")
  await waitFor(() => expect(inits[0]?.signal?.aborted).toBe(true))
  await waitFor(() => expect(result.current.status).toBe("ready"))
  expect(
    (result.current as { data: { target_id: string } }).data.target_id,
  ).toBe("jetlinks-1")
})

test("a delayed response for the previous target never reaches the new state", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  const first = deferred<Response>()
  const second = deferred<Response>()
  globalThis.fetch = (async (url: unknown) => {
    return String(url).endsWith("comfyui-1") ? first.promise : second.promise
  }) as typeof fetch

  const { result, rerender } = renderHook(
    ({ id }: { id: string }) => useOperatorGroundTruth(id, true),
    { initialProps: { id: "comfyui-1" } },
  )
  rerender({ id: "jetlinks-1" })

  second.resolve(jsonResponse(payload("jetlinks-1", "V-NEW")))
  await waitFor(() => expect(result.current.status).toBe("ready"))

  // The stale answer arrives after the new one; it must be discarded.
  first.resolve(jsonResponse(payload("comfyui-1", "V-OLD")))
  await new Promise((resolve) => setTimeout(resolve, 0))

  expect(result.current.status).toBe("ready")
  const ready = result.current as {
    data: { target_id: string; vulnerabilities: { vuln_id: string }[] }
  }
  expect(ready.data.target_id).toBe("jetlinks-1")
  expect(ready.data.vulnerabilities.map((v) => v.vuln_id)).toEqual(["V-NEW"])
})

test("a failure becomes the unavailable state without hiding anything else", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  globalThis.fetch = (async () => {
    throw new Error("second tunnel absent")
  }) as typeof fetch

  const { result } = renderHook(() => useOperatorGroundTruth("comfyui-1", true))

  await waitFor(() => expect(result.current).toEqual({ status: "unavailable" }))
})
