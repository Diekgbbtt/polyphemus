import { usePolledResource } from "../usePolledResource"
import { listProjectArtifacts } from "./client"
import { artifactCount } from "./ResolvedArtifactsSection"
import {
  artifactKey,
  artifactSections,
  groupKey,
  groupLabel,
  kindLabel,
  representationLabel,
} from "./projectArtifacts"
import type { ProjectArtifactGroup, ResolvedArtifactInventory } from "./types"

// The project's own tree changes only when a producer writes a file, so this
// does not need the live board's cadence.
const ARTIFACTS_POLL_MS = 30_000

// One project's Hunting and Skill files, read straight from the project data
// root with no Trial in the path. It lists what the project produced - names,
// kinds and sizes - and deliberately has no links: opening a file is the Trial
// artifact detail's job, and this block never pretends to be a Trial.
export function ProjectArtifactsBlock({ projectId }: { projectId: string }) {
  const { data, error, loading } = usePolledResource<ResolvedArtifactInventory>({
    key: `project-artifacts:${projectId}`,
    load: (signal) => listProjectArtifacts(projectId, signal),
    intervalMs: ARTIFACTS_POLL_MS,
  })

  const unavailable = data && data.status !== "available" ? data : null
  const groups = data?.status === "available" ? data.groups ?? [] : []
  const sections = artifactSections(groups).filter(
    (section) => section.groups.length > 0,
  )

  if (unavailable) {
    return (
      <p className="project-block-muted">
        Project artifacts unavailable
        {unavailable.reason ? ` (${unavailable.reason})` : ""}.
      </p>
    )
  }
  if (!data) {
    return (
      <p className="project-block-muted">
        {loading ? "Loading project artifacts…" : "Project artifacts unavailable."}
      </p>
    )
  }
  if (sections.length === 0) {
    return (
      <p className="project-block-muted">No artifacts were saved for this project.</p>
    )
  }
  return (
    <>
      {error !== null && (
        <p className="project-block-muted">
          Project artifacts not up to date — showing the last reading.
        </p>
      )}
      {sections.map((section) => (
        <div key={section.category} className="project-artifact-section">
          <h3 className="project-artifact-section-title">{section.label}</h3>
          <ArtifactGroups groups={section.groups} />
        </div>
      ))}
    </>
  )
}

// The group tree as nested, always-open lists: a group header carries its name
// and the number of files beneath it, then each file one line.
function ArtifactGroups({ groups }: { groups: ProjectArtifactGroup[] }) {
  return (
    <ul className="project-artifact-groups">
      {groups.map((group) => (
        <li key={groupKey(group)}>
          <p className="project-artifact-group">
            <span className="project-artifact-group-label">{groupLabel(group)}</span>
            <span className="project-artifact-group-count">{artifactCount(group)}</span>
          </p>
          {group.entries.length > 0 && (
            <ul className="project-artifact-entries">
              {group.entries.map((entry) => (
                <li key={artifactKey(entry)} className="project-artifact-entry">
                  <span className="project-artifact-path">{entry.relative_path}</span>
                  <span className="project-artifact-meta">
                    {kindLabel(entry.kind)} · {representationLabel(entry.representation)} ·{" "}
                    {bytesLabel(entry.size_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {group.children.length > 0 && <ArtifactGroups groups={group.children} />}
        </li>
      ))}
    </ul>
  )
}

function bytesLabel(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
