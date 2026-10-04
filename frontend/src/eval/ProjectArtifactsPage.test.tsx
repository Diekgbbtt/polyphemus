import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { Link, MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, expect, test } from "vitest"
import { App } from "../App"
import { EvalDataProvider } from "./EvalDataProvider"
import { ProjectArtifactsPage } from "./ProjectArtifactsPage"
import {
  artifactKey,
  artifactSections,
  groupLabel,
  kindLabel,
  representationLabel,
} from "./projectArtifacts"
import type {
  EvalSnapshot,
  EvalTrial,
  ProjectArtifactEntry,
  ProjectArtifactGroup,
  ResolvedArtifactInventory,
} from "./types"

// --- fixtures ------------------------------------------------------------------

function entry(overrides: Partial<ProjectArtifactEntry>): ProjectArtifactEntry {
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

function group(overrides: Partial<ProjectArtifactGroup>): ProjectArtifactGroup {
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
  kind: "hunt_config",
  relative_path: "hunting/orchestration/hunt_configs/produced/prod.yaml",
  size_bytes: 12,
})

const SKILL_ENTRY = entry({
  artifact_id: "s1",
  category: "skill",
  kind: "skill_procedure",
  relative_path: "skills/authn/SKILL.md",
  media_type: "text/markdown",
  size_bytes: 20,
  representation: "markdown",
})

const INVENTORY: ResolvedArtifactInventory = {
  status: "available",
  source: "project_storage",
  fallback_reason: null,
  project_id: "p1",
  groups: [
    group({
      key: "hunt-configs",
      label: "Hunt configs",
      children: [
        group({
          key: "hunt-configs/produced",
          label: "Produced",
          entries: [HUNTING_ENTRY],
        }),
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
}

function evalTrial(overrides: Partial<EvalTrial> = {}): EvalTrial {
  return {
    target_id: "t",
    target_run_id: "r",
    trial_id: "trial-1",
    instance_id: "inst-1",
    project_id: "p1",
    start_phase: "recon",
    terminal: "complete",
    copied_at: "2024-01-01T00:00:00+00:00",
    phases: [],
    eval_sha: "sha-x",
    stack_fingerprint: "fp-x",
    verdicts: [],
    diagnoses: [],
    availability: "complete",
    reason: null,
    artifact_summary: { status: "available", hunting: 1, skills: 1 },
    project_graph_summary: {
      status: "project_graph_unavailable",
      nodes: 0,
      links: 0,
      captured_at: null,
    },
    ...overrides,
  }
}

// The inventory shape the read API serves for one stopped-at-cap schema-v2
// Trial: hunting groups only, grouped exactly as `_build_groups` would.
const REAL_SHAPE_INVENTORY: ResolvedArtifactInventory = {
  status: "available",
  source: "project_storage",
  fallback_reason: null,
  project_id: "p1",
  groups: [
    group({
      key: "hunt-configs",
      label: "Hunt configs",
      children: [
        group({
          key: "hunt-configs/consumed",
          label: "Consumed",
          entries: [
            entry({
              artifact_id: "hc1",
              relative_path:
                "hunting/orchestration/hunt_configs/consumed/" +
                "AuthorizationSystem:__singleton___CWE-1220_IDOR.yaml",
            }),
          ],
        }),
      ],
    }),
    group({
      key: "test-specs",
      label: "Test specs",
      children: [
        group({
          key: "test-specs/demo-authz::CWE-1220::idor",
          label: "demo-authz::CWE-1220::idor",
          children: [
            group({
              key: "test-specs/demo-authz::CWE-1220::idor/consumed",
              label: "Consumed",
              entries: [
                entry({
                  artifact_id: "ts1",
                  kind: "test_spec",
                  relative_path:
                    "hunting/hunter/test-specs/demo-authz::CWE-1220::idor/consumed/anon-id.yaml",
                }),
              ],
            }),
          ],
        }),
      ],
    }),
    group({
      key: "pod-executions",
      label: "Pod executions",
      children: [
        group({
          key: "pod-executions/demo-authz-cwe1220-anon-id",
          label: "demo-authz-cwe1220-anon-id",
          entries: [
            entry({
              artifact_id: "pv1",
              kind: "pod_variant",
              relative_path:
                "hunting/test-executor-pod/demo-authz-cwe1220-anon-id/variants/v0.yaml",
            }),
            entry({
              artifact_id: "el1",
              kind: "experiment_log",
              relative_path:
                "hunting/test-executor-pod/demo-authz-cwe1220-anon-id/experiment-log/order-0.yaml",
            }),
          ],
        }),
      ],
    }),
  ],
}

function evalSnapshot(trials: EvalTrial[]): EvalSnapshot {
  return {
    dataset: { id: "webexploitbench", name: "WebExploitBench" },
    summary: { targets: 1, trials: trials.length, identified: 0, partial: 0, missed: 0, degraded: 0 },
    targets: [],
    trials,
    versions: [],
    coverage: {
      targets: { tested: 0, with_identified: 0, without_identified: 0 },
      vulnerabilities: { total: 0, found: 0, not_found: 0, partial: 0 },
    },
    successes: [],
    degraded_trials: [],
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function routeFetch(
  routes: Array<[string, () => Response | Promise<Response>]>,
): { calls: string[]; signals: AbortSignal[] } {
  const calls: string[] = []
  const signals: AbortSignal[] = []
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    calls.push(url)
    if (init?.signal) signals.push(init.signal as AbortSignal)
    for (const [needle, handler] of routes) {
      if (url.includes(needle)) return handler()
    }
    throw new Error(`unexpected fetch: ${url}`)
  }) as typeof fetch
  return { calls, signals }
}

function goto(path: string) {
  window.history.pushState({}, "", path)
  return render(<App />)
}

afterEach(() => {
  window.history.pushState({}, "", "/")
})

// --- pure helpers ---------------------------------------------------------------

test("artifactSections split hunting and skill preserving server order", () => {
  const reordered: ResolvedArtifactInventory = {
    ...INVENTORY,
    groups: [INVENTORY.groups[1], INVENTORY.groups[0]],
  }

  const sections = artifactSections(reordered.groups)

  expect(sections.map((section) => section.category)).toEqual(["hunting", "skill"])
  expect(sections[0].label).toBe("Hunting")
  expect(sections[1].label).toBe("Skills")
  expect(sections[0].groups.map((item) => item.key)).toEqual(["hunt-configs"])
  expect(sections[1].groups.map((item) => item.key)).toEqual(["skills"])
})

test("groupLabel falls back deterministically and keys stay stable", () => {
  expect(groupLabel(group({ key: "a/b/c", label: "" }))).toBe("c")
  expect(groupLabel(group({ key: "", label: "" }))).toBe("Artifacts")
  expect(groupLabel(group({ key: "k", label: "  Readable  " }))).toBe("Readable")
  expect(artifactKey(HUNTING_ENTRY)).toBe("h1")
})

test("kind and representation labels are readable with fallbacks", () => {
  expect(kindLabel("hunt_config")).toBe("Hunt config")
  expect(kindLabel("skill_procedure")).toBe("Procedure")
  expect(kindLabel("unknown_kind" as never)).toBe("unknown_kind")
  expect(representationLabel("markdown")).toBe("Markdown")
  expect(representationLabel("binary")).toBe("Binary")
})

// --- the inventory page ---------------------------------------------------------

test("renders the grouped inventory with entry metadata and links", async () => {
  const { calls } = routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expect(screen.getByRole("heading", { name: "Skills", level: 2 })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Hunt configs" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Produced" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "authn" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Procedure" })).toBeDefined()

  const link = screen.getByRole("link", {
    name: "hunting/orchestration/hunt_configs/produced/prod.yaml",
  })
  expect(link.getAttribute("href")).toBe("/p/p1/evals/t/r/trial-1/artifacts/h1")
  const item = link.closest("li") as HTMLElement
  expect(item.textContent).toContain("Hunt config")
  expect(item.textContent).toContain("YAML")
  expect(item.textContent).toContain("12")
  expect(item.textContent).toContain("h1")

  const skillLink = screen.getByRole("link", { name: "skills/authn/SKILL.md" })
  expect(skillLink.getAttribute("href")).toBe("/p/p1/evals/t/r/trial-1/artifacts/s1")

  // Only the list request: no detail and no content fetch here.
  expect(calls.filter((url) => url.includes("/resolved-artifacts"))).toHaveLength(1)
  expect(calls.some((url) => url.includes("/content"))).toBe(false)
})

test("renders a hunting-only real-shape inventory without skill artifacts", async () => {
  routeFetch([
    [
      "/snapshot",
      () =>
        json(
          evalSnapshot([
            evalTrial({
              artifact_summary: { status: "available", hunting: 21, skills: 0 },
            }),
          ]),
        ),
    ],
    ["/resolved-artifacts", () => json(REAL_SHAPE_INVENTORY)],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expect(screen.getByRole("heading", { name: "Hunt configs" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Test specs" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Pod executions" })).toBeDefined()
  expect(
    screen.getByRole("heading", { name: "demo-authz::CWE-1220::idor" }),
  ).toBeDefined()
  expect(screen.getAllByRole("heading", { name: "Consumed" }).length).toBeGreaterThan(0)

  const variant = screen.getByRole("link", {
    name: "hunting/test-executor-pod/demo-authz-cwe1220-anon-id/variants/v0.yaml",
  })
  expect(variant.closest("li")?.textContent).toContain("Pod variant")
  const log = screen.getByRole("link", {
    name: "hunting/test-executor-pod/demo-authz-cwe1220-anon-id/experiment-log/order-0.yaml",
  })
  expect(log.closest("li")?.textContent).toContain("Experiment log")

  // No skill artifact is catalogued: the section is present but empty.
  expect(screen.getByRole("heading", { name: "Skills", level: 2 })).toBeDefined()
  expect(screen.getByText("No Skill artifacts")).toBeDefined()
})

test("the workspace page keeps the trial identity visible", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expect(screen.getByText(/p1/)).toBeDefined()
  expect(screen.getAllByText(/trial-1/).length).toBeGreaterThan(0)
})

test("a readable but empty inventory shows both explicit empty states", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts", () => json({ ...INVENTORY, groups: [] })],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() => expect(screen.getByText("No Hunting artifacts")).toBeDefined())
  expect(screen.getByText("No Skill artifacts")).toBeDefined()
})

test("shows a loading state", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts", () => new Promise<Response>(() => {})],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() =>
    expect(screen.getByText(/Loading artifacts/i)).toBeDefined(),
  )
})

test("shows the API failure detail", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts", () => json({ detail: "artifact_unsafe" }, 409)],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/artifact_unsafe/)
})

test("an unavailable resolved inventory shows a notice", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial({
      artifact_summary: { status: "project_artifacts_unavailable", hunting: 0, skills: 0 },
    })]))],
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
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() =>
    expect(screen.getByText(/project_artifacts_unavailable/)).toBeDefined(),
  )
  expect(screen.queryByRole("heading", { name: "Hunting" })).toBeNull()
})

test("an unknown trial shows a generic not-found with no request", async () => {
  const { calls } = routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/p/p1/evals/t/r/missing/artifacts")

  await waitFor(() => expect(screen.getByText(/Trial not found/i)).toBeDefined())
  expect(calls.some((url) => url.includes("/artifacts"))).toBe(false)
})

test("a cross-project mismatch is not found and does not leak", async () => {
  const { calls } = routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial({ project_id: "p2" })]))],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() => expect(screen.getByText(/Trial not found/i)).toBeDefined())
  expect(screen.queryByText("p2")).toBeNull()
  expect(calls.some((url) => url.includes("/artifacts"))).toBe(false)
})

test("an inventory project id mismatch is a safe error without groups", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts", () => json({ ...INVENTORY, project_id: "someone-else" })],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts")

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/mismatch/i)
  expect(screen.queryByRole("heading", { name: "Hunting" })).toBeNull()
})

test("the compatible eval route links entries through evalPaths", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts", () => json(INVENTORY)],
  ])
  goto("/eval/trials/t/r/trial-1/project-artifacts")

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expect(
    screen
      .getByRole("link", { name: "hunting/orchestration/hunt_configs/produced/prod.yaml" })
      .getAttribute("href"),
  ).toBe("/eval/trials/t/r/trial-1/project-artifacts/h1")
})

test("aborts on route change and ignores a late response", async () => {
  let resolveFirst: ((response: Response) => void) | undefined
  const first = new Promise<Response>((resolve) => {
    resolveFirst = resolve
  })
  const { signals } = routeFetch([
    [
      "/snapshot",
      () =>
        json(
          evalSnapshot([
            evalTrial(),
            evalTrial({ trial_id: "trial-2" }),
          ]),
        ),
    ],
    ["/trial-1/resolved-artifacts", () => first],
    ["/trial-2/resolved-artifacts", () => json(INVENTORY)],
  ])

  function Harness() {
    return (
      <>
        <Link to="/p/p1/evals/t/r/trial-2/artifacts">next-trial</Link>
        <Routes>
          <Route
            path="/p/:projectId/evals/:targetId/:targetRunId/:trialId/artifacts"
            element={<ProjectArtifactsPage variant="workspace" />}
          />
        </Routes>
      </>
    )
  }

  render(
    <MemoryRouter initialEntries={["/p/p1/evals/t/r/trial-1/artifacts"]}>
      <EvalDataProvider>
        <Harness />
      </EvalDataProvider>
    </MemoryRouter>,
  )

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "next-trial" })).toBeDefined(),
  )
  fireEvent.click(screen.getByRole("link", { name: "next-trial" }))
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expect(signals[0].aborted).toBe(true)

  // The mock ignores the abort: its late response must not update the page.
  resolveFirst?.(
    json({
      ...INVENTORY,
      groups: [group({ key: "stale", label: "Stale group", entries: [] })],
    }),
  )
  await Promise.resolve()
  await Promise.resolve()
  expect(screen.queryByRole("heading", { name: "Stale group" })).toBeNull()
  expect(screen.getByRole("heading", { name: "Hunt configs" })).toBeDefined()
})
