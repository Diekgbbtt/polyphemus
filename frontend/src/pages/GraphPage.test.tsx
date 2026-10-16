import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { expect, test, vi } from "vitest"
import type { AppState, ProjectUsage } from "../api/types"
import { GraphPage } from "./GraphPage"

// The canvas is not what these tests are about, and jsdom has no 2D context.
vi.mock("../graph/GraphCanvas", () => ({
  GraphCanvas: ({ nodes }: { nodes: Array<{ id: string }> }) => (
    <div data-testid="graph-canvas">{nodes.length}</div>
  ),
}))

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

const PROJECT = {
  project_id: "proj-1",
  name: "ComfyUI Target",
  created_at: "2024-01-01T00:00:00+00:00",
}

const GRAPH = {
  project_id: "proj-1",
  nodes: [{ id: "n1", name: "chunk-abc.min.js", type: "L1Unit", properties: {} }],
  links: [],
}

const USAGE: ProjectUsage = {
  project_id: "proj-1",
  context_tokens: { cached: 50, uncached: 75 },
  generated_tokens: { reasoning: 40, visible: 110 },
  total_tokens: 275,
  capped_tokens: 225,
  calls: 3,
  by_agent: {
    recon: {
      context_tokens: { cached: 50, uncached: 75 },
      generated_tokens: { reasoning: 40, visible: 110 },
      total_tokens: 275,
      capped_tokens: 225,
      calls: 3,
    },
  },
}

// The project's own Hunting/Skill tree, read with no Trial in the path.
const ARTIFACTS = {
  status: "available",
  source: "project_storage",
  project_id: "proj-1",
  fallback_reason: null,
  issues: [],
  groups: [
    {
      key: "hunting/orchestration",
      label: "Orchestration",
      category: "hunting",
      entries: [
        {
          artifact_id: "h1",
          category: "hunting",
          kind: "hunt_config",
          relative_path: "hunting/orchestration/hunt_configs/produced/prod.yaml",
          media_type: "application/yaml",
          size_bytes: 2048,
          sha256: "0".repeat(64),
          representation: "yaml",
          origin: "current",
        },
      ],
      children: [],
    },
  ],
}

const SETTINGS = {
  recon: {
    target_domain: "example.com",
    scope: { depth: 3 },
    deep_scan: true,
  },
}

const APP_STATE: AppState = {
  idle: false,
  projects: [
    {
      project_id: "proj-1",
      project_name: "ComfyUI Target",
      in_flight: true,
      recon: [
        {
          run_id: "recon-run-1",
          project_id: "proj-1",
          project_name: "ComfyUI Target",
          status: "running",
          liveness: "stalled",
          current_phase: 2,
          started_at: null,
          last_heartbeat_at: null,
          jobs: {
            total: 3,
            in_progress: 1,
            success: 1,
            degraded: 0,
            skipped: 0,
            failed: 1,
          },
        },
      ],
      analysis: [
        {
          analysis_run_id: "analysis-run-1",
          run_id: "recon-run-1",
          project_id: "proj-1",
          status: "draining",
          started_at: null,
        },
      ],
      hunting: [
        {
          hunting_run_id: "hunting-run-1",
          project_id: "proj-1",
          status: "running",
          started_at: null,
          finished_at: null,
        },
      ],
    },
  ],
}

const IDLE_APP_STATE: AppState = {
  idle: true,
  projects: [
    {
      project_id: "proj-1",
      project_name: "ComfyUI Target",
      in_flight: false,
      recon: [],
      analysis: [],
      hunting: [],
    },
  ],
}

// A per-path stub: the first matching needle wins, and anything unrouted reads
// as an explicit 404 rather than throwing inside the poller.
function stub(routes: Array<[string, () => Response]>): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    for (const [needle, handler] of routes) {
      if (url.includes(needle)) return handler()
    }
    return json({ detail: "not_found" }, 404)
  }) as typeof fetch
  return calls
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/p/proj-1"]}>
      <Routes>
        <Route path="/p/:projectId" element={<GraphPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function standardRoutes(
  graph: () => Response = () => json(GRAPH),
  usage: () => Response = () => json(USAGE),
  appState: () => Response = () => json(APP_STATE),
  settings: () => Response = () => json(SETTINGS),
): Array<[string, () => Response]> {
  return [
    ["/app-state", appState],
    ["/projects/proj-1/graph", graph],
    ["/projects/proj-1/usage", usage],
    ["/projects/proj-1/artifacts", () => json(ARTIFACTS)],
    ["/projects/proj-1/settings", settings],
    ["/projects", () => json({ projects: [PROJECT] })],
  ]
}

test("shows the project identity, its three run classes, the graph and counters", async () => {
  stub(standardRoutes())
  renderPage()

  // Identity comes from the project list, never invented.
  expect(await screen.findByRole("heading", { name: "ComfyUI Target" })).toBeDefined()
  expect(screen.getByText("2024-01-01T00:00:00+00:00")).toBeDefined()

  // Every in-flight class the platform expresses, with recon's liveness kept.
  expect(await screen.findByRole("region", { name: "recon runs" })).toBeDefined()
  expect(screen.getByRole("region", { name: "analysis runs" })).toBeDefined()
  expect(screen.getByRole("region", { name: "hunting runs" })).toBeDefined()
  expect(screen.getByText("recon-run-1")).toBeDefined()
  expect(screen.getByText("stalled")).toBeDefined()

  // The operator's stored configuration, read back verbatim.
  expect(await screen.findByText("target_domain")).toBeDefined()
  expect(screen.getByText("example.com")).toBeDefined()
  expect(screen.getByText("deep_scan")).toBeDefined()
  expect(screen.getByText("true")).toBeDefined()
  expect(screen.getByText('{"depth":3}')).toBeDefined()

  // The live graph of the project itself.
  expect(screen.getByText("Live project graph")).toBeDefined()
  expect(screen.getByTestId("graph-canvas")).toBeDefined()

  // The project's own produced files, listed without a Trial in the path.
  expect(
    await screen.findByText("hunting/orchestration/hunt_configs/produced/prod.yaml"),
  ).toBeDefined()

  // The cumulative counters.
  await waitFor(() =>
    expect(document.querySelector('[data-usage="total"]')?.textContent).toBe("275"),
  )
  expect(document.querySelector('[data-usage="cached"]')?.textContent).toBe("50")
  expect(document.querySelector('[data-usage="uncached"]')?.textContent).toBe("75")
  expect(document.querySelector('[data-usage="calls"]')?.textContent).toBe("3")
})

test("a project with no stored graph says so instead of failing", async () => {
  stub(standardRoutes(() => json({ detail: "unknown project" }, 404)))
  renderPage()

  expect(
    await screen.findByText(/no graph is stored for this project/i),
  ).toBeDefined()
  // A missing graph is an answer, not an error the reader must decode.
  expect(screen.queryByRole("alert")).toBeNull()
})

test("a real graph failure stays an accessible error", async () => {
  stub(standardRoutes(() => json({ detail: "boom" }, 500)))
  renderPage()

  const alert = await screen.findByRole("alert")
  expect(alert.textContent).toMatch(/graph error/i)
  expect(screen.queryByText(/no graph is stored for this project/i)).toBeNull()
})

test("says so when nothing is in flight", async () => {
  stub(standardRoutes(undefined, undefined, () => json(IDLE_APP_STATE)))
  renderPage()

  expect(await screen.findByText(/no runs in flight/i)).toBeDefined()
  expect(screen.queryByRole("region", { name: "recon runs" })).toBeNull()
})

test("an invalid usage body is unavailable, never zero", async () => {
  stub(
    standardRoutes(
      undefined,
      () => json({ project_id: "proj-1", total_tokens: "275" }),
    ),
  )
  renderPage()

  expect(await screen.findByText(/usage unavailable/i)).toBeDefined()
  expect(document.querySelector('[data-usage="total"]')).toBeNull()
})

test("a project with no stored configuration says so", async () => {
  stub(standardRoutes(undefined, undefined, undefined, () => json({ recon: {} })))
  renderPage()

  expect(
    await screen.findByText(/no settings are stored for this project/i),
  ).toBeDefined()
})

test("an invalid settings body is unavailable, never an empty configuration", async () => {
  stub(
    standardRoutes(undefined, undefined, undefined, () =>
      json({ recon: "nope" }),
    ),
  )
  renderPage()

  expect(await screen.findByText(/settings unavailable/i)).toBeDefined()
  expect(screen.queryByText(/no settings are stored/i)).toBeNull()
})

test("a project the agent does not know shows no configuration", async () => {
  stub(
    standardRoutes(undefined, undefined, undefined, () =>
      json({ detail: "unknown project" }, 404),
    ),
  )
  renderPage()

  expect(await screen.findByText(/settings unavailable/i)).toBeDefined()
})
