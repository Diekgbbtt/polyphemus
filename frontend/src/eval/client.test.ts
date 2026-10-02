import { afterEach, expect, test, vi } from "vitest"
import { getSnapshot } from "./client"

const SNAPSHOT = {
  dataset: { id: "webexploitbench", name: "WebExploitBench" },
  summary: { targets: 0, trials: 0, identified: 0, degraded: 0 },
  targets: [],
  successes: [],
  degraded_trials: [],
}

afterEach(() => vi.unstubAllEnvs())

function stubFetch(body: unknown, status = 200): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (url: unknown) => {
    calls.push(String(url))
    return new Response(JSON.stringify(body), { status })
  }) as typeof fetch
  return calls
}

test("getSnapshot reads VITE_EVAL_API_BASE_URL", async () => {
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "http://eval.test")
  const calls = stubFetch(SNAPSHOT)

  const snapshot = await getSnapshot()

  expect(calls).toEqual(["http://eval.test/snapshot"])
  expect(snapshot.dataset.name).toBe("WebExploitBench")
})

test("getSnapshot is independent of VITE_AGENT_BASE_URL", async () => {
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "")
  vi.stubEnv("VITE_AGENT_BASE_URL", "http://agent.test")
  const calls = stubFetch(SNAPSHOT)

  await getSnapshot()

  expect(calls).toEqual(["/snapshot"])
})

test("getSnapshot raises on a non-2xx response", async () => {
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "")
  stubFetch({ detail: "unavailable" }, 503)

  await expect(getSnapshot()).rejects.toThrow("/snapshot")
})
