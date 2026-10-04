import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, expect, test } from "vitest"
import { ProjectsPage } from "./pages/ProjectsPage"
import type { EvalSnapshot } from "./eval/types"

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

const SNAPSHOT: EvalSnapshot = {
  dataset: { id: "webexploitbench", name: "WebExploitBench" },
  summary: { targets: 1, trials: 1, identified: 0, partial: 0, missed: 1, degraded: 0 },
  targets: [],
  trials: [
    {
      target_id: "comfyui-1",
      target_run_id: "run-a",
      trial_id: "trial-1",
      instance_id: "inst-1",
      project_id: "proj-eval",
      start_phase: "recon",
      terminal: "stopped",
      copied_at: "2024-01-02T00:00:00+00:00",
      phases: [],
      eval_sha: "demo-sha-c",
      stack_fingerprint: "demo-env-w",
      verdicts: [],
      diagnoses: [],
      availability: "complete",
      reason: null,
      artifact_summary: { status: "available", hunting: 21, skills: 0 },
      project_graph_summary: {
        status: "available",
        nodes: 4,
        links: 3,
        captured_at: "2024-01-02T00:00:00+00:00",
      },
    },
  ],
  versions: [],
  coverage: {
    targets: { tested: 0, with_identified: 0, without_identified: 0 },
    vulnerabilities: { total: 0, found: 0, not_found: 0, partial: 0 },
  },
  successes: [],
  degraded_trials: [],
}

function stubCatalog(live: Response, snapshot: Response) {
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    if (url.includes("/projects")) return live
    if (url.includes("/snapshot")) return snapshot
    throw new Error(`unexpected fetch: ${url}`)
  }) as typeof fetch
}

afterEach(() => {
  window.history.pushState({}, "", "/")
})

test("the catalog lists an eval-derived project when the live runtime is unavailable", async () => {
  stubCatalog(json({ detail: "unavailable" }, 503), json(SNAPSHOT))
  render(
    <MemoryRouter>
      <ProjectsPage />
    </MemoryRouter>,
  )

  await waitFor(() =>
    expect(screen.getByText(/live runtime unavailable/i)).toBeDefined(),
  )
  // The failure is non-blocking: the eval-only project is still listed, and its
  // card leads to the eval workspace, never the unavailable live graph.
  const link = screen.getByRole("link", { name: "proj-eval" })
  expect(link.getAttribute("href")).toBe("/p/proj-eval/evals")
  expect(screen.queryByRole("alert")).toBeNull()
})

test("live and eval projects merge into one card", async () => {
  stubCatalog(
    json({
      projects: [
        { project_id: "proj-eval", name: "Shared Project", created_at: "2024-01-01T00:00:00+00:00" },
        { project_id: "live-only", name: "Live Only", created_at: "2024-01-01T00:00:00+00:00" },
      ],
    }),
    json(SNAPSHOT),
  )
  render(
    <MemoryRouter>
      <ProjectsPage />
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getByText("Shared Project")).toBeDefined())
  // One row per project_id: the shared project is not duplicated. The catalog is
  // a single vertical list of row entries, not a grid of bordered cards.
  const rows = screen.getAllByRole("listitem")
  expect(rows).toHaveLength(2)
  for (const row of rows) {
    expect(row.className).toContain("project-entry")
    expect(row.querySelector(".project-card")).toBeNull()
  }
  expect(screen.getAllByText("Shared Project")).toHaveLength(1)
  expect(screen.getByText("Live Only")).toBeDefined()
})
