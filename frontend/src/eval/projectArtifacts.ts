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

// --- PodExport outcome grouping -------------------------------------------------

// The terminal_reason vocabulary the producer writes into the PodExport envelope
// (`evidence.terminal_reason`). The inventory does not carry it, so the section
// reads each PodExport's detail - never the filename, the verdict, or the vuln.
export const POD_EXPORT_REASONS = [
  "symptom-confirmed",
  "space-exhausted",
  "technical-infeasibility",
  "specific-defence-prevention",
  "no-symptom-evidence",
  "budget-timeout",
] as const
export type PodExportReason = (typeof POD_EXPORT_REASONS)[number]

// One export's classification: still loading, or settled (a recognized reason,
// or null when the reason is absent, malformed, unrecognized, or unavailable).
export type PodExportOutcome =
  | { state: "pending" }
  | { state: "ready"; reason: PodExportReason | null }

const POD_EXPORT_REASON_LABELS: Record<PodExportReason, string> = {
  "symptom-confirmed": "Symptom confirmed",
  "space-exhausted": "Space exhausted",
  "technical-infeasibility": "Technical infeasibility",
  "specific-defence-prevention": "Specific defence prevention",
  "no-symptom-evidence": "No symptom evidence",
  "budget-timeout": "Budget timeout",
}
const POD_EXPORT_UNAVAILABLE = "unavailable"
const POD_EXPORT_UNAVAILABLE_LABEL = "Outcome unavailable"
const POD_EXPORT_PENDING = "pending"
const POD_EXPORT_PENDING_LABEL = "Classifying"

// The outcome carried by a parsed PodExport envelope. A missing, malformed, or
// unrecognized `evidence.terminal_reason` is null - never guessed from `verdict`.
export function podExportReasonFromDetail(parsed: unknown): PodExportReason | null {
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null
  const evidence = (parsed as Record<string, unknown>).evidence
  if (!evidence || typeof evidence !== "object" || Array.isArray(evidence)) return null
  const reason = (evidence as Record<string, unknown>).terminal_reason
  return typeof reason === "string" && (POD_EXPORT_REASONS as readonly string[]).includes(reason)
    ? (reason as PodExportReason)
    : null
}

// Every pod_export entry in the tree, in render order.
export function collectPodExports(groups: ProjectArtifactGroup[]): ProjectArtifactEntry[] {
  const collected: ProjectArtifactEntry[] = []
  for (const group of groups) {
    collected.push(...group.entries.filter((entry) => entry.kind === "pod_export"))
    collected.push(...collectPodExports(group.children))
  }
  return collected
}

// The presentation transform: lift every pod_export entry into a "Pod exports"
// root grouped by outcome (recognized reasons in enum order, then the
// unavailable and pending buckets), leaving log and variant entries in their
// original per-spec groups. A container left truly empty is dropped; ids, paths
// and order are preserved; the input is never mutated.
export function withPodExportOutcomes(
  groups: ProjectArtifactGroup[],
  outcomes: ReadonlyMap<string, PodExportOutcome>,
): ProjectArtifactGroup[] {
  const exports: ProjectArtifactEntry[] = []

  const strip = (level: ProjectArtifactGroup[]): ProjectArtifactGroup[] => {
    let changed = false
    const keptGroups: ProjectArtifactGroup[] = []
    for (const group of level) {
      const keptEntries: ProjectArtifactEntry[] = []
      let moved = false
      for (const entry of group.entries) {
        if (entry.kind === "pod_export") {
          exports.push(entry)
          moved = true
        } else {
          keptEntries.push(entry)
        }
      }
      const children = strip(group.children)
      const childrenChanged = children !== group.children
      if (!moved && !childrenChanged) {
        keptGroups.push(group)
        continue
      }
      changed = true
      if (keptEntries.length === 0 && children.length === 0) continue // became empty
      keptGroups.push({ ...group, entries: keptEntries, children })
    }
    return changed ? keptGroups : level
  }

  const stripped = strip(groups)
  if (exports.length === 0) return stripped

  const buckets = new Map<string, ProjectArtifactEntry[]>()
  for (const entry of exports) {
    const outcome = outcomes.get(entry.artifact_id)
    const key =
      !outcome || outcome.state === "pending"
        ? POD_EXPORT_PENDING
        : (outcome.reason ?? POD_EXPORT_UNAVAILABLE)
    const bucket = buckets.get(key)
    if (bucket) bucket.push(entry)
    else buckets.set(key, [entry])
  }

  const category = exports[0].category
  const child = (key: string, label: string): ProjectArtifactGroup | null => {
    const entries = buckets.get(key)
    if (!entries || entries.length === 0) return null
    return { key: `pod-exports/${key}`, label, category, entries, children: [] }
  }

  const children: ProjectArtifactGroup[] = []
  for (const reason of POD_EXPORT_REASONS) {
    const node = child(reason, POD_EXPORT_REASON_LABELS[reason])
    if (node) children.push(node)
  }
  const unavailable = child(POD_EXPORT_UNAVAILABLE, POD_EXPORT_UNAVAILABLE_LABEL)
  if (unavailable) children.push(unavailable)
  const pending = child(POD_EXPORT_PENDING, POD_EXPORT_PENDING_LABEL)
  if (pending) children.push(pending)

  const root: ProjectArtifactGroup = {
    key: "pod-exports",
    label: "Pod exports",
    category,
    entries: [],
    children,
  }
  // Right after "Pod executions" when present, otherwise appended.
  const after = stripped.findIndex((group) => group.key === "pod-executions")
  if (after === -1) return [...stripped, root]
  return [...stripped.slice(0, after + 1), root, ...stripped.slice(after + 1)]
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

// --- verdict evidence -> artifact links ----------------------------------------

export type EvidenceResolution =
  | { kind: "linked"; artifact_id: string }
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "plain" }

const OPAQUE_SCHEME = /^(javascript|data|vbscript|blob|file|mailto|tel):/i

// A reference the projection may safely be compared against an inventory path.
// The server already emits only relative, path-safe refs; this is the belt-and-
// braces gate: no URL, no absolute path, no traversal, no control character.
// There is deliberately NO decoding and no permissive normalisation.
export function isSafeEvidenceReference(reference: string): boolean {
  if (!reference) return false
  if (reference.startsWith("/")) return false
  if (reference.includes("\\") || reference.includes("\u0000")) return false
  if (/[\n\r\t]/.test(reference)) return false
  if (/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(reference)) return false
  if (OPAQUE_SCHEME.test(reference)) return false
  if (reference.split("/").some((segment) => segment === "." || segment === "..")) return false
  return true
}

export interface ArtifactPathIndex {
  projectId: string | null
  // relative_path -> its entries. More than one entry is ambiguous, never a guess.
  byPath: Map<string, ProjectArtifactEntry[]>
}

export function buildArtifactPathIndex(
  groups: ProjectArtifactGroup[],
  projectId: string | null,
): ArtifactPathIndex {
  const byPath = new Map<string, ProjectArtifactEntry[]>()
  const visit = (level: ProjectArtifactGroup[]) => {
    for (const group of level) {
      for (const entry of group.entries) {
        const bucket = byPath.get(entry.relative_path)
        if (bucket) bucket.push(entry)
        else byPath.set(entry.relative_path, [entry])
      }
      visit(group.children)
    }
  }
  visit(groups)
  return { projectId, byPath }
}

// Resolve one evidence reference against the inventory. Only two shapes are
// accepted: an exact `relative_path`, or `<project_id>/<relative_path>` with the
// exact project prefix removed. No basename, no suffix, no substring, no
// decoding. An unsafe reference, or one whose relative_path is present more than
// once, is left plain; a safe reference with no entry is `missing`.
export function resolveEvidenceReference(
  reference: string,
  index: ArtifactPathIndex,
): EvidenceResolution {
  if (!isSafeEvidenceReference(reference)) return { kind: "plain" }
  const candidate =
    index.projectId && reference.startsWith(`${index.projectId}/`)
      ? reference.slice(index.projectId.length + 1)
      : reference
  if (!isSafeEvidenceReference(candidate)) return { kind: "plain" }
  const matches = index.byPath.get(candidate)
  if (!matches || matches.length === 0) return { kind: "missing" }
  if (matches.length > 1) return { kind: "plain" }
  return { kind: "linked", artifact_id: matches[0].artifact_id }
}
