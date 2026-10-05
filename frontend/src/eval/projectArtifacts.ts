// Pure display helpers for the project-artifact inventory. No React, no fetch,
// no state: the server's grouping and order are authoritative.
import type {
  ProjectArtifactCategory,
  ProjectArtifactEntry,
  ProjectArtifactGroup,
  ProjectArtifactKind,
  ProjectArtifactRepresentation,
  ResolvedSource,
} from "./types"

// The two sources a resolved inventory or graph reports. The browser labels
// them; it never chooses between them and never shows a schema-version term.
const SOURCE_LABELS: Record<ResolvedSource, string> = {
  trial_snapshot: "Captured with Trial",
  project_storage: "Saved for project",
}

export function sourceLabel(source: ResolvedSource): string {
  return SOURCE_LABELS[source] ?? String(source)
}

export interface ProjectArtifactSection {
  category: ProjectArtifactCategory
  label: string
  groups: ProjectArtifactGroup[]
}

const SECTION_LABELS: Record<ProjectArtifactCategory, string> = {
  hunting: "Hunting",
  skill: "Skills",
}

// Split the server's root groups into the two readable sections, preserving the
// order the server sent within each.
export function artifactSections(groups: ProjectArtifactGroup[]): ProjectArtifactSection[] {
  return [
    {
      category: "hunting",
      label: SECTION_LABELS.hunting,
      groups: groups.filter((group) => group.category === "hunting"),
    },
    {
      category: "skill",
      label: SECTION_LABELS.skill,
      groups: groups.filter((group) => group.category === "skill"),
    },
  ]
}

// --- TestImplementationSpec produced/consumed split ---------------------------

// The directory side is the ONLY classification source. The document carries a
// separate `status` (hypothesised/verified/dropped/specified) that must never
// drive this grouping. "Consumed" means the mover drained the spec from the
// inbox - it does NOT mean a test ran or that a vulnerability was found.
const TEST_SPEC_SIDES = ["produced", "consumed"] as const
type TestSpecSide = (typeof TEST_SPEC_SIDES)[number]

const TEST_SPEC_SIDE_LABELS: Record<TestSpecSide, string> = {
  produced: "Produced",
  consumed: "Consumed",
}

// `hunting/hunter/test-specs/<fault_key>/<produced|consumed>/<file>.yaml` - the
// fixed allowlist shape the reader serves. Parsed positionally, never by
// searching the whole path for the word "consumed".
function testSpecSide(relativePath: string): TestSpecSide | null {
  const parts = relativePath.split("/")
  if (parts.length !== 6) return null
  const [root, module, family, faultKey, side, file] = parts
  if (root !== "hunting" || module !== "hunter" || family !== "test-specs") return null
  if (!faultKey || !file.endsWith(".yaml")) return null
  return (TEST_SPEC_SIDES as readonly string[]).includes(side) ? (side as TestSpecSide) : null
}

function sideChild(
  parent: ProjectArtifactGroup,
  side: TestSpecSide,
  entries: ProjectArtifactEntry[],
): ProjectArtifactGroup {
  return {
    key: `${parent.key}/${side}`,
    label: TEST_SPEC_SIDE_LABELS[side],
    category: parent.category,
    entries,
    children: [],
  }
}

// The shared, pure presentation adapter: split each group's own `test_spec`
// entries into non-empty Produced/Consumed children by directory side. Entries
// that are not test specs - or whose path is not the recognized shape - stay in
// the group exactly where they were. Order, ids and links are preserved, the
// input is never mutated, and an unchanged tree is returned as-is.
export function withTestSpecSides(groups: ProjectArtifactGroup[]): ProjectArtifactGroup[] {
  let changed = false
  const next = groups.map((group) => {
    const children = withTestSpecSides(group.children)
    const produced: ProjectArtifactEntry[] = []
    const consumed: ProjectArtifactEntry[] = []
    const rest: ProjectArtifactEntry[] = []
    for (const entry of group.entries) {
      const side = entry.kind === "test_spec" ? testSpecSide(entry.relative_path) : null
      if (side === "produced") produced.push(entry)
      else if (side === "consumed") consumed.push(entry)
      else rest.push(entry)
    }
    const childrenChanged = children !== group.children
    if (!childrenChanged && produced.length === 0 && consumed.length === 0) return group
    changed = true
    const merged = childrenChanged ? [...children] : [...group.children]
    if (produced.length > 0) merged.push(sideChild(group, "produced", produced))
    if (consumed.length > 0) merged.push(sideChild(group, "consumed", consumed))
    return { ...group, entries: rest, children: merged }
  })
  return changed ? next : groups
}

// The group's display label, with a deterministic fallback to the last key
// segment (then a final literal) when the server label is blank.
export function groupLabel(group: ProjectArtifactGroup): string {
  const label = typeof group.label === "string" ? group.label.trim() : ""
  if (label) return label
  const segment = group.key.split("/").filter(Boolean).pop()
  return segment ?? "Artifacts"
}

// Stable React keys: the group key and the artifact id are unique per Trial.
export function groupKey(group: ProjectArtifactGroup): string {
  return group.key
}

export function artifactKey(entry: ProjectArtifactEntry): string {
  return entry.artifact_id
}

const KIND_LABELS: Record<ProjectArtifactKind, string> = {
  hunt_config: "Hunt config",
  test_spec: "Test spec",
  pod_variant: "Pod variant",
  experiment_log: "Experiment log",
  pod_export: "Pod export",
  skill_procedure: "Procedure",
  skill_reference: "Reference",
  skill_script: "Script",
  skill_asset: "Asset",
}

export function kindLabel(kind: ProjectArtifactKind): string {
  return KIND_LABELS[kind] ?? String(kind)
}

const REPRESENTATION_LABELS: Record<ProjectArtifactRepresentation, string> = {
  yaml: "YAML",
  markdown: "Markdown",
  text: "Text",
  binary: "Binary",
}

export function representationLabel(representation: ProjectArtifactRepresentation): string {
  return REPRESENTATION_LABELS[representation] ?? String(representation)
}
