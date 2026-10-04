import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { Link, MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, expect, test } from "vitest"
import { App } from "../App"
import { EvalDataProvider } from "./EvalDataProvider"
import { ProjectArtifactPage } from "./ProjectArtifactPage"
import { ProjectArtifactRenderer } from "./ProjectArtifactRenderers"
import type {
  EvalSnapshot,
  EvalTrial,
  ProjectArtifactDetail,
  ProjectArtifactEntry,
  ProjectArtifactPreview,
} from "./types"

// --- fixtures ------------------------------------------------------------------

function entry(overrides: Partial<ProjectArtifactEntry> = {}): ProjectArtifactEntry {
  return {
    artifact_id: "a1",
    category: "hunting",
    kind: "hunt_config",
    relative_path: "hunting/orchestration/hunt_configs/produced/x.yaml",
    media_type: "application/yaml",
    size_bytes: 10,
    sha256: "sha-1",
    representation: "yaml",
    ...overrides,
  }
}

function preview(overrides: Partial<ProjectArtifactPreview> = {}): ProjectArtifactPreview {
  return { text: "raw", parsed: null, truncated: false, parse_error: null, ...overrides }
}

function detail(overrides: Partial<ProjectArtifactDetail> = {}): ProjectArtifactDetail {
  return {
    entry: entry(),
    preview: preview(),
    content_url: "/ignored-by-the-client",
    ...overrides,
  }
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

// --- typed YAML cards -----------------------------------------------------------

test("renders the HuntConfig card with extra keys in the generic tree", () => {
  render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({ kind: "hunt_config" }),
        preview: preview({
          parsed: {
            hunt_id: "H-1",
            unit_id: "U-1",
            fault_class: "CWE-78",
            status: "ready",
            vulnerability_class: "rce",
            note: "extra",
          },
        }),
      })}
    />,
  )

  for (const value of ["H-1", "U-1", "CWE-78", "ready", "rce"]) {
    expect(screen.getByText(value)).toBeDefined()
  }
  expect(screen.getByRole("heading", { name: "Additional fields" })).toBeDefined()
  expect(screen.getByText("note")).toBeDefined()
  expect(screen.getByText("extra")).toBeDefined()
})

test("renders the TestImplementationSpec card with nested structures", () => {
  render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({ kind: "test_spec", relative_path: "hunting/hunter/test-specs/f/produced/s.yaml" }),
        preview: preview({
          parsed: {
            target_identity: { host: "app", port: 8080 },
            testing_pattern: ["probe", "mutate"],
            verification_symptoms: "crash",
            assumptions: null,
          },
        }),
      })}
    />,
  )

  for (const value of ["target_identity", "app", "8080", "probe", "mutate", "crash", "null"]) {
    expect(screen.getByText(value)).toBeDefined()
  }
})

test("renders the PodExport card", () => {
  render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({ kind: "pod_export", relative_path: "hunting/test-executor-pod/s/export.yaml" }),
        preview: preview({
          parsed: {
            verdict: "identified",
            terminal_reason: "complete",
            iterations: 3,
            clean: true,
          },
        }),
      })}
    />,
  )

  for (const value of ["identified", "complete", "3", "true"]) {
    expect(screen.getByText(value)).toBeDefined()
  }
})

test("renders a generic YAML tree for objects, arrays, scalars, and null", () => {
  render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({ kind: "pod_variant", relative_path: "hunting/test-executor-pod/s/variants/v.yaml" }),
        preview: preview({ parsed: { a: { b: [1, "two", null, false] } } }),
      })}
    />,
  )

  expect(screen.getByRole("heading", { name: "YAML" })).toBeDefined()
  for (const value of ["a", "b", "1", "two", "null", "false"]) {
    expect(screen.getByText(value)).toBeDefined()
  }
})

test("renders the ExperimentLog detail with the generic YAML tree", () => {
  render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({
          kind: "experiment_log",
          relative_path:
            "hunting/test-executor-pod/demo-authz-cwe1220-anon-id/experiment-log/order-0.yaml",
        }),
        preview: preview({
          parsed: { order: 0, observation: "synthetic observation", clean: true },
        }),
      })}
    />,
  )

  expect(screen.getByRole("heading", { name: "YAML" })).toBeDefined()
  for (const value of ["order", "0", "observation", "synthetic observation", "clean", "true"]) {
    expect(screen.getByText(value)).toBeDefined()
  }
})

// --- markdown and code safety ---------------------------------------------------

test("markdown skips active content and unsafe URLs", () => {
  const { container } = render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({
          kind: "skill_reference",
          relative_path: "skills/authn/references/x.md",
          media_type: "text/markdown",
          representation: "markdown",
        }),
        preview: preview({
          text:
            "# Title\n\n<script>alert(1)</script>\n\n" +
            '<iframe src="https://evil.example"></iframe>\n\n' +
            '<div onclick="alert(1)">click</div>\n\n[go](javascript:alert(1))',
          parsed: null,
        }),
      })}
    />,
  )

  expect(screen.getByRole("heading", { name: "Title" })).toBeDefined()
  expect(container.querySelector("script")).toBeNull()
  expect(container.querySelector("iframe")).toBeNull()
  expect(container.querySelector("[onclick]")).toBeNull()
  for (const anchor of Array.from(container.querySelectorAll("a"))) {
    expect(anchor.getAttribute("href") ?? "").not.toContain("javascript:")
  }
})

test("script/log text stays escaped text, never an active node", () => {
  const { container } = render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({
          kind: "skill_script",
          relative_path: "skills/authn/scripts/run.sh",
          media_type: "text/x-shellscript",
          representation: "text",
        }),
        preview: preview({ text: 'echo "<script>alert(1)</script>"', parsed: null }),
      })}
    />,
  )

  expect(container.querySelector("script")).toBeNull()
  expect(container.textContent).toContain("echo")
})

// --- fallbacks and states -------------------------------------------------------

test("a parse error shows the code, the raw text, and keeps the download", () => {
  render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({ kind: "hunt_config", representation: "yaml" }),
        preview: preview({ text: "key: [unterminated", parsed: null, parse_error: "invalid_yaml" }),
      })}
    />,
  )

  expect(screen.getByText(/invalid_yaml/)).toBeDefined()
  expect(screen.getByText("key: [unterminated")).toBeDefined()
})

test("parsed null without a parse error falls back to raw text", () => {
  render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({ kind: "pod_export", representation: "yaml" }),
        preview: preview({ text: "raw fallback", parsed: null, parse_error: null }),
      })}
    />,
  )

  expect(screen.getByText("raw fallback")).toBeDefined()
})

test("a truncated preview is announced", () => {
  render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({ kind: "skill_reference", representation: "markdown", media_type: "text/markdown" }),
        preview: preview({ text: "# big", truncated: true }),
      })}
    />,
  )

  expect(screen.getByText(/truncated/i)).toBeDefined()
})

test("the raw toggle preserves the exact preview text", () => {
  const raw = "line one\n  line two\n<script>alert(1)</script>"
  const { container } = render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({ kind: "pod_export", representation: "yaml" }),
        preview: preview({ text: raw, parsed: { verdict: "identified" } }),
      })}
    />,
  )

  fireEvent.click(screen.getByRole("button", { name: "Raw" }))

  const pre = container.querySelector("pre.artifact-raw")
  expect(pre?.textContent).toBe(raw)
  expect(screen.getByRole("button", { name: "Raw" }).getAttribute("aria-pressed")).toBe("true")
})

test("binary shows download-only metadata and no inline active element", () => {
  const { container } = render(
    <ProjectArtifactRenderer
      detail={detail({
        entry: entry({
          kind: "skill_asset",
          relative_path: "skills/authn/assets/logo.png",
          media_type: "image/png",
          representation: "binary",
        }),
        preview: preview({ text: null, parsed: null }),
      })}
    />,
  )

  expect(screen.getByText(/download-only/i)).toBeDefined()
  for (const tag of ["img", "iframe", "object", "embed", "audio", "video"]) {
    expect(container.querySelector(tag)).toBeNull()
  }
  expect(screen.queryByRole("button", { name: "Raw" })).toBeNull()
})

// --- routing and lifecycle ------------------------------------------------------

test("the workspace detail route renders metadata and rebuilds the raw URL", async () => {
  const { calls } = routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts/a1", () => json(detail())],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts/a1")

  await waitFor(() =>
    expect(
      screen.getAllByText("hunting/orchestration/hunt_configs/produced/x.yaml").length,
    ).toBeGreaterThan(0),
  )
  expect(screen.getByText("a1")).toBeDefined()
  expect(screen.getByText("sha-1")).toBeDefined()
  expect(screen.getByRole("link", { name: "Download raw" }).getAttribute("href")).toBe(
    "/trials/t/r/trial-1/resolved-artifacts/a1/content?expected_sha256=sha-1",
  )
  // Client-built navigation, not the server's content_url.
  expect(
    screen.getByRole("link", { name: "Trial workspace" }).getAttribute("href"),
  ).toBe("/p/p1/evals/t/r/trial-1")
  expect(
    screen.getByRole("link", { name: "Project artifacts" }).getAttribute("href"),
  ).toBe("/p/p1/evals/t/r/trial-1/artifacts")
  expect(calls.some((url) => url.includes("/content"))).toBe(false)
})

test("the compatible eval detail route renders eval breadcrumbs", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts/a1", () => json(detail())],
  ])
  goto("/eval/trials/t/r/trial-1/project-artifacts/a1")

  await waitFor(() =>
    expect(
      screen.getAllByText("hunting/orchestration/hunt_configs/produced/x.yaml").length,
    ).toBeGreaterThan(0),
  )
  const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" })
  const hrefs = Array.from(crumbs.querySelectorAll("a")).map((a) => a.getAttribute("href"))
  expect(hrefs).toEqual([
    "/eval",
    "/eval/trials/t/r/trial-1",
    "/eval/trials/t/r/trial-1/project-artifacts",
  ])
})

test("an unknown trial shows not-found with no detail request", async () => {
  const { calls } = routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts/a1", () => json(detail())],
  ])
  goto("/p/p1/evals/t/r/missing/artifacts/a1")

  await waitFor(() => expect(screen.getByText(/Trial not found/i)).toBeDefined())
  expect(calls.some((url) => url.includes("/artifacts/a1"))).toBe(false)
})

test("a cross-project mismatch shows not-found with no detail request", async () => {
  const { calls } = routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial({ project_id: "p2" })]))],
    ["/resolved-artifacts/a1", () => json(detail())],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts/a1")

  await waitFor(() => expect(screen.getByText(/Trial not found/i)).toBeDefined())
  expect(screen.queryByText("p2")).toBeNull()
  expect(calls.some((url) => url.includes("/artifacts/a1"))).toBe(false)
})

test("an unavailable resolved detail shows a notice", async () => {
  routeFetch([
    [
      "/snapshot",
      () =>
        json(
          evalSnapshot([
            evalTrial({
              artifact_summary: { status: "project_artifacts_unavailable", hunting: 0, skills: 0 },
            }),
          ]),
        ),
    ],
    [
      "/resolved-artifacts/a1",
      () => json({ detail: "artifact_unavailable" }, 409),
    ],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts/a1")

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/artifact_unavailable/)
  expect(screen.queryByText("Download raw")).toBeNull()
})

test("a detail artifact id mismatch is a safe error", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts/a1", () => json(detail({ entry: entry({ artifact_id: "other" }) }))],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts/a1")

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/mismatch/i)
})

test("shows loading and API error states", async () => {
  routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts/a1", () => json({ detail: "artifact_missing" }, 409)],
  ])
  goto("/p/p1/evals/t/r/trial-1/artifacts/a1")

  await waitFor(() => expect(screen.getByRole("alert")).toBeDefined())
  expect(screen.getByRole("alert").textContent).toMatch(/artifact_missing/)
})

test("aborts on artifact route change and ignores a late response", async () => {
  let resolveFirst: ((response: Response) => void) | undefined
  const first = new Promise<Response>((resolve) => {
    resolveFirst = resolve
  })
  const { signals } = routeFetch([
    ["/snapshot", () => json(evalSnapshot([evalTrial()]))],
    ["/resolved-artifacts/a1", () => first],
    ["/resolved-artifacts/a2", () => json(detail({ entry: entry({ artifact_id: "a2", relative_path: "second.yaml" }) }))],
  ])

  function Harness() {
    return (
      <>
        <Link to="/p/p1/evals/t/r/trial-1/artifacts/a2">next-artifact</Link>
        <Routes>
          <Route
            path="/p/:projectId/evals/:targetId/:targetRunId/:trialId/artifacts/:artifactId"
            element={<ProjectArtifactPage variant="workspace" />}
          />
        </Routes>
      </>
    )
  }

  render(
    <MemoryRouter initialEntries={["/p/p1/evals/t/r/trial-1/artifacts/a1"]}>
      <EvalDataProvider>
        <Harness />
      </EvalDataProvider>
    </MemoryRouter>,
  )

  await waitFor(() =>
    expect(screen.getByRole("link", { name: "next-artifact" })).toBeDefined(),
  )
  fireEvent.click(screen.getByRole("link", { name: "next-artifact" }))
  await waitFor(() =>
    expect(screen.getAllByText("second.yaml").length).toBeGreaterThan(0),
  )
  expect(signals[0].aborted).toBe(true)

  resolveFirst?.(json(detail({ entry: entry({ artifact_id: "a1", relative_path: "late.yaml" }) })))
  await Promise.resolve()
  await Promise.resolve()
  expect(screen.queryAllByText("late.yaml")).toHaveLength(0)
  expect(screen.getAllByText("second.yaml").length).toBeGreaterThan(0)
})
