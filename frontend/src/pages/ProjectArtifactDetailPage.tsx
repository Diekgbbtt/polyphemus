import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import "../eval/eval.css"
import {
  getProjectArtifactDetail,
  projectArtifactDetailContentUrl,
} from "../eval/client"
import { Metadata } from "../eval/ProjectArtifactPage"
import { ProjectArtifactRenderer } from "../eval/ProjectArtifactRenderers"
import type { ResolvedArtifactDetail } from "../eval/types"
import { projectPaths } from "../projectPaths"

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "AbortError"
  )
}

// One artifact of one project, read from the project's own tree: the same
// metadata, safe preview and digest-bound download the Trial detail serves, with
// no Trial in the path. The route is the project-scoped sibling of the Trial
// artifact route, so an unassigned project's files open exactly like a Trial's.
export function ProjectArtifactDetailPage() {
  const { projectId = "", artifactId = "" } = useParams()
  const [detail, setDetail] = useState<ResolvedArtifactDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setDetail(null)
    setError(null)
    setLoading(true)
    getProjectArtifactDetail(projectId, artifactId, controller.signal)
      .then((response) => {
        if (!active) return
        if (response.entry.artifact_id !== artifactId) {
          setError("Artifact detail does not match the requested id (mismatch).")
          setLoading(false)
          return
        }
        setDetail(response)
        setLoading(false)
      })
      .catch((cause: unknown) => {
        if (!active || isAbortError(cause)) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [projectId, artifactId])

  const label = detail?.entry.relative_path ?? artifactId
  // The download URL is always rebuilt here, bound to the digest the detail
  // returned: the server's own field is never trusted for the link.
  const contentUrl = projectArtifactDetailContentUrl(
    projectId,
    artifactId,
    detail?.entry.sha256 ?? "",
  )

  return (
    <div className="eval-page project-artifact">
      <nav className="eval-crumbs" aria-label="Breadcrumb">
        <ol>
          <li>
            <Link to={projectPaths.live(projectId)}>Project</Link>
          </li>
          <li>
            <span aria-current="page">{label}</span>
          </li>
        </ol>
      </nav>

      <header className="eval-header eval-trial-header">
        <h1>Artifact</h1>
        <p className="project-trial-identity">
          project <span className="eval-ref">{projectId}</span>
        </p>
      </header>

      {loading && <p className="eval-status">Loading artifact…</p>}
      {error !== null && (
        <p className="eval-error" role="alert">
          Artifact load error: {error}
        </p>
      )}
      {detail && (
        <>
          <Metadata detail={detail} />
          <p className="artifact-actions">
            <a className="artifact-download" href={contentUrl} download>
              Download raw
            </a>
          </p>
          <ProjectArtifactRenderer detail={detail} />
        </>
      )}
    </div>
  )
}
