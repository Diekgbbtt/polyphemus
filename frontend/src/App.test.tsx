import { render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, expect, test } from "vitest"
import type { EvalTrial } from "./eval/types"
import type { EvalSnapshot } from "./eval/types"
import { ProjectsPage, targetCatalog, unassignedSavedData } from "./pages/ProjectsPage"

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function trial(
  target_id: string,
  target_run_id: string,
  trial_id: string,
  project_id: string,
): EvalTrial {
  return {
    target_id,
    target_run_id,
    trial_id,
    instance_id: "eval-server-1",
    project_id,
    start_phase: "recon",
    terminal: "complete",
    copied_at: "2024-01-02T00:00:00+00:00",
    phases: [],
    eval_sha: "demo-sha",
    stack_fingerprint: "demo-env",
    verdicts: [],
    diagnoses: [],
    availability: "complete",
    reason: null,
    artifact_summary: { status: "available", hunting: 1, skills: 0 },
    project_graph_summary: {
      status: "available",
      nodes: 4,
      links: 3,
      captured_at: "2024-01-02T00:00:00+00:00",
    },
  }
}

const SNAPSHOT: EvalSnapshot = {
  dataset: { id: "webexploitbench", name: "WebExploitBench" },
  summary: { targets: 2, trials: 2, identified: 0, partial: 1, missed: 1, degraded: 0 },
  targets: [
    {
      target_id: "white-jotter-1",
      trial_count: 1,
      identified_count: 0,
      partial_count: 0,
      missed_count: 1,
    },
    {
      target_id: "comfyui-1",
      trial_count: 1,
      identified_count: 0,
      partial_count: 1,
      missed_count: 0,
    },
  ],
  trials: [
    trial("comfyui-1", "run-a", "trial-a", "proj-comfyui"),
    trial("white-jotter-1", "run-b", "trial-b", "proj-jotter"),
  ],
  versions: [],
  coverage: {
    targets: { tested: 2, with_identified: 0, without_identified: 2 },
    vulnerabilities: { total: 0, found: 0, not_found: 0, partial: 0 },
  },
  successes: [],
  degraded_trials: [],
  unassigned_saved_data: [
    { project_id: "orphan-project", status: "available", hunting: 3, skills: 1 },
  ],
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

test("targetCatalog orders targets by target_id", () => {
  const ordered = targetCatalog(SNAPSHOT).map((entry) => entry.target_id)
  expect(ordered).toEqual(["comfyui-1", "white-jotter-1"])
})

test("the home lists one row per Target with counts and canonical links", async () => {
  stubCatalog(json({ projects: [] }), json(SNAPSHOT))
  render(
    <MemoryRouter>
      <ProjectsPage />
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getByText("comfyui-1")).toBeDefined())

  const catalog = document.querySelector(".project-catalog") as HTMLElement
  const catalogRows = [...catalog.children] as HTMLElement[]
  expect(catalogRows).toHaveLength(2)

  const linkFor = (targetId: string) =>
    screen.getByRole("link", { name: targetId }).getAttribute("href")
  expect(linkFor("comfyui-1")).toBe("/targets/comfyui-1")
  expect(linkFor("white-jotter-1")).toBe("/targets/white-jotter-1")

  // The first row's summary carries the outcome counts, and the page never
  // renders the internal project_id as a primary row.
  const firstRow = catalogRows[0]
  expect(within(firstRow).getByText(/1 trial/)).toBeDefined()
  expect(within(firstRow).getByText(/1 partial/)).toBeDefined()
  expect(screen.queryByText("proj-comfyui")).toBeNull()
})

test("the target catalog renders when the live runtime is unavailable", async () => {
  stubCatalog(json({ detail: "unavailable" }, 503), json(SNAPSHOT))
  render(
    <MemoryRouter>
      <ProjectsPage />
    </MemoryRouter>,
  )

  await waitFor(() =>
    expect(screen.getByText(/live runtime unavailable/i)).toBeDefined(),
  )
  expect(screen.getByRole("link", { name: "comfyui-1" })).toBeDefined()
  expect(screen.queryByRole("alert")).toBeNull()
})

test("unassigned saved data merges raw-only dirs with live-only projects", async () => {
  stubCatalog(
    json({
      projects: [
        { project_id: "live-only", name: "Live Only", created_at: "2024-01-01T00:00:00+00:00" },
        { project_id: "proj-comfyui", name: "Proven", created_at: "2024-01-01T00:00:00+00:00" },
      ],
    }),
    json(SNAPSHOT),
  )
  render(
    <MemoryRouter>
      <ProjectsPage />
    </MemoryRouter>,
  )

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Unassigned saved data" })).toBeDefined(),
  )

  const section = screen
    .getByRole("heading", { name: "Unassigned saved data" })
    .closest("section")!
  // The backend raw-only directory and the live-only project both appear; the
  // project proven by a Trial does not.
  expect(within(section).getByText("orphan-project")).toBeDefined()
  expect(within(section).getByText("live-only")).toBeDefined()
  expect(within(section).queryByText("proj-comfyui")).toBeNull()
  // No fabricated Trial link inside the diagnostic section.
  expect(within(section).queryAllByRole("link")).toHaveLength(0)
})

test("unassignedSavedData is empty when every project is proven", () => {
  expect(unassignedSavedData([], { ...SNAPSHOT, unassigned_saved_data: [] })).toEqual([])
})
