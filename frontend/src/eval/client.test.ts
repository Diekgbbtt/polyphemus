import { afterEach, expect, test, vi } from "vitest"
import { getSnapshot, getTrialProjectGraph } from "./client"

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

function stubFetchDetailed(
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

// --- the historical project graph ----------------------------------------------

const GRAPH = {
  status: "available",
  captured_at: "2024-05-05T00:00:00+00:00",
  sha256: "graph-digest",
  graph: { project_id: "proj-1", nodes: [], links: [] },
}

test("getTrialProjectGraph encodes every segment and uses the eval base", async () => {
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "http://eval.test")
  vi.stubEnv("VITE_AGENT_BASE_URL", "http://agent.test")
  const { calls } = stubFetchDetailed(GRAPH)

  const graph = await getTrialProjectGraph("t 1", "r/2", "x?y")

  expect(calls).toEqual(["http://eval.test/trials/t%201/r%2F2/x%3Fy/project-graph"])
  expect(graph.graph.project_id).toBe("proj-1")
})

test("getTrialProjectGraph is independent of VITE_AGENT_BASE_URL", async () => {
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "")
  vi.stubEnv("VITE_AGENT_BASE_URL", "http://agent.test")
  const { calls } = stubFetchDetailed(GRAPH)

  await getTrialProjectGraph("t", "r", "trial")

  expect(calls).toEqual(["/trials/t/r/trial/project-graph"])
})

test("getTrialProjectGraph forwards the AbortSignal", async () => {
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "")
  const { inits } = stubFetchDetailed(GRAPH)
  const controller = new AbortController()

  await getTrialProjectGraph("t", "r", "trial", controller.signal)

  expect(inits[0].signal).toBe(controller.signal)
})

test("getTrialProjectGraph rejects with the stable failure detail", async () => {
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "")
  stubFetchDetailed({ detail: "project_graph_unavailable" }, 409)

  await expect(getTrialProjectGraph("t", "r", "trial")).rejects.toThrow(
    "project_graph_unavailable",
  )
})

test("getTrialProjectGraph falls back safely for a non-JSON body", async () => {
  vi.stubEnv("VITE_EVAL_API_BASE_URL", "")
  stubFetchDetailed("<html>nope</html>", 500)

  await expect(getTrialProjectGraph("t", "r", "trial")).rejects.toThrow(
    "/trials/t/r/trial/project-graph -> 500",
  )
})
