import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
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
  // Exactly one inventory request; no detail or content fetch.
  expect(calls).toHaveLength(1)
  expect(calls[0]).toBe("/trials/t/r/trial-1/resolved-artifacts")
})

test("links each entry through the canonical detail path", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory())]])

  const { container } = renderSection()

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Hunting" })).toBeDefined(),
  )
  expandAll(container)
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
  const body = section.querySelector(":scope > .project-artifacts-group-body")
  const entries = body
    ? [...body.querySelectorAll(":scope > ul > li > a")].map((anchor) => anchor.textContent ?? "")
    : []
  const rows: Array<[string, string[]]> = [[label, entries]]
  if (body) {
    for (const child of body.querySelectorAll(":scope > section")) rows.push(...groupTree(child))
  }
  return rows
}

function testSpecTree(container: HTMLElement): Array<[string, string[]]> {
  const section = container.querySelector('section[aria-label="Test specs"]')
  return section ? groupTree(section) : []
}

function podExportsTree(container: HTMLElement): Array<[string, string[]]> {
  const section = container.querySelector('section[aria-label="Pod exports"]')
  return section ? groupTree(section) : []
}

function toggleStates(container: HTMLElement): Record<string, string> {
  const states: Record<string, string> = {}
  for (const section of container.querySelectorAll("section.project-artifacts-group")) {
    const label = section.getAttribute("aria-label") ?? ""
    const button = section.querySelector(".project-artifacts-group-head > button")
    states[label] = button?.getAttribute("aria-expanded") ?? "missing"
  }
  return states
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

  const { container } = renderSection()

  await waitFor(() =>
    expect(container.querySelector('section[aria-label="Test specs"]')).not.toBeNull(),
  )
  // It stays in its fault group (not a side) and keeps a working detail link.
  expect(testSpecTree(container)).toContainEqual([
    "FaultA",
    ["hunting/hunter/test-specs/FaultA/notes/odd.yaml"],
  ])
  const anchor = [...container.querySelectorAll(".project-artifact-entries a")].find(
    (item) => item.textContent === "hunting/hunter/test-specs/FaultA/notes/odd.yaml",
  )
  expect(anchor?.getAttribute("href")).toBe("/targets/t/trials/r/trial-1/artifacts/odd")
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

// --- PodExport outcome grouping -------------------------------------------------

function podArtifact(
  kind: ProjectArtifactEntry["kind"],
  id: string,
  spec: string,
  sub: string,
): ProjectArtifactEntry {
  return entry({
    artifact_id: id,
    kind,
    relative_path: `hunting/test-executor-pod/${spec}/${sub}`,
    sha256: `sha-${id}`,
  })
}
function podExport(id: string, spec: string): ProjectArtifactEntry {
  return podArtifact("pod_export", id, spec, `${id}.yaml`)
}
function podLog(id: string, spec: string): ProjectArtifactEntry {
  return podArtifact("experiment_log", id, spec, `experiment-log/${id}.yaml`)
}
function podVariant(id: string, spec: string): ProjectArtifactEntry {
  return podArtifact("pod_variant", id, spec, `variants/${id}.yaml`)
}
function podSpecsGroup(specs: Array<[string, ProjectArtifactEntry[]]>): ProjectArtifactGroup {
  return group({
    key: "pod-executions",
    label: "Pod executions",
    children: specs.map(([spec, entries]) =>
      group({ key: `pod-executions/${spec}`, label: spec, entries }),
    ),
  })
}

function podOutcomeDetail(entry: ProjectArtifactEntry, reason: string | null): unknown {
  return {
    entry,
    preview: {
      text: "raw",
      parsed: reason === null ? { verdict: "unsuccessful" } : { verdict: "unsuccessful", evidence: { terminal_reason: reason } },
      truncated: false,
      parse_error: null,
    },
    content_url: "/never-fetched",
  }
}

function podFetch(
  body: unknown,
  handler: (id: string) => Response,
): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    calls.push(url)
    if (url.endsWith("/resolved-artifacts")) return json(body)
    return handler(url.split("/").pop() ?? "")
  }) as typeof fetch
  return calls
}

test("groups pod exports by outcome and keeps log and variant per spec", async () => {
  const x1 = podExport("x1", "alpha")
  const l1 = podLog("l1", "alpha")
  const v1 = podVariant("v1", "alpha")
  const x2 = podExport("x2", "beta")
  const l2 = podLog("l2", "beta")
  const body = inventory({ groups: [podSpecsGroup([["alpha", [x1, l1, v1]], ["beta", [x2, l2]]])] })
  const reasons: Record<string, string> = { x1: "symptom-confirmed", x2: "space-exhausted" }

  podFetch(body, (id) => {
    const entry = [x1, x2].find((item) => item.artifact_id === id)!
    return json(podOutcomeDetail(entry, reasons[id]))
  })
  const { container } = renderSection()

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Symptom confirmed" })).toBeDefined(),
  )
  expandAll(container)
  expect(screen.getByRole("heading", { name: "Pod executions" })).toBeDefined()
  expect(screen.getByRole("heading", { name: "Space exhausted" })).toBeDefined()
  // Log and variant stay in their per-spec groups, with unchanged links.
  expect(screen.getByRole("heading", { name: "alpha" })).toBeDefined()
  expect(screen.getByRole("link", { name: l1.relative_path }).getAttribute("href")).toBe(
    "/targets/t/trials/r/trial-1/artifacts/l1",
  )
  expect(screen.getByRole("link", { name: v1.relative_path })).toBeDefined()
  expect(screen.getByRole("link", { name: l2.relative_path })).toBeDefined()
  // Exports moved under their outcome, links preserved.
  expect(screen.getByRole("link", { name: x1.relative_path }).getAttribute("href")).toBe(
    "/targets/t/trials/r/trial-1/artifacts/x1",
  )
  expect(screen.getByRole("link", { name: x2.relative_path })).toBeDefined()
})

test("keeps every export visible while its outcome is still loading", async () => {
  const x1 = podExport("x1", "alpha")
  const body = inventory({ groups: [podSpecsGroup([["alpha", [x1]]])] })
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith("/resolved-artifacts")) return json(body)
    return await new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), {
        once: true,
      })
    })
  }) as typeof fetch

  const { container } = renderSection()

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Classificazione in corso" })).toBeDefined(),
  )
  expandAll(container)
  expect(screen.getByRole("link", { name: x1.relative_path })).toBeDefined()
})

test("an outcome error never hides an export, log, or variant", async () => {
  const x1 = podExport("x1", "alpha")
  const l1 = podLog("l1", "alpha")
  const body = inventory({ groups: [podSpecsGroup([["alpha", [x1, l1]]])] })
  podFetch(body, () => json({ detail: "artifact_missing" }, 409))

  const { container } = renderSection()

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Esito non disponibile" })).toBeDefined(),
  )
  expandAll(container)
  expect(screen.getByRole("link", { name: x1.relative_path })).toBeDefined()
  expect(screen.getByRole("link", { name: l1.relative_path })).toBeDefined()
})

// --- collapsible artifact groups -------------------------------------------------

function groupSection(label: string): HTMLElement {
  // The section headings ("Hunting"/"Skills") share names with some groups, so
  // pick the heading that belongs to an artifact-group section.
  for (const heading of screen.getAllByRole("heading", { name: label })) {
    const section = heading.closest("section.project-artifacts-group")
    if (section) return section as HTMLElement
  }
  throw new Error(`no group section for ${label}`)
}

function toggleOf(label: string): HTMLButtonElement {
  const button = groupSection(label).querySelector<HTMLButtonElement>(
    ".project-artifacts-group-head > button",
  )
  if (!button) throw new Error(`no toggle for ${label}`)
  return button
}

function bodyOf(label: string): HTMLElement {
  const body = groupSection(label).querySelector<HTMLElement>(".project-artifacts-group-body")
  if (!body) throw new Error(`no body for ${label}`)
  return body
}

function expandAll(container: HTMLElement): void {
  for (let pass = 0; pass < 20; pass += 1) {
    const closed = [...container.querySelectorAll<HTMLButtonElement>('button[aria-expanded="false"]')]
    if (closed.length === 0) return
    for (const button of closed) fireEvent.click(button)
  }
}

test("top-level groups start open and their subgroups start closed", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory())]])
  renderSection()
  await waitFor(() => expect(screen.getByRole("heading", { name: "Hunt configs" })).toBeDefined())

  expect(toggleOf("Hunt configs").getAttribute("aria-expanded")).toBe("true")
  expect(toggleOf("Produced").getAttribute("aria-expanded")).toBe("false")
  // The collapsed subgroup's entry is not in the accessibility tree.
  expect(
    screen.queryByRole("link", { name: "hunting/orchestration/hunt_configs/produced/prod.yaml" }),
  ).toBeNull()
})

test("the toggle exposes aria-controls to a unique, stable body id", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory())]])
  const { container } = renderSection()
  await waitFor(() => expect(screen.getByRole("heading", { name: "Hunt configs" })).toBeDefined())

  const ids = [...container.querySelectorAll<HTMLElement>(".project-artifacts-group-body")].map(
    (body) => body.id,
  )
  expect(ids.every((id) => id.length > 0)).toBe(true)
  expect(new Set(ids).size).toBe(ids.length)

  // Every group's toggle points at its own body, whether or not it is open.
  const sections = [...container.querySelectorAll("section.project-artifacts-group")]
  expect(sections.length).toBeGreaterThan(3)
  for (const section of sections) {
    const button = section.querySelector(".project-artifacts-group-head > button")
    const body = section.querySelector<HTMLElement>(".project-artifacts-group-body")
    expect(button?.getAttribute("aria-controls")).toBe(body?.id)
  }
})

test("click, Enter, and Space all toggle the group", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory())]])
  renderSection()
  await waitFor(() => expect(screen.getByRole("heading", { name: "Hunt configs" })).toBeDefined())

  const button = toggleOf("Hunt configs")
  expect(button.getAttribute("aria-expanded")).toBe("true")

  fireEvent.click(button)
  expect(button.getAttribute("aria-expanded")).toBe("false")

  fireEvent.keyDown(button, { key: "Enter" })
  expect(button.getAttribute("aria-expanded")).toBe("true")

  fireEvent.keyDown(button, { key: " " })
  expect(button.getAttribute("aria-expanded")).toBe("false")
})

test("a collapsed group hides its entries and its subgroups from the keyboard", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory())]])
  renderSection()
  await waitFor(() => expect(screen.getByRole("heading", { name: "Hunt configs" })).toBeDefined())

  // Open the subgroup so its entry is reachable, then close the parent.
  fireEvent.click(toggleOf("Produced"))
  expect(
    screen.getByRole("link", { name: "hunting/orchestration/hunt_configs/produced/prod.yaml" }),
  ).toBeDefined()

  fireEvent.click(toggleOf("Hunt configs"))
  expect(bodyOf("Hunt configs").hasAttribute("hidden")).toBe(true)
  expect(
    screen.queryByRole("link", { name: "hunting/orchestration/hunt_configs/produced/prod.yaml" }),
  ).toBeNull()
  expect(screen.queryByRole("heading", { name: "Produced" })).toBeNull()
})

test("closing and reopening a parent keeps its children's choices", async () => {
  routeFetch([["/resolved-artifacts", () => json(inventory())]])
  renderSection()
  await waitFor(() => expect(screen.getByRole("heading", { name: "authn" })).toBeDefined())

  fireEvent.click(toggleOf("authn"))
  fireEvent.click(toggleOf("Procedure"))
  expect(toggleOf("Procedure").getAttribute("aria-expanded")).toBe("true")

  fireEvent.click(toggleOf("authn"))
  fireEvent.click(toggleOf("authn"))
  expect(toggleOf("Procedure").getAttribute("aria-expanded")).toBe("true")
})

test("a refresh with new instances of the same tree keeps the choices", async () => {
  vi.useFakeTimers()
  let body: unknown = inventory()
  routeFetch([["/resolved-artifacts", () => json(body)]])
  const { container } = renderSection()
  await act(async () => {})
  fireEvent.click(toggleOf("Hunt configs"))
  expect(toggleOf("Hunt configs").getAttribute("aria-expanded")).toBe("false")

  body = inventory()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })
  expect(toggleOf("Hunt configs").getAttribute("aria-expanded")).toBe("false")
  expect(container.querySelectorAll('button[aria-expanded="false"]').length).toBeGreaterThan(0)
})

test("a new group follows the default for its depth and the counts update", async () => {
  vi.useFakeTimers()
  let body: unknown = inventory()
  routeFetch([["/resolved-artifacts", () => json(body)]])
  renderSection()
  await act(async () => {})

  body = inventory({
    groups: [
      group({
        key: "hunt-configs",
        label: "Hunt configs",
        children: [
          group({
            key: "hunt-configs/produced",
            label: "Produced",
            entries: [HUNTING_ENTRY],
            children: [
              group({
                key: "hunt-configs/produced/extra",
                label: "Extra",
                entries: [
                  entry({
                    artifact_id: "h3",
                    relative_path: "hunting/orchestration/hunt_configs/produced/extra.yaml",
                  }),
                ],
              }),
            ],
          }),
        ],
      }),
    ],
  })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  // Open the parent so the new subgroup is reachable, then read its default.
  fireEvent.click(toggleOf("Produced"))
  expect(toggleOf("Extra").getAttribute("aria-expanded")).toBe("false")
  const count = groupSection("Hunt configs").querySelector(
    ".project-artifacts-group-head .project-artifacts-group-count",
  )
  expect(count?.textContent).toBe("2")
})

test("the PodExport classification never resets an open/closed choice", async () => {
  const x1 = podExport("x1", "alpha")
  const body = inventory({ groups: [podSpecsGroup([["alpha", [x1, podLog("l1", "alpha")]]])] })
  podFetch(body, () => json(podOutcomeDetail(x1, "symptom-confirmed")))
  renderSection()

  await waitFor(() => expect(screen.getByRole("heading", { name: "Symptom confirmed" })).toBeDefined())
  fireEvent.click(toggleOf("Pod executions"))
  expect(toggleOf("Pod executions").getAttribute("aria-expanded")).toBe("false")

  // Classification keeps running and later re-renders must not reset the choice.
  await waitFor(() => expect(screen.getByRole("heading", { name: "Symptom confirmed" })).toBeDefined())
  expect(toggleOf("Pod executions").getAttribute("aria-expanded")).toBe("false")
})

test("every artifact is reachable once the groups are open", async () => {
  const x1 = podExport("x1", "alpha")
  const body = inventory({
    groups: [
      testSpecsGroup(),
      podSpecsGroup([["alpha", [x1, podLog("l1", "alpha")]]]),
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
  })
  podFetch(body, (id) => json(podOutcomeDetail(x1, "symptom-confirmed")))
  const { container } = renderSection()
  await waitFor(() => expect(screen.getByRole("heading", { name: "Test specs" })).toBeDefined())

  expandAll(container)

  const paths = [...container.querySelectorAll(".project-artifact-entries a")].map(
    (anchor) => anchor.textContent ?? "",
  )
  const expected = new Set([
    "hunting/hunter/test-specs/FaultA/produced/a-prod.yaml",
    "hunting/hunter/test-specs/FaultA/consumed/a-cons.yaml",
    "hunting/hunter/test-specs/FaultB/produced/b-prod.yaml",
    x1.relative_path,
    "hunting/test-executor-pod/alpha/experiment-log/l1.yaml",
    "skills/authn/SKILL.md",
  ])
  expect(new Set(paths)).toEqual(expected)
  expect(screen.getByRole("link", { name: "skills/authn/SKILL.md" })).toBeDefined()
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

function coherenceGroups(): ProjectArtifactGroup[] {
  return [
    testSpecsGroup(),
    podSpecsGroup([["alpha", [podExport("cx1", "alpha"), podLog("cl1", "alpha")]]]),
  ]
}

function stubCoherenceFetch(): void {
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    if (url.endsWith("/snapshot")) return json(coherenceSnapshot())
    if (url.endsWith("/resolved-artifacts")) return json(inventory({ groups: coherenceGroups() }))
    if (url.includes("/resolved-artifacts/")) {
      const id = url.split("/").pop() ?? ""
      return json(podOutcomeDetail(podExport(id, "alpha"), "symptom-confirmed"))
    }
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
  await waitFor(() =>
    expect(inline.container.querySelector('section[aria-label="Pod exports"]')).not.toBeNull(),
  )
  const inlineTree = testSpecTree(inline.container)
  const inlinePod = podExportsTree(inline.container)
  const inlineToggles = toggleStates(inline.container)
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
  await waitFor(() =>
    expect(page.container.querySelector('section[aria-label="Pod exports"]')).not.toBeNull(),
  )
  const pageTree = testSpecTree(page.container)
  const pagePod = podExportsTree(page.container)
  const pageToggles = toggleStates(page.container)

  expect(inlineTree).toEqual(pageTree)
  expect(inlineTree.map(([label]) => label)).toContain("Consumed")
  expect(inlinePod).toEqual(pagePod)
  expect(inlinePod.map(([label]) => label)).toContain("Symptom confirmed")
  // The inline workspace and the standalone page share the same disclosure state.
  expect(inlineToggles).toEqual(pageToggles)
  expect(inlineToggles["Test specs"]).toBe("true")
  expect(inlineToggles["FaultA"]).toBe("false")
})


test("labels current-only files and leaves captured files unlabelled", async () => {
  const captured = entry({
    artifact_id: "cap",
    relative_path: "hunting/orchestration/hunt_configs/produced/captured.yaml",
    origin: "captured",
  })
  const current = entry({
    artifact_id: "cur",
    relative_path: "hunting/orchestration/hunt_configs/produced/current.yaml",
    origin: "current",
  })
  routeFetch([
    [
      "/resolved-artifacts",
      () =>
        json(
          inventory({
            source: "trial_snapshot",
            groups: [
              group({
                key: "hunt-configs",
                label: "Hunt configs",
                entries: [captured, current],
              }),
            ],
          }),
        ),
    ],
  ])

  const { container } = renderSection()

  await waitFor(() =>
    expect(container.querySelectorAll(".project-artifact-entries li")).toHaveLength(2),
  )
  // The inventory is labelled as captured with the Trial...
  expect(container.querySelector(".artifact-source")?.textContent).toBe(
    "Captured with Trial",
  )
  // ...and only the current-only entry carries the provenance marker.
  const markers = [...container.querySelectorAll(".project-artifact-origin")]
  expect(markers).toHaveLength(1)
  expect(markers[0].textContent).toBe("Current project file")
  const items = [...container.querySelectorAll<HTMLElement>(".project-artifact-entries li")]
  const capturedItem = items.find((li) => li.textContent?.includes("captured.yaml"))
  const currentItem = items.find((li) => li.textContent?.includes("current.yaml"))
  expect(capturedItem?.querySelector(".project-artifact-origin")).toBeNull()
  expect(currentItem?.querySelector(".project-artifact-origin")).not.toBeNull()
})


test("warns when the current source fails but keeps the stored artifacts", async () => {
  const stored = entry({
    artifact_id: "cap",
    relative_path: "hunting/orchestration/hunt_configs/produced/captured.yaml",
    origin: "captured",
  })
  routeFetch([
    [
      "/resolved-artifacts",
      () =>
        json(
          inventory({
            source: "trial_snapshot",
            issues: [{ source: "project_storage", reason: "artifact_unsafe" }],
            groups: [
              group({
                key: "hunt-configs",
                label: "Hunt configs",
                entries: [stored],
              }),
            ],
          }),
        ),
    ],
  ])

  const { container } = renderSection()

  const warning = await screen.findByRole("status")
  expect(warning.textContent).toContain(
    "Artifact correnti non consultabili (artifact_unsafe)",
  )
  expect(warning.textContent).toContain("mostrati gli artifact salvati disponibili")
  // The stored artifact stays visible and linkable.
  const link = container.querySelector(".project-artifact-entries a")
  expect(link?.textContent).toContain("captured.yaml")
})


test("shows no current-source warning for a clean inventory", async () => {
  routeFetch([
    ["/resolved-artifacts", () => json(inventory({ source: "trial_snapshot", issues: [] }))],
  ])

  renderSection()

  await waitFor(() =>
    expect(document.querySelector(".artifact-source")).not.toBeNull(),
  )
  expect(screen.queryByText(/Artifact correnti non consultabili/)).toBeNull()
})


test("removes the warning once the current source is readable again", async () => {
  vi.useFakeTimers()
  let body: ResolvedArtifactInventory = inventory({
    source: "trial_snapshot",
    issues: [{ source: "project_storage", reason: "artifact_unsafe" }],
  })
  routeFetch([["/resolved-artifacts", () => json(body)]])
  renderSection()

  await act(async () => {})
  expect(screen.getByText(/Artifact correnti non consultabili/)).toBeDefined()

  body = inventory({ source: "trial_snapshot", issues: [] })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })

  expect(screen.queryByText(/Artifact correnti non consultabili/)).toBeNull()
})
