import { Link } from "react-router-dom"
import { projectPaths } from "../projectPaths"

export type ProjectSection = "graph" | "runs" | "evals"

// The shared project navigation: the one entry point for the live graph, the
// operational runs, and the materialized eval Trials.
export function ProjectNav({
  projectId,
  active,
}: {
  projectId: string
  active?: ProjectSection
}) {
  return (
    <nav className="project-nav" aria-label="Project sections">
      <Link to={projectPaths.live(projectId)} aria-current={active === "graph" ? "page" : undefined}>
        Graph
      </Link>
      <Link to={projectPaths.runs(projectId)} aria-current={active === "runs" ? "page" : undefined}>
        Runs
      </Link>
      <Link to={projectPaths.evals(projectId)} aria-current={active === "evals" ? "page" : undefined}>
        Eval Trials
      </Link>
    </nav>
  )
}
