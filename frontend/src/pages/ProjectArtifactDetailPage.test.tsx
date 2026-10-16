import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { expect, test } from "vitest"
import { ProjectArtifactDetailPage } from "./ProjectArtifactDetailPage"

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

const ENTRY = {
  artifact_id: "h1",
  category: "hunting",
  kind: "hunt_config",
  relative_path: "hunting/orchestration/hunt_configs/produced/prod.yaml",
  media_type: "application/yaml",
  size_bytes: 32,
  sha256: "a".repeat(64),
  representation: "yaml",
  origin: "current",
}

const DETAIL = {
  entry: ENTRY,
  preview: { text: "kind: hunt-config\n", parsed: { kind: "hunt-config" }, truncated: false, parse_error: null },
  content_url: "ignored-by-the-client",
}

function stub(body: unknown, status = 200): string[] {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    calls.push(String(input))
    return json(body, status)
  }) as typeof fetch
  return calls
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/p/proj-1/artifacts/h1"]}>
      <Routes>
        <Route path="/p/:projectId/artifacts/:artifactId" element={<ProjectArtifactDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

test("shows the project artifact's metadata and its safe preview", async () => {
  stub(DETAIL)
  renderPage()

  await waitFor(() =>
    expect(screen.getByText(ENTRY.relative_path, { selector: "dd" })).toBeDefined(),
  )
  expect(screen.getByRole("heading", { name: "Artifact" })).toBeDefined()
  expect(screen.getByText(/project/)).toBeDefined()
  // The raw download is rebuilt from the digest, on the project's own route.
  const download = screen.getByRole("link", { name: /download raw/i })
  expect(download.getAttribute("href")).toBe(
    `/projects/proj-1/artifacts/h1/content?expected_sha256=${ENTRY.sha256}`,
  )
  // The breadcrumb leads back to the project, not to a Trial.
  const back = screen.getByRole("link", { name: "Project" })
  expect(back.getAttribute("href")).toBe("/p/proj-1")
  // The preview is rendered through the shared renderer.
  expect(screen.getByText(/hunt-config/)).toBeDefined()
})

test("a failing detail read is an accessible error", async () => {
  stub({ detail: "artifact_not_found" }, 404)
  renderPage()

  const alert = await screen.findByRole("alert")
  expect(alert.textContent).toMatch(/artifact load error/i)
})

test("a detail that names another artifact is refused", async () => {
  stub({ ...DETAIL, entry: { ...ENTRY, artifact_id: "other" } })
  renderPage()

  const alert = await screen.findByRole("alert")
  expect(alert.textContent).toMatch(/mismatch/i)
})
