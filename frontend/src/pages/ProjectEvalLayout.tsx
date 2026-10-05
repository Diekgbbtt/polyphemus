import { Outlet, useParams } from "react-router-dom"
import { EvalDataProvider, useEvalData } from "../eval/EvalDataProvider"
import { EvalRefreshControls } from "../eval/EvalRefreshControls"
import { ProjectNav } from "./ProjectNav"
import "../eval/eval.css"

// The project-eval subtree's layout: one EvalDataProvider owns the `/snapshot`
// request for the list and every Trial route below it, keeps it fresh, and owns
// the shared loading/error gate.
export function ProjectEvalLayout() {
  return (
    <EvalDataProvider>
      <ProjectEvalShell />
    </EvalDataProvider>
  )
}

function ProjectEvalShell() {
  const { projectId = "" } = useParams()
  const { status, error, refreshError } = useEvalData()
  return (
    <main className="eval project-eval">
      <header className="eval-topbar">
        <p className="eval-eyebrow">Project</p>
        <ProjectNav projectId={projectId} active="evals" />
        <EvalRefreshControls />
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
      {status === "ready" && refreshError && (
        <p className="eval-notice" role="status">
          Aggiornamento non riuscito: {refreshError}. Sono mostrati i dati precedenti.
        </p>
      )}
      {status === "ready" && <Outlet />}
    </main>
  )
}
