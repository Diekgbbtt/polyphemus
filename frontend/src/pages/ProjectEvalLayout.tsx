import { Outlet, useParams } from "react-router-dom"
import { EvalDataProvider, useEvalData } from "../eval/EvalDataProvider"
import { ProjectNav } from "./ProjectNav"
import "../eval/eval.css"

// The project-eval subtree's layout: one EvalDataProvider owns the single
// `/snapshot` request for the list and every Trial route below it, and the
// shell owns the shared loading/error gate.
export function ProjectEvalLayout() {
  return (
    <EvalDataProvider>
      <ProjectEvalShell />
    </EvalDataProvider>
  )
}

function ProjectEvalShell() {
  const { projectId = "" } = useParams()
  const { status, error } = useEvalData()
  return (
    <main className="eval project-eval">
      <header className="eval-topbar">
        <p className="eval-eyebrow">Project</p>
        <ProjectNav projectId={projectId} active="evals" />
      </header>

      {status === "loading" && (
        <p className="eval-status" role="status">
          Loading eval results…
        </p>
      )}
      {status === "error" && (
        <p className="eval-error" role="alert">
          Failed to load eval results: {error}
        </p>
      )}
      {status === "ready" && <Outlet />}
    </main>
  )
}
