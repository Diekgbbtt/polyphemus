import { Link, Outlet } from "react-router-dom"
import { GlobalNav } from "../pages/ProjectNav"
import { evalPaths } from "./EvalBreadcrumbs"
import { EvalDataProvider, useEvalData } from "./EvalDataProvider"
import { EvalRefreshControls } from "./EvalRefreshControls"
import "./eval.css"

// The eval section's layout: one provider loads and keeps `/snapshot` fresh for
// every child route, and the shell owns the shared loading/error gate plus the
// top nav.
export function EvalPage() {
  return (
    <EvalDataProvider>
      <EvalShell />
    </EvalDataProvider>
  )
}

function EvalShell() {
  const { status, error, refreshError } = useEvalData()
  return (
    <main className="eval">
      <header className="eval-topbar">
        <GlobalNav active="evaluations" />
        <p className="eval-eyebrow">Evaluation</p>
        <nav className="eval-topnav" aria-label="Eval sections">
          <Link to={evalPaths.dashboard}>Dashboard</Link>
          <Link to={evalPaths.vulnerabilities}>Successful vulnerabilities</Link>
        </nav>
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
          Refresh failed: {refreshError}. The previous data is still shown.
        </p>
      )}
      {status === "ready" && <Outlet />}
    </main>
  )
}
