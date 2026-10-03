// Pure display helpers for the project-artifact inventory. No React, no fetch,
// no state: the server's grouping and order are authoritative.
import type {
  ProjectArtifactCategory,
  ProjectArtifactEntry,
  ProjectArtifactGroup,
  ProjectArtifactKind,
  ProjectArtifactRepresentation,
} from "./types"

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
