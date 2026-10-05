import { afterEach, expect, test, vi } from "vitest"
import {
  DEFAULT_OPERATOR_GT_BASE_URL,
  getOperatorGroundTruth,
  operatorGroundTruthBaseUrl,
} from "./operatorGroundTruth"

const PAYLOAD = {
  target_id: "comfyui-1",
  provenance: "current_benchmark_checkout",
  vulnerabilities: [
    {
      vuln_id: "comfyui-001",
      location: "http://comfyui-manager:8288/view",
      type: "Arbitrary File Read",
      scoring: ["LLM_judge"],
    },
  ],
}

afterEach(() => vi.unstubAllEnvs())

function stubFetch(
  body: unknown,
  status = 200,
): { calls: string[]; inits: RequestInit[] } {
  const calls: string[] = []
  const inits: RequestInit[] = []
  globalThis.fetch = (async (url: unknown, init?: RequestInit) => {
    calls.push(String(url))
    inits.push(init ?? {})
    const text = typeof body === "string" ? body : JSON.stringify(body)
    return new Response(text, { status })
  }) as typeof fetch
  return { calls, inits }
}

test("requests the reference from the loopback operator base by default", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  const { calls } = stubFetch(PAYLOAD)

  const data = await getOperatorGroundTruth("comfyui-1")

  expect(calls).toEqual([
    `${DEFAULT_OPERATOR_GT_BASE_URL}/ground-truth/targets/comfyui-1`,
  ])
  expect(data.vulnerabilities[0].location).toBe("http://comfyui-manager:8288/view")
})

test("encodes the target id and forwards the abort signal", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  const { calls, inits } = stubFetch(PAYLOAD)
  const controller = new AbortController()

  await getOperatorGroundTruth("comfyui-1", controller.signal).catch(() => undefined)

  expect(calls[0]).toContain("/ground-truth/targets/")
  expect(inits[0].signal).toBe(controller.signal)
})

test("accepts a loopback base override and never falls back to another API", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "http://127.0.0.1:19099/")
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "http://eval.invalid")
  vi.stubEnv("VITE_AGENT_BASE_URL", "http://agent.invalid")
  const { calls } = stubFetch(PAYLOAD)

  await getOperatorGroundTruth("comfyui-1")

  expect(operatorGroundTruthBaseUrl()).toBe("http://127.0.0.1:19099")
  expect(calls).toEqual(["http://127.0.0.1:19099/ground-truth/targets/comfyui-1"])
})

test("rejects a non-loopback override without issuing a request", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "https://evil.invalid")
  const { calls } = stubFetch(PAYLOAD)

  await expect(getOperatorGroundTruth("comfyui-1")).rejects.toThrow()

  expect(calls).toEqual([])
})

test("rejects an override that carries credentials, a query or a fragment", async () => {
  for (const base of [
    "http://user:pass@localhost:18091",
    "http://localhost:18091/?token=1",
    "http://localhost:18091/#frag",
  ]) {
    vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", base)
    const { calls } = stubFetch(PAYLOAD)
    await expect(getOperatorGroundTruth("comfyui-1")).rejects.toThrow()
    expect(calls).toEqual([])
  }
})

test("an HTTP failure is a path-and-body-free unavailable error", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  const { calls } = stubFetch({ detail: "ground_truth_source_invalid" }, 503)

  await expect(getOperatorGroundTruth("comfyui-1")).rejects.toThrow(
    "operator ground truth unavailable",
  )
  expect(calls).toHaveLength(1)
})

test("a network failure and a malformed body are unavailable errors", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  globalThis.fetch = (async () => {
    throw new Error("socket closed")
  }) as typeof fetch
  await expect(getOperatorGroundTruth("comfyui-1")).rejects.toThrow(
    "operator ground truth unavailable",
  )

  stubFetch("{ not json")
  await expect(getOperatorGroundTruth("comfyui-1")).rejects.toThrow(
    "operator ground truth unavailable",
  )

  stubFetch({ ...PAYLOAD, vulnerabilities: "nope" })
  await expect(getOperatorGroundTruth("comfyui-1")).rejects.toThrow(
    "operator ground truth unavailable",
  )
})

test("a response for another target is rejected", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  stubFetch(PAYLOAD)

  await expect(getOperatorGroundTruth("jetlinks-1")).rejects.toThrow(
    "operator ground truth unavailable",
  )
})

test("conflicting duplicate vulnerability ids are rejected, identical ones collapse", async () => {
  vi.stubEnv("VITE_OPERATOR_GT_API_BASE_URL", "")
  const entry = PAYLOAD.vulnerabilities[0]

  stubFetch({
    ...PAYLOAD,
    vulnerabilities: [entry, { ...entry, scoring: ["route_probe"] }],
  })
  await expect(getOperatorGroundTruth("comfyui-1")).rejects.toThrow(
    "operator ground truth unavailable",
  )

  const { calls } = stubFetch({ ...PAYLOAD, vulnerabilities: [entry, { ...entry }] })
  const data = await getOperatorGroundTruth("comfyui-1")
  expect(calls).toHaveLength(1)
  expect(data.vulnerabilities).toHaveLength(1)
})
