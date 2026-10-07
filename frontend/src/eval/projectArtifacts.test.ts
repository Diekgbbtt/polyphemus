import { expect, test } from "vitest"
import {
  POD_EXPORT_REASONS,
  buildArtifactPathIndex,
  collectPodExports,
  podExportReasonFromDetail,
  resolveEvidenceReference,
  withPodExportOutcomes,
  withTestSpecSides,
} from "./projectArtifacts"
import type { PodExportOutcome } from "./projectArtifacts"
import type { ProjectArtifactEntry, ProjectArtifactGroup } from "./types"

function spec(
  id: string,
  side: string,
  fault = "FaultA",
  file = `${id}.yaml`,
): ProjectArtifactEntry {
  return {
    artifact_id: id,
    category: "hunting",
    kind: "test_spec",
    relative_path: `hunting/hunter/test-specs/${fault}/${side}/${file}`,
    media_type: "application/yaml",
    size_bytes: 10,
    sha256: `sha-${id}`,
    representation: "yaml",
  }
}

function huntEntry(id: string): ProjectArtifactEntry {
  return {
    artifact_id: id,
    category: "hunting",
    kind: "hunt_config",
    relative_path: `hunting/orchestration/hunt_configs/consumed/${id}.yaml`,
    media_type: "application/yaml",
    size_bytes: 5,
    sha256: `sha-${id}`,
    representation: "yaml",
  }
}

function group(overrides: Partial<ProjectArtifactGroup> = {}): ProjectArtifactGroup {
  return { key: "g", label: "G", category: "hunting", entries: [], children: [], ...overrides }
}

function fault(key: string, entries: ProjectArtifactEntry[]): ProjectArtifactGroup {
  return group({ key: `test-specs/${key}`, label: key, entries })
}

function testSpecs(rootChildren: ProjectArtifactGroup[]): ProjectArtifactGroup[] {
  return [group({ key: "test-specs", label: "Test specs", children: rootChildren })]
}

function sidesOf(faultGroup: ProjectArtifactGroup): Record<string, string[]> {
  return Object.fromEntries(
    faultGroup.children.map((child) => [child.label, child.entries.map((e) => e.artifact_id)]),
  )
}

function allIds(groups: ProjectArtifactGroup[]): string[] {
  const ids: string[] = []
  for (const g of groups) {
    ids.push(...g.entries.map((e) => e.artifact_id))
    ids.push(...allIds(g.children))
  }
  return ids.sort()
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value as Record<string, unknown>).forEach(deepFreeze)
    Object.freeze(value)
  }
  return value
}

test("splits one fault's test specs into Produced and Consumed", () => {
  const out = withTestSpecSides(
    testSpecs([fault("FaultA", [spec("a-prod", "produced"), spec("a-cons", "consumed")])]),
  )

  const faultGroup = out[0].children[0]
  expect(faultGroup.entries).toHaveLength(0)
  expect(sidesOf(faultGroup)).toEqual({ Produced: ["a-prod"], Consumed: ["a-cons"] })
  expect(faultGroup.children.map((c) => c.key)).toEqual([
    "test-specs/FaultA/produced",
    "test-specs/FaultA/consumed",
  ])
})

test("keeps every entry in its own fault group", () => {
  const out = withTestSpecSides(
    testSpecs([
      fault("FaultA", [spec("a1", "produced"), spec("a2", "consumed")]),
      fault("FaultB", [spec("b1", "consumed")]),
    ]),
  )

  expect(sidesOf(out[0].children[0])).toEqual({ Produced: ["a1"], Consumed: ["a2"] })
  expect(sidesOf(out[0].children[1])).toEqual({ Consumed: ["b1"] })
})

test("does not invent an empty side subgroup", () => {
  const out = withTestSpecSides(testSpecs([fault("FaultA", [spec("a1", "produced")])]))

  const faultGroup = out[0].children[0]
  expect(faultGroup.children.map((c) => c.label)).toEqual(["Produced"])
})

test("classifies by the directory side, not by a status field on the document", () => {
  const producedWithStatus = { ...spec("p1", "produced"), status: "consumed" } as ProjectArtifactEntry
  const consumedWithStatus = { ...spec("c1", "consumed"), status: "specified" } as ProjectArtifactEntry

  const out = withTestSpecSides(testSpecs([fault("FaultA", [producedWithStatus, consumedWithStatus])]))

  expect(sidesOf(out[0].children[0])).toEqual({ Produced: ["p1"], Consumed: ["c1"] })
})

test("is not fooled by the word consumed elsewhere in the path", () => {
  const inProduced = spec("p1", "produced", "FaultA", "reconsumed-name.yaml")
  const inConsumed = spec("c1", "consumed", "FaultA", "produced-lookalike.yaml")

  const out = withTestSpecSides(testSpecs([fault("FaultA", [inProduced, inConsumed])]))

  expect(sidesOf(out[0].children[0])).toEqual({ Produced: ["p1"], Consumed: ["c1"] })
})

test("keeps an unrecognized test-spec path visible in the original group", () => {
  const odd = spec("z1", "notes") // hunting/hunter/test-specs/FaultA/notes/z1.yaml
  const shallow = { ...spec("z2", "x"), relative_path: "hunting/hunter/test-specs/z2.yaml" }

  const out = withTestSpecSides(testSpecs([fault("FaultA", [odd, shallow, spec("ok", "produced")])]))

  const faultGroup = out[0].children[0]
  expect(faultGroup.entries.map((e) => e.artifact_id)).toEqual(["z1", "z2"])
  expect(sidesOf(faultGroup)).toEqual({ Produced: ["ok"] })
})

test("does not duplicate or lose entries and preserves the order within a side", () => {
  const input = testSpecs([
    fault("FaultA", [
      spec("a2", "consumed"),
      spec("a1", "produced"),
      spec("a3", "consumed"),
      spec("a4", "produced"),
    ]),
  ])

  const out = withTestSpecSides(input)

  expect(allIds(out)).toEqual(allIds(input))
  expect(sidesOf(out[0].children[0])).toEqual({
    Produced: ["a1", "a4"],
    Consumed: ["a2", "a3"],
  })
})

test("does not mutate its input", () => {
  const input = testSpecs([
    fault("FaultA", [spec("a1", "produced"), spec("a2", "consumed")]),
  ])
  deepFreeze(input)
  const before = JSON.stringify(input)

  expect(() => withTestSpecSides(input)).not.toThrow()
  expect(JSON.stringify(input)).toBe(before)
})

test("leaves other kinds and categories untouched", () => {
  const otherGroups: ProjectArtifactGroup[] = [
    group({
      key: "hunt-configs",
      label: "Hunt configs",
      children: [
        group({ key: "hunt-configs/consumed", label: "Consumed", entries: [huntEntry("h1")] }),
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
          children: [],
        }),
      ],
    }),
  ]

  const out = withTestSpecSides(otherGroups)

  expect(out).toBe(otherGroups)
})

// --- PodExport outcome grouping -------------------------------------------------

function podEntry(
  kind: ProjectArtifactEntry["kind"],
  id: string,
  spec: string,
  sub: string,
): ProjectArtifactEntry {
  return {
    artifact_id: id,
    category: "hunting",
    kind,
    relative_path: `hunting/test-executor-pod/${spec}/${sub}`,
    media_type: "application/yaml",
    size_bytes: 10,
    sha256: `sha-${id}`,
    representation: "yaml",
  }
}

function exportEntry(id: string, spec: string): ProjectArtifactEntry {
  return podEntry("pod_export", id, spec, `${id}.yaml`)
}
function logEntry(id: string, spec: string): ProjectArtifactEntry {
  return podEntry("experiment_log", id, spec, `experiment-log/${id}.yaml`)
}
function variantEntry(id: string, spec: string): ProjectArtifactEntry {
  return podEntry("pod_variant", id, spec, `variants/${id}.yaml`)
}

function specGroup(spec: string, entries: ProjectArtifactEntry[]): ProjectArtifactGroup {
  return group({ key: `pod-executions/${spec}`, label: spec, entries })
}
function podExecutions(children: ProjectArtifactGroup[]): ProjectArtifactGroup[] {
  return [group({ key: "pod-executions", label: "Pod executions", children })]
}
function podExportsRoot(groups: ProjectArtifactGroup[]): ProjectArtifactGroup | undefined {
  return groups.find((g) => g.key === "pod-exports")
}

test("classifies a PodExport from the envelope's evidence.terminal_reason", () => {
  expect(
    podExportReasonFromDetail({ verdict: "successful", evidence: { terminal_reason: "symptom-confirmed" } }),
  ).toBe("symptom-confirmed")
})

test("ignores verdict and filenames when classifying", () => {
  // A verdict that names a reason must not win over the evidence.
  expect(
    podExportReasonFromDetail({ verdict: "symptom-confirmed", evidence: { terminal_reason: "budget-timeout" } }),
  ).toBe("budget-timeout")
  // No evidence reason at all: the verdict is not a reason.
  expect(podExportReasonFromDetail({ verdict: "successful", evidence: {} })).toBeNull()
})

test("returns null for a missing, malformed, or unrecognized reason", () => {
  expect(podExportReasonFromDetail(null)).toBeNull()
  expect(podExportReasonFromDetail("symptom-confirmed")).toBeNull()
  expect(podExportReasonFromDetail({ evidence: "nope" })).toBeNull()
  expect(podExportReasonFromDetail({ evidence: { terminal_reason: 42 } })).toBeNull()
  expect(podExportReasonFromDetail({ evidence: { terminal_reason: "made-up" } })).toBeNull()
  // Exact values only: a case variant is not recognized.
  expect(podExportReasonFromDetail({ evidence: { terminal_reason: "SYMPTOM-CONFIRMED" } })).toBeNull()
})

test("collects every pod_export entry across the tree, in order", () => {
  const groups = podExecutions([
    specGroup("a", [exportEntry("x1", "a"), logEntry("l1", "a")]),
    specGroup("b", [exportEntry("x2", "b")]),
  ])

  expect(collectPodExports(groups).map((e) => e.artifact_id)).toEqual(["x1", "x2"])
})

test("groups pod exports by every allowed terminal reason, in enum order", () => {
  const entries = POD_EXPORT_REASONS.map((_, index) => exportEntry(`e${index}`, `spec-${index}`))
  const outcomes = new Map<string, PodExportOutcome>(
    entries.map((e, index) => [e.artifact_id, { state: "ready", reason: POD_EXPORT_REASONS[index] }]),
  )

  const out = withPodExportOutcomes(
    podExecutions(entries.map((e, index) => specGroup(`spec-${index}`, [e]))),
    outcomes,
  )

  const root = podExportsRoot(out)
  expect(root?.label).toBe("Pod exports")
  expect(root?.children.map((c) => c.label)).toEqual([
    "Symptom confirmed",
    "Space exhausted",
    "Technical infeasibility",
    "Specific defence prevention",
    "No symptom evidence",
    "Budget timeout",
  ])
  expect(root?.children.map((c) => c.entries.map((e) => e.artifact_id))).toEqual([
    ["e0"],
    ["e1"],
    ["e2"],
    ["e3"],
    ["e4"],
    ["e5"],
  ])
})

test("moves pod exports into outcome groups while log and variant stay per spec", () => {
  const groups = [
    group({
      key: "hunt-configs",
      label: "Hunt configs",
      children: [group({ key: "hunt-configs/consumed", label: "Consumed", entries: [huntEntry("h1")] })],
    }),
    ...podExecutions([
      specGroup("alpha", [exportEntry("x1", "alpha"), logEntry("l1", "alpha"), variantEntry("v1", "alpha")]),
      specGroup("beta", [exportEntry("x2", "beta"), logEntry("l2", "beta"), variantEntry("v2", "beta")]),
    ]),
  ]
  const outcomes = new Map<string, PodExportOutcome>([
    ["x1", { state: "ready", reason: "symptom-confirmed" }],
    ["x2", { state: "ready", reason: "space-exhausted" }],
  ])

  const out = withPodExportOutcomes(groups, outcomes)

  const executions = out.find((g) => g.key === "pod-executions")
  expect(executions?.children.map((c) => c.label)).toEqual(["alpha", "beta"])
  expect(executions?.children.map((c) => c.entries.map((e) => e.kind))).toEqual([
    ["experiment_log", "pod_variant"],
    ["experiment_log", "pod_variant"],
  ])

  const root = podExportsRoot(out)
  expect(root?.children.map((c) => [c.label, c.entries.map((e) => e.artifact_id)])).toEqual([
    ["Symptom confirmed", ["x1"]],
    ["Space exhausted", ["x2"]],
  ])
  // "Pod exports" sits right after "Pod executions".
  expect(out.map((g) => g.key)).toEqual(["hunt-configs", "pod-executions", "pod-exports"])
})

test("keeps unclassified exports visible: pending and unavailable are separate groups", () => {
  const groups = podExecutions([
    specGroup("alpha", [exportEntry("x1", "alpha")]),
    specGroup("beta", [exportEntry("x2", "beta"), logEntry("l2", "beta")]),
  ])

  const loading = withPodExportOutcomes(groups, new Map())
  expect(podExportsRoot(loading)?.children.map((c) => c.label)).toEqual([
    "Classifying",
  ])
  expect(podExportsRoot(loading)?.children[0].entries.map((e) => e.artifact_id)).toEqual(["x1", "x2"])

  const ready = withPodExportOutcomes(
    groups,
    new Map<string, PodExportOutcome>([
      ["x1", { state: "ready", reason: null }],
      ["x2", { state: "pending" }],
    ]),
  )
  expect(podExportsRoot(ready)?.children.map((c) => c.label)).toEqual([
    "Outcome unavailable",
    "Classifying",
  ])
})

test("removes only containers that became truly empty", () => {
  const groups = podExecutions([
    specGroup("only-export", [exportEntry("y1", "only-export")]),
    specGroup("has-log", [exportEntry("y2", "has-log"), logEntry("l2", "has-log")]),
  ])
  const outcomes = new Map<string, PodExportOutcome>([
    ["y1", { state: "ready", reason: "budget-timeout" }],
    ["y2", { state: "ready", reason: "budget-timeout" }],
  ])

  const out = withPodExportOutcomes(groups, outcomes)

  expect(out.find((g) => g.key === "pod-executions")?.children.map((c) => c.label)).toEqual([
    "has-log",
  ])
  expect(podExportsRoot(out)?.children[0].entries.map((e) => e.artifact_id)).toEqual(["y1", "y2"])
})

test("drops the Pod executions root when every spec was export-only", () => {
  const groups = podExecutions([specGroup("a", [exportEntry("z1", "a")])])
  const out = withPodExportOutcomes(
    groups,
    new Map<string, PodExportOutcome>([["z1", { state: "ready", reason: "symptom-confirmed" }]]),
  )

  expect(out.find((g) => g.key === "pod-executions")).toBeUndefined()
  expect(podExportsRoot(out)?.children[0].entries.map((e) => e.artifact_id)).toEqual(["z1"])
})

test("does not duplicate or lose entries and does not mutate the input", () => {
  const groups = [
    ...podExecutions([
      specGroup("alpha", [exportEntry("x1", "alpha"), logEntry("l1", "alpha"), variantEntry("v1", "alpha")]),
      specGroup("beta", [exportEntry("x2", "beta")]),
    ]),
  ]
  deepFreeze(groups)
  const before = JSON.stringify(groups)
  const ids = (gs: ProjectArtifactGroup[]): string[] => {
    const out: string[] = []
    for (const g of gs) {
      out.push(...g.entries.map((e) => e.artifact_id))
      out.push(...ids(g.children))
    }
    return out.sort()
  }
  const beforeIds = ids(groups)

  const out = withPodExportOutcomes(
    groups,
    new Map<string, PodExportOutcome>([
      ["x1", { state: "ready", reason: "symptom-confirmed" }],
      ["x2", { state: "ready", reason: "space-exhausted" }],
    ]),
  )

  expect(ids(out)).toEqual(beforeIds)
  expect(JSON.stringify(groups)).toBe(before)
})

test("leaves TestSpec produced/consumed and Skills untouched", () => {
  const groups = [
    ...testSpecs([fault("FaultA", [spec("p1", "produced"), spec("c1", "consumed")])]),
    ...podExecutions([specGroup("alpha", [exportEntry("x1", "alpha"), logEntry("l1", "alpha")])]),
  ]

  const out = withPodExportOutcomes(
    withTestSpecSides(groups),
    new Map<string, PodExportOutcome>([["x1", { state: "ready", reason: "budget-timeout" }]]),
  )

  const ts = out.find((g) => g.key === "test-specs")
  expect(ts?.children[0].children.map((c) => c.label)).toEqual(["Produced", "Consumed"])
  const executions = out.find((g) => g.key === "pod-executions")
  expect(executions?.children[0].entries.map((e) => e.kind)).toEqual(["experiment_log"])
})

test("uses stable, collision-free outcome group keys", () => {
  const groups = podExecutions([
    specGroup("alpha", [exportEntry("x1", "alpha")]),
    specGroup("beta", [exportEntry("x2", "beta")]),
  ])
  const out = withPodExportOutcomes(
    groups,
    new Map<string, PodExportOutcome>([
      ["x1", { state: "ready", reason: "symptom-confirmed" }],
      ["x2", { state: "ready", reason: null }],
    ]),
  )

  const keys = podExportsRoot(out)?.children.map((c) => c.key) ?? []
  expect(keys).toEqual(["pod-exports/symptom-confirmed", "pod-exports/unavailable"])
  expect(new Set(keys).size).toBe(keys.length)
})

// --- verdict evidence -> artifact links ----------------------------------------

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

function pathIndex(entries: ProjectArtifactEntry[], projectId: string | null = "proj-1") {
  return buildArtifactPathIndex([group({ key: "g", entries })], projectId)
}

test("links an evidence reference that matches a relative_path exactly", () => {
  const index = pathIndex([artifact("a1", "hunting/hunter/test-specs/F/produced/x.yaml")])

  expect(resolveEvidenceReference("hunting/hunter/test-specs/F/produced/x.yaml", index)).toEqual({
    kind: "linked",
    artifact_id: "a1",
  })
})

test("removes only the exact project_id prefix", () => {
  const index = pathIndex([artifact("a1", "hunting/x.yaml")], "proj-1")

  expect(resolveEvidenceReference("proj-1/hunting/x.yaml", index)).toEqual({
    kind: "linked",
    artifact_id: "a1",
  })
  // A different project's prefix is NOT stripped: it matches nothing.
  expect(resolveEvidenceReference("proj-2/hunting/x.yaml", index)).toEqual({ kind: "missing" })
})

test("never matches by basename or by a suffix of the path", () => {
  const index = pathIndex([artifact("a1", "hunting/deep/x.yaml")])

  expect(resolveEvidenceReference("x.yaml", index)).toEqual({ kind: "missing" })
  expect(resolveEvidenceReference("deep/x.yaml", index)).toEqual({ kind: "missing" })
  expect(resolveEvidenceReference("other/deep/x.yaml", index)).toEqual({ kind: "missing" })
})

test("a directory reference (spec_dir) is never linked to its children", () => {
  const index = pathIndex([
    artifact("a1", "hunting/hunter/test-specs/F/produced/x.yaml"),
    artifact("a2", "hunting/hunter/test-specs/F/consumed/y.yaml"),
  ])

  expect(resolveEvidenceReference("hunting/hunter/test-specs/F", index)).toEqual({ kind: "missing" })
})

test("an ambiguous relative_path is never resolved arbitrarily", () => {
  const index = pathIndex([artifact("a1", "hunting/x.yaml"), artifact("a2", "hunting/x.yaml")])

  expect(resolveEvidenceReference("hunting/x.yaml", index)).toEqual({ kind: "plain" })
})

test("rejects traversal, absolute paths, and URLs", () => {
  const index = pathIndex([artifact("a1", "hunting/x.yaml")])

  for (const reference of [
    "../hunting/x.yaml",
    "a/../hunting/x.yaml",
    "./hunting/x.yaml",
    "/hunting/x.yaml",
    "//evil.invalid/hunting/x.yaml",
    "https://evil.invalid/hunting/x.yaml",
    "javascript:alert(1)",
    "hunting\\x.yaml",
  ]) {
    expect(resolveEvidenceReference(reference, index), reference).toEqual({ kind: "plain" })
  }
})

test("a safe reference with no match is missing, not plain", () => {
  const index = pathIndex([artifact("a1", "hunting/x.yaml")])

  expect(resolveEvidenceReference("hunting/nope.yaml", index)).toEqual({ kind: "missing" })
})
