import { act, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, expect, test, vi } from "vitest"
import { TrialProjectGraph } from "./TrialProjectGraph"

vi.mock("../graph/GraphCanvas", () => ({
  GraphCanvas: ({ nodes }: { nodes: Array<{ id: string }> }) =>
    <div data-testid="review-canvas">{nodes.map(n => n.id).join(",")}</div>,
}))
afterEach(() => vi.useRealTimers())
const graph = (id: string, source = "project_storage") => ({
  status: "available", source, project_id: "p", captured_at: null,
  sha256: source === "trial_snapshot" ? "digest" : null, fallback_reason: null,
  graph: { project_id: "p", nodes: [{ id, name: id, type: "Endpoint", properties: {} }], links: [] },
})
const unavailable = (reason: string) => ({
  status: "unavailable", source: "project_storage", project_id: "p",
  captured_at: null, fallback_reason: null, reason,
})
const json = (value: unknown) => new Response(JSON.stringify(value))
const view = (id = "a") => <MemoryRouter><TrialProjectGraph targetId="t" targetRunId="r" trialId={id}/></MemoryRouter>

test("review: a confirmed empty graph invalidates stale retention before a timeout", async () => {
  vi.useFakeTimers()
  let body: unknown = graph("old")
  globalThis.fetch = vi.fn(async () => json(body))
  render(view())
  await act(async () => {})
  expect(screen.getByTestId("review-canvas").textContent).toBe("old")
  body = unavailable("project_graph_empty")
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.queryByTestId("review-canvas")).toBeNull()
  body = unavailable("project_graph_timeout")
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.queryByTestId("review-canvas")).toBeNull()
})

test("review: a post-timeout response cannot become the frozen capture for a later poll", async () => {
  vi.useFakeTimers()
  let resolveOld!: (response: Response) => void
  const old = new Promise<Response>(resolve => { resolveOld = resolve })
  const fetcher = vi.fn().mockImplementationOnce(() => old).mockImplementation(async () => json(graph("fresh")))
  globalThis.fetch = fetcher
  render(view())
  await act(async () => { await vi.advanceTimersByTimeAsync(45_000) })
  // The tick at 45s starts a recovery request once the first one times out.
  expect(screen.getByTestId("review-canvas").textContent).toBe("fresh")
  await act(async () => { resolveOld(json(graph("discarded", "trial_snapshot"))) })
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.getByTestId("review-canvas").textContent).toBe("fresh")
  expect(fetcher).toHaveBeenCalledTimes(3)
})

test("review: an aborted old trial response cannot overwrite the new trial frozen cache", async () => {
  vi.useFakeTimers()
  let resolveOld!: (response: Response) => void
  const old = new Promise<Response>(resolve => { resolveOld = resolve })
  const calls: string[] = []
  let newBody: unknown = graph("new-captured", "trial_snapshot")
  globalThis.fetch = vi.fn(async input => {
    const url = String(input); calls.push(url)
    return url.includes("/a/resolved-graph") ? old : json(newBody)
  }) as typeof fetch
  const { rerender } = render(view("a"))
  rerender(view("b"))
  await act(async () => {})
  expect(screen.getByTestId("review-canvas").textContent).toBe("new-captured")
  newBody = graph("mutable-replacement")
  await act(async () => { resolveOld(json(graph("old-captured", "trial_snapshot"))) })
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.getByTestId("review-canvas").textContent).toBe("new-captured")
  expect(calls.filter(url => url.includes("/b/resolved-graph"))).toHaveLength(1)
})
