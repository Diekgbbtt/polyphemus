import { Link } from "react-router-dom"
import { projectPaths } from "../projectPaths"

export type GlobalSection = "projects" | "live" | "evaluations"

// The site-wide entry points. Both the project shells and the eval shell render
// it, so a user can always move between the catalog and the evaluations - even
// when the live agent is unavailable. The catalog is reached through Projects
// (to "/"); there is no separate Home entry point.
export function GlobalNav({ active }: { active?: GlobalSection }) {
  return (
    <nav className="global-nav" aria-label="Global">
      <Link to="/" aria-current={active === "projects" ? "page" : undefined}>
        Projects
      </Link>
      <Link to="/live" aria-current={active === "live" ? "page" : undefined}>
        Live
      </Link>
      <Link to="/eval" aria-current={active === "evaluations" ? "page" : undefined}>
        Evaluations
      </Link>
    </nav>
  )
}

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
    <div className="project-nav-shell">
      <GlobalNav />
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
    </div>
  )
}
