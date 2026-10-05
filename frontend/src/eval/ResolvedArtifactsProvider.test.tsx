import { useLayoutEffect } from "react"
import { act, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, expect, test, vi } from "vitest"
import {
  ResolvedArtifactsProvider,
  useEvidenceResolver,
  useResolvedArtifactsResource,
} from "./ResolvedArtifactsProvider"
import { ResolvedArtifactsSection } from "./ResolvedArtifactsSection"
import type { ProjectArtifactEntry, ResolvedArtifactInventory } from "./types"

const POLL = 15_000

interface Ids {
  targetId: string
  targetRunId: string
  trialId: string
  expectedProjectId: string
}

const FIRST: Ids = { targetId: "target", targetRunId: "run", trialId: "first", expectedProjectId: "p" }

function identityOf(ids: Ids): string {
  return `${ids.targetId}|${ids.targetRunId}|${ids.trialId}|${ids.expectedProjectId}`
}

function artifact(id: string, relativePath: string): ProjectArtifactEntry {
  return {
    artifact_id: id,
    category: "hunting",
    kind: "test_spec",
    relative_path: relativePath,
    media_type: "application/yaml",
    size_bytes: 10,
    sha256: `sha-${id}`,
    representation: "yaml",
  }
}

function inventory(entries: ProjectArtifactEntry[], projectId = "p"): ResolvedArtifactInventory {
  return {
    status: "available",
    source: "project_storage",
    project_id: projectId,
    fallback_reason: null,
    groups: [{ key: "g", label: "G", category: "hunting", entries, children: [] }],
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

function hanging(): Promise<Response> {
  return new Promise<Response>(() => {})
}

type Resolutions = Array<{ identity: string; kind: string }>
type Frames = Array<{ identity: string; text: string }>

// Records the resolution of EVERY committed render - not just the final one.
function LinkProbe({ ids, seen }: { ids: Ids; seen: Resolutions }) {
  const resolve = useEvidenceResolver(ids.expectedProjectId)
  const result = resolve(`${ids.expectedProjectId}/hunting/x.yaml`)
  useLayoutEffect(() => {
    seen.push({ identity: identityOf(ids), kind: result.kind })
  })
  return null
}

// Records the artifacts DOM of every committed render.
function DomProbe({ ids, frames }: { ids: Ids; frames: Frames }) {
  // Consume the context so this probe re-renders with the section.
  useResolvedArtifactsResource()
  useLayoutEffect(() => {
    frames.push({
      identity: identityOf(ids),
      text: document.querySelector(".resolved-artifacts")?.textContent ?? "",
    })
  })
  return null
}

function Workspace({
  ids,
  seen,
  frames,
}: {
  ids: Ids
  seen: Resolutions
  frames: Frames
}) {
  return (
    <MemoryRouter>
      <ResolvedArtifactsProvider
        targetId={ids.targetId}
        targetRunId={ids.targetRunId}
        trialId={ids.trialId}
        expectedProjectId={ids.expectedProjectId}
      >
        <ResolvedArtifactsSection
          targetId={ids.targetId}
          targetRunId={ids.targetRunId}
          trialId={ids.trialId}
          expectedProjectId={ids.expectedProjectId}
          detailPath={(artifactId) => `/artifact/${artifactId}`}
        />
        <LinkProbe ids={ids} seen={seen} />
        <DomProbe ids={ids} frames={frames} />
      </ResolvedArtifactsProvider>
    </MemoryRouter>
  )
}

function linked(seen: Resolutions, ids: Ids): Resolutions {
  return seen.filter((entry) => entry.identity === identityOf(ids) && entry.kind === "linked")
}

afterEach(() => {
  vi.useRealTimers()
})

test("no committed render of a new trial resolves the previous trial's artifact", async () => {
  const seen: Resolutions = []
  const frames: Frames = []
  globalThis.fetch = (async () =>
    json(inventory([artifact("old-artifact", "hunting/x.yaml")]))) as typeof fetch

  const view = render(<Workspace ids={FIRST} seen={seen} frames={frames} />)
  await waitFor(() => expect(linked(seen, FIRST)).not.toEqual([]))

  const second = { ...FIRST, trialId: "second" }
  globalThis.fetch = (async () => await hanging()) as typeof fetch
  view.rerender(<Workspace ids={second} seen={seen} frames={frames} />)

  expect(linked(seen, second)).toEqual([])
})

test("a shared project_id never lets two trials share resolved artifacts", async () => {
  const seen: Resolutions = []
  const frames: Frames = []
  const first = { ...FIRST, expectedProjectId: "shared" }
  globalThis.fetch = (async () =>
    json(inventory([artifact("old-artifact", "hunting/x.yaml")], "shared"))) as typeof fetch

  const view = render(<Workspace ids={first} seen={seen} frames={frames} />)
  await waitFor(() => expect(linked(seen, first)).not.toEqual([]))

  const second = { ...first, trialId: "second" }
  globalThis.fetch = (async () => await hanging()) as typeof fetch
  view.rerender(<Workspace ids={second} seen={seen} frames={frames} />)
  expect(linked(seen, second)).toEqual([])
})

test("changing target_run_id, target_id, or expectedProjectId clears the artifacts", async () => {
  const variants: Array<Partial<Ids>> = [
    { targetRunId: "run-2" },
    { targetId: "target-2" },
    { expectedProjectId: "p2" },
  ]

  for (const variant of variants) {
    const seen: Resolutions = []
    const frames: Frames = []
    globalThis.fetch = (async () =>
      json(inventory([artifact("old-artifact", "hunting/x.yaml")]))) as typeof fetch
    const view = render(<Workspace ids={FIRST} seen={seen} frames={frames} />)
    await waitFor(() => expect(linked(seen, FIRST)).not.toEqual([]))

    const second = { ...FIRST, ...variant }
    globalThis.fetch = (async () => await hanging()) as typeof fetch
    view.rerender(<Workspace ids={second} seen={seen} frames={frames} />)

    expect(linked(seen, second), JSON.stringify(variant)).toEqual([])
    view.unmount()
  }
})

test("the artifacts DOM never shows the previous trial's entries in any committed render", async () => {
  const seen: Resolutions = []
  const frames: Frames = []
  globalThis.fetch = (async () =>
    json(inventory([artifact("old-artifact", "hunting/x.yaml")]))) as typeof fetch

  const view = render(<Workspace ids={FIRST} seen={seen} frames={frames} />)
  await waitFor(() =>
    expect(frames.some((frame) => frame.text.includes("hunting/x.yaml"))).toBe(true),
  )

  const second = { ...FIRST, trialId: "second" }
  globalThis.fetch = (async () => await hanging()) as typeof fetch
  view.rerender(<Workspace ids={second} seen={seen} frames={frames} />)

  const stale = frames.filter(
    (frame) => frame.identity === identityOf(second) && frame.text.includes("hunting/x.yaml"),
  )
  expect(stale).toEqual([])
})

test("a late response for the previous trial never restores its artifacts", async () => {
  const seen: Resolutions = []
  const frames: Frames = []
  let resolveFirst: ((value: Response) => void) | undefined
  let calls = 0
  globalThis.fetch = (async () => {
    calls += 1
    if (calls === 1) {
      return await new Promise<Response>((resolve) => {
        resolveFirst = resolve
      })
    }
    return await hanging()
  }) as typeof fetch

  const view = render(<Workspace ids={FIRST} seen={seen} frames={frames} />)
  await waitFor(() => expect(resolveFirst).toBeDefined())
  const second = { ...FIRST, trialId: "second" }
  view.rerender(<Workspace ids={second} seen={seen} frames={frames} />)

  await act(async () => {
    resolveFirst?.(json(inventory([artifact("old-artifact", "hunting/x.yaml")])))
  })
  expect(linked(seen, second)).toEqual([])
  expect(
    frames.filter(
      (frame) => frame.identity === identityOf(second) && frame.text.includes("hunting/x.yaml"),
    ),
  ).toEqual([])
})

test("a failed refresh of the same identity keeps the last valid inventory", async () => {
  vi.useFakeTimers()
  const seen: Resolutions = []
  const frames: Frames = []
  let failing = false
  globalThis.fetch = (async () =>
    failing
      ? json({ detail: "artifact_unsafe" }, 409)
      : json(inventory([artifact("old-artifact", "hunting/x.yaml")]))) as typeof fetch

  render(<Workspace ids={FIRST} seen={seen} frames={frames} />)
  await act(async () => {})
  expect(linked(seen, FIRST)).not.toEqual([])

  failing = true
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL)
  })
  // The failed refresh belongs to the SAME identity: its last valid data stays.
  expect(linked(seen, FIRST)).not.toEqual([])
})

test("the workspace polls the resolved inventory once per identity", async () => {
  const calls: string[] = []
  globalThis.fetch = (async (input: unknown) => {
    calls.push(String(input))
    return json(inventory([artifact("old-artifact", "hunting/x.yaml")]))
  }) as typeof fetch

  render(<Workspace ids={FIRST} seen={[]} frames={[]} />)
  await waitFor(() => expect(calls.length).toBeGreaterThan(0))
  expect(calls.filter((url) => url.endsWith("/resolved-artifacts"))).toHaveLength(1)
})

test("the PodExport classification never consumes the previous trial's exports", async () => {
  const requests: string[] = []
  let second = false
  const exportEntry: ProjectArtifactEntry = {
    ...artifact("old-export", "hunting/test-executor-pod/s/run.yaml"),
    kind: "pod_export",
  }
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    requests.push(url)
    if (url.endsWith("/resolved-artifacts")) {
      if (second) return await hanging()
      return json(inventory([exportEntry]))
    }
    return json({
      entry: exportEntry,
      preview: {
        text: "raw",
        parsed: { verdict: "successful", evidence: { terminal_reason: "symptom-confirmed" } },
        truncated: false,
        parse_error: null,
      },
      content_url: "/never",
    })
  }) as typeof fetch

  const view = render(<Workspace ids={FIRST} seen={[]} frames={[]} />)
  await waitFor(() => expect(screen.getByRole("heading", { name: "Symptom confirmed" })).toBeDefined())
  const before = requests.filter((url) => /\/resolved-artifacts\/old-export$/.test(url)).length

  second = true
  view.rerender(<Workspace ids={{ ...FIRST, trialId: "second" }} seen={[]} frames={[]} />)
  await act(async () => {})

  const after = requests.filter((url) => /\/resolved-artifacts\/old-export$/.test(url)).length
  expect(after).toBe(before)
})
