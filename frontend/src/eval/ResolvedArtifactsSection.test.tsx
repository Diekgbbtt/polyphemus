import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, test } from "vitest"
import { ResolvedArtifactsSection } from "./ResolvedArtifactsSection"
import type {
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
