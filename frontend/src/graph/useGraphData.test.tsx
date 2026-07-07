import { renderHook, waitFor } from "@testing-library/react"
import { useGraphData } from "./useGraphData"

test("useGraphData loads and exposes data", async () => {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ project_id: "p1", nodes: [{ id: "a", name: "acme", type: "Domain", properties: {} }], links: [] }),
      { status: 200 })) as typeof fetch
  const { result } = renderHook(() => useGraphData("p1"))
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.data?.nodes[0].id).toBe("a")
})
