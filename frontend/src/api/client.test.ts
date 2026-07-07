import { getProjects } from "./client"

test("getProjects unwraps the projects array", async () => {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ projects: [{ project_id: "p1", name: "x", created_at: "t" }] }),
      { status: 200 })) as typeof fetch
  const out = await getProjects()
  expect(out[0].project_id).toBe("p1")
})
