import { expect, test } from "vitest"
import { withTestSpecSides } from "./projectArtifacts"
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
