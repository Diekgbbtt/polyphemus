import { render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { expect, test } from "vitest"
import { ProjectArtifactsBlock } from "./ProjectArtifactsBlock"

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

const ENTRY_HUNTING = {
  artifact_id: "h1",
  category: "hunting",
  kind: "hunt_config",
  relative_path: "hunting/orchestration/hunt_configs/produced/prod.yaml",
  media_type: "application/yaml",
  size_bytes: 2048,
  sha256: "0".repeat(64),
  representation: "yaml",
  origin: "current",
}

const ENTRY_SKILL = {
  artifact_id: "s1",
  category: "skill",
  kind: "skill",
  relative_path: "skills/authn/SKILL.md",
  media_type: "text/markdown",
  size_bytes: 512,
  sha256: "1".repeat(64),
  representation: "markdown",
  origin: "current",
}

const INVENTORY = {
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
      entries: [ENTRY_HUNTING],
      children: [],
    },
    {
      key: "skills",
      label: "Procedures",
      category: "skill",
      entries: [ENTRY_SKILL],
      children: [],
    },
  ],
}

function stub(body: unknown, status = 200): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    calls.push(String(input))
    return json(body, status)
  }) as typeof fetch
  return calls
}

function renderBlock(projectId = "proj-1") {
  return render(
    <MemoryRouter>
      <ProjectArtifactsBlock projectId={projectId} />
    </MemoryRouter>,
  )
}

test("lists the project's hunting and skill files, grouped and counted", async () => {
  stub(INVENTORY)
  renderBlock()

  await waitFor(() => expect(screen.getByText("Hunting")).toBeDefined())
  expect(screen.getByText("Skills")).toBeDefined()
  // Group label plus the number of files beneath it.
  const orchestration = screen.getByText("Orchestration").closest("li")!
  expect(within(orchestration).getByText("1")).toBeDefined()
  // Every file is named, with its kind, representation and size.
  expect(screen.getByText(/2\.0 KB/)).toBeDefined()
  expect(screen.getByText(/512 B/)).toBeDefined()
})

test("each file opens its own project-scoped detail, like a Trial's", async () => {
  stub(INVENTORY)
  renderBlock()

  const hunting = await screen.findByRole("link", {
    name: ENTRY_HUNTING.relative_path,
  })
  expect(hunting.getAttribute("href")).toBe("/p/proj-1/artifacts/h1")
  const skill = screen.getByRole("link", { name: ENTRY_SKILL.relative_path })
  expect(skill.getAttribute("href")).toBe("/p/proj-1/artifacts/s1")
})

test("an empty tree says so instead of looking broken", async () => {
  stub({ ...INVENTORY, groups: [] })
  renderBlock()

  expect(
    await screen.findByText(/no artifacts were saved for this project/i),
  ).toBeDefined()
  expect(screen.queryByText("Hunting")).toBeNull()
})

test("an unavailable inventory names the reason", async () => {
  stub({
    status: "unavailable",
    source: "project_storage",
    project_id: "proj-1",
    fallback_reason: null,
    reason: "project_data_unavailable",
    groups: [],
  })
  renderBlock()

  expect(
    await screen.findByText(/project artifacts unavailable \(project_data_unavailable\)/i),
  ).toBeDefined()
})

test("a failed read is stated, never rendered as an empty tree", async () => {
  stub({ detail: "boom" }, 500)
  renderBlock()

  expect(await screen.findByText(/project artifacts unavailable/i)).toBeDefined()
  expect(screen.queryByText(/no artifacts were saved/i)).toBeNull()
})

test("the request encodes the project id", async () => {
  const calls = stub(INVENTORY)
  renderBlock("proj/2")

  await waitFor(() => expect(calls.length).toBeGreaterThan(0))
  expect(calls[0]).toBe("/projects/proj%2F2/artifacts")
})
