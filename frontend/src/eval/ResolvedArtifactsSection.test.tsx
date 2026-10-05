import { act, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, expect, test, vi } from "vitest"
import { EvalDataProvider } from "./EvalDataProvider"
import { ProjectArtifactsPage } from "./ProjectArtifactsPage"
import { ResolvedArtifactsSection } from "./ResolvedArtifactsSection"
import { TrialSection } from "./TrialSection"
import type {
  EvalSnapshot,
  EvalTrial,
  ProjectArtifactEntry,
  ProjectArtifactGroup,
  ResolvedArtifactInventory,
} from "./types"

function entry(overrides: Partial<ProjectArtifactEntry> = {}): ProjectArtifactEntry {
  return {
    artifact_id: "id",
    category: "hunting",
    kind: "hunt_config",
    relative_path: "hunting/x.yaml",
    media_type: "application/yaml",
    size_bytes: 1,
    sha256: "digest",
    representation: "yaml",
    ...overrides,
  }
}

function group(overrides: Partial<ProjectArtifactGroup> = {}): ProjectArtifactGroup {
  return {
    key: "group",
    label: "Group",
    category: "hunting",
    entries: [],
    children: [],
    ...overrides,
  }
}

const HUNTING_ENTRY = entry({
  artifact_id: "h1",
  relative_path: "hunting/orchestration/hunt_configs/produced/prod.yaml",
  size_bytes: 12,
})

const SKILL_ENTRY = entry({
  artifact_id: "s1",
  category: "skill",
  kind: "skill_procedure",
  relative_path: "skills/authn/SKILL.md",
  media_type: "text/markdown",
  representation: "markdown",
})

function inventory(
  overrides: Partial<ResolvedArtifactInventory> = {},
): ResolvedArtifactInventory {
  return {
    status: "available",
    source: "project_storage",
    project_id: "p1",
    fallback_reason: null,
    groups: [
      group({
        key: "hunt-configs",
        label: "Hunt configs",
        children: [
          group({ key: "hunt-configs/produced", label: "Produced", entries: [HUNTING_ENTRY] }),
        ],
      }),
      group({
        key: "skills",
        label: "Skills",
        category: "skill",
        children: [
          group({
            key: "skills/authn",
            label: "authn",
            category: "skill",
            children: [
              group({
                key: "skills/authn/procedure",
                label: "Procedure",
                category: "skill",
                entries: [SKILL_ENTRY],
              }),
            ],
          }),
        ],
      }),
    ],
    ...overrides,
  } as ResolvedArtifactInventory
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function routeFetch(routes: Array<[string, () => Response | Promise<Response>]>): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    for (const [needle, handler] of routes) {
      if (url.includes(needle)) return handler()
    }
    throw new Error(`unexpected fetch: ${url}`)
  }) as typeof fetch
  return calls
}

afterEach(() => {
  vi.useRealTimers()
})

const POLL = 15_000

function renderSection() {
  return render(
    <MemoryRouter>
      <ResolvedArtifactsSection
        targetId="t"
        targetRunId="r"
        trialId="trial-1"
        detailPath={(artifactId) => `/targets/t/trials/r/trial-1/artifacts/${artifactId}`}
      />
    </MemoryRouter>,
  )
}

test("loads one resolved inventory and renders both groups with a source note", async () => {
  const calls = routeFetch([
    ["/resolved-artifacts", () => json(inventory())],
  ])

  renderSection()

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expect(screen.getByRole("heading", { name: "Skills", level: 2 })).toBeDefined()
  expect(screen.getByText("Saved for project")).toBeDefined()
  expect(screen.getByRole("heading", { name: "Produced" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Procedure" })).toBeDefined()
  // Exactly one inventory request; no detail or content fetch.
  expect(calls).toHaveLength(1)
  expect(calls[0]).toBe("/trials/t/r/trial-1/resolved-artifacts")
})

test("links each entry through the canonical detail path", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory())]])

  renderSection()

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expect(
    screen
      .getByRole("link", { name: "hunting/orchestration/hunt_configs/produced/prod.yaml" })
      .getAttribute("href"),
  ).toBe("/targets/t/trials/r/trial-1/artifacts/h1")
  expect(
    screen.getByRole("link", { name: "skills/authn/SKILL.md" }).getAttribute("href"),
  ).toBe("/targets/t/trials/r/trial-1/artifacts/s1")
})

test("a zero-entry readable inventory shows both explicit empty states", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory({ groups: [] }))]])

  renderSection()

  await waitFor(() => expect(screen.getByText("No Hunting artifacts")).toBeDefined())
  expect(screen.getByText("No Skill artifacts")).toBeDefined()
  expect(screen.queryByText(/unavailable/i)).toBeNull()
})

test("labels a captured inventory as captured with the trial", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory({ source: "trial_snapshot" }))]])

  renderSection()

  await waitFor(() => expect(screen.getByText("Captured with Trial")).toBeDefined())
  expect(screen.queryByText("Saved for project")).toBeNull()
})

test("an unavailable inventory shows a notice with no groups", async () => {
  routeFetch([
    [
      "/resolved-artifacts",
      () =>
        json({
          status: "unavailable",
          source: "project_storage",
          project_id: "p1",
          fallback_reason: null,
          reason: "project_artifacts_unavailable",
          groups: [],
        }),
    ],
  ])

  renderSection()

  await waitFor(() =>
    expect(screen.getByText(/project_artifacts_unavailable/)).toBeDefined(),
  )
  expect(screen.queryByRole("heading", { name: "Hunting" })).toBeNull()
  expect(screen.queryByRole("heading", { name: "Skills" })).toBeNull()
})

test("an inventory error stays confined to the artifacts section", async () => {
  routeFetch([["/resolved-artifacts", () => json({ detail: "artifact_unsafe" }, 409)]])

  renderSection()

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/artifact_unsafe/)
  expect(screen.queryByRole("heading", { name: "Hunting" })).toBeNull()
})

function extraEntry(): ProjectArtifactEntry {
  return entry({
    artifact_id: "h2",
    relative_path: "hunting/orchestration/hunt_configs/produced/fresh.yaml",
    size_bytes: 30,
  })
}

test("re-reads the inventory and shows an artifact added to the open Trial", async () => {
  vi.useFakeTimers()
  let body: unknown = inventory()
  routeFetch([["/resolved-artifacts", () => json(body)]])
  renderSection()

  await act(async () => {})
  expect(screen.getByText("Saved for project")).toBeDefined()
  expect(
    screen.queryByText("hunting/orchestration/hunt_configs/produced/fresh.yaml"),
  ).toBeNull()

  body = inventory({
    groups: [
      group({
        key: "hunt-configs",
        label: "Hunt configs",
        children: [
          group({
            key: "hunt-configs/produced",
            label: "Produced",
            entries: [HUNTING_ENTRY, extraEntry()],
          }),
        ],
      }),
    ],
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(
    screen.getByText("hunting/orchestration/hunt_configs/produced/fresh.yaml"),
  ).toBeDefined()
})

test("a failed inventory refresh keeps the previous inventory with a soft notice", async () => {
  vi.useFakeTimers()
  let failing = false
  globalThis.fetch = (async () =>
    failing
      ? json({ detail: "artifact_unsafe" }, 409)
      : json(inventory())) as typeof fetch
  renderSection()

  await act(async () => {})
  expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined()

  failing = true
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  // The previous inventory stays visible; the failure is a soft notice.
  expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined()
  expect(screen.queryByRole("alert")).toBeNull()
  expect(screen.getByText(/artifact_unsafe/)).toBeDefined()
})

// --- TestImplementationSpec produced/consumed ----------------------------------

function testSpec(id: string, side: "produced" | "consumed", fault: string): ProjectArtifactEntry {
  return entry({
    artifact_id: id,
    kind: "test_spec",
    relative_path: `hunting/hunter/test-specs/${fault}/${side}/${id}.yaml`,
  })
}

function testSpecsGroup(extra: ProjectArtifactEntry[] = []): ProjectArtifactGroup {
  return group({
    key: "test-specs",
    label: "Test specs",
    children: [
      group({
        key: "test-specs/FaultA",
        label: "FaultA",
        entries: [testSpec("a-prod", "produced", "FaultA"), testSpec("a-cons", "consumed", "FaultA"), ...extra],
      }),
      group({
        key: "test-specs/FaultB",
        label: "FaultB",
        entries: [testSpec("b-prod", "produced", "FaultB")],
      }),
    ],
  })
}

// The ordered (label, entry relative_paths) rows of the "Test specs" subtree.
function groupTree(section: Element): Array<[string, string[]]> {
  const label = section.getAttribute("aria-label") ?? ""
  const entries = [...section.querySelectorAll(":scope > ul > li > a")].map(
    (anchor) => anchor.textContent ?? "",
  )
  const rows: Array<[string, string[]]> = [[label, entries]]
  for (const child of section.querySelectorAll(":scope > section")) rows.push(...groupTree(child))
  return rows
}

function testSpecTree(container: HTMLElement): Array<[string, string[]]> {
  const section = container.querySelector('section[aria-label="Test specs"]')
  return section ? groupTree(section) : []
}

test("splits each fault's test specs into Produced and Consumed subgroups", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory({ groups: [testSpecsGroup()] }))]])

  const { container } = renderSection()

  await waitFor(() =>
    expect(container.querySelector('section[aria-label="Test specs"]')).not.toBeNull(),
  )
  expect(testSpecTree(container)).toEqual([
    ["Test specs", []],
    ["FaultA", []],
    ["Produced", ["hunting/hunter/test-specs/FaultA/produced/a-prod.yaml"]],
    ["Consumed", ["hunting/hunter/test-specs/FaultA/consumed/a-cons.yaml"]],
    ["FaultB", []],
    ["Produced", ["hunting/hunter/test-specs/FaultB/produced/b-prod.yaml"]],
  ])
})

test("keeps an unrecognized test-spec path visible and clickable in its fault", async () => {
  const odd = entry({
    artifact_id: "odd",
    kind: "test_spec",
    relative_path: "hunting/hunter/test-specs/FaultA/notes/odd.yaml",
  })
  routeFetch([
    ["/resolved-artifacts", () => json(inventory({ groups: [testSpecsGroup([odd])] }))],
  ])

  renderSection()

  const link = await screen.findByRole("link", {
    name: "hunting/hunter/test-specs/FaultA/notes/odd.yaml",
  })
  expect(link.getAttribute("href")).toBe("/targets/t/trials/r/trial-1/artifacts/odd")
  // It was not classified into a side, so FaultB's Produced is the only subgroup.
  expect(screen.getAllByRole("heading", { name: "Consumed", level: 5 })).toHaveLength(1)
})

test("a later inventory replaces the test-spec subgroups without stale entries", async () => {
  vi.useFakeTimers()
  let body: unknown = inventory({ groups: [testSpecsGroup()] })
  routeFetch([["/resolved-artifacts", () => json(body)]])
  renderSection()

  await act(async () => {})
  expect(
    screen.getByText("hunting/hunter/test-specs/FaultA/produced/a-prod.yaml"),
  ).toBeDefined()

  body = inventory({
    groups: [
      group({
        key: "test-specs",
        label: "Test specs",
        children: [
          group({
            key: "test-specs/FaultA",
            label: "FaultA",
            entries: [testSpec("a-prod2", "produced", "FaultA")],
          }),
        ],
      }),
    ],
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(screen.getByText("hunting/hunter/test-specs/FaultA/produced/a-prod2.yaml")).toBeDefined()
  expect(
    screen.queryByText("hunting/hunter/test-specs/FaultA/produced/a-prod.yaml"),
  ).toBeNull()
  expect(screen.queryByText("hunting/hunter/test-specs/FaultB/produced/b-prod.yaml")).toBeNull()
  expect(screen.getAllByText("hunting/hunter/test-specs/FaultA/produced/a-prod2.yaml")).toHaveLength(1)
})

// --- inline trial vs artifact page coherence -----------------------------------

function coherenceTrial(overrides: Partial<EvalTrial> = {}): EvalTrial {
  return {
    target_id: "t",
    target_run_id: "r",
    trial_id: "trial-1",
    instance_id: "inst-1",
    project_id: "p1",
    start_phase: "recon",
    terminal: "stopped",
    copied_at: "2024-01-01T00:00:00+00:00",
    phases: [],
    eval_sha: "sha-x",
    stack_fingerprint: "fp-x",
    verdicts: [],
    diagnoses: [],
    availability: "complete",
    reason: null,
    artifact_summary: { status: "project_artifacts_unavailable", hunting: 0, skills: 0 },
    project_graph_summary: {
      status: "project_graph_unavailable",
      nodes: 0,
      links: 0,
      captured_at: null,
    },
    ...overrides,
  }
}

function coherenceSnapshot(): EvalSnapshot {
  return {
    dataset: { id: "webexploitbench", name: "WebExploitBench" },
    summary: { targets: 1, trials: 1, identified: 0, partial: 0, missed: 0, degraded: 0 },
    targets: [],
    trials: [coherenceTrial()],
    versions: [],
    coverage: {
      targets: { tested: 0, with_identified: 0, without_identified: 0 },
      vulnerabilities: { total: 0, found: 0, not_found: 0, partial: 0 },
    },
    successes: [],
    degraded_trials: [],
  }
}

function stubCoherenceFetch(): void {
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    if (url.endsWith("/snapshot")) return json(coherenceSnapshot())
    if (url.includes("/resolved-artifacts")) return json(inventory({ groups: [testSpecsGroup()] }))
    // Every other trial section is a separate, safely-unavailable source.
    return json({
      status: "unavailable",
      source: null,
      project_id: null,
      captured_at: null,
      fallback_reason: null,
      reason: "not_captured",
      groups: [],
    })
  }) as typeof fetch
}

test("presents the same Test specs grouping inline and on the artifact page", async () => {
  stubCoherenceFetch()
  const inline = render(
    <MemoryRouter>
      <EvalDataProvider>
        <TrialSection trial={coherenceTrial()} />
      </EvalDataProvider>
    </MemoryRouter>,
  )
  await waitFor(() =>
    expect(inline.container.querySelector('section[aria-label="Test specs"]')).not.toBeNull(),
  )
  const inlineTree = testSpecTree(inline.container)
  inline.unmount()

  stubCoherenceFetch()
  const page = render(
    <MemoryRouter initialEntries={["/p/p1/evals/t/r/trial-1/artifacts"]}>
      <EvalDataProvider>
        <Routes>
          <Route
            path="/p/:projectId/evals/:targetId/:targetRunId/:trialId/artifacts"
            element={<ProjectArtifactsPage variant="workspace" />}
          />
        </Routes>
      </EvalDataProvider>
    </MemoryRouter>,
  )
  await waitFor(() =>
    expect(page.container.querySelector('section[aria-label="Test specs"]')).not.toBeNull(),
  )
  const pageTree = testSpecTree(page.container)

  expect(inlineTree).toEqual(pageTree)
  expect(inlineTree.map(([label]) => label)).toContain("Consumed")
})
