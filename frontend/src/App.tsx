import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom"
import { ProjectsPage } from "./pages/ProjectsPage"
import { GraphPage } from "./pages/GraphPage"
import { RunsPage } from "./pages/RunsPage"
import { ProjectEvalLayout } from "./pages/ProjectEvalLayout"
import { ProjectEvalsPage } from "./pages/ProjectEvalsPage"
import { ProjectTrialPage } from "./pages/ProjectTrialPage"
import { ProjectArtifactsPage } from "./eval/ProjectArtifactsPage"
import { ProjectArtifactPage } from "./eval/ProjectArtifactPage"
import { EvalPage } from "./eval/EvalPage"
import { EvalDashboard } from "./eval/EvalDashboard"
import { DatasetPage } from "./eval/DatasetPage"
import { TargetPage } from "./eval/TargetPage"
import { TrialPage } from "./eval/TrialPage"
import { TrialArtifactPage } from "./eval/TrialArtifactPage"
import { VersionPage } from "./eval/VersionPage"
import { SuccessfulVulnerabilitiesPage } from "./eval/SuccessfulVulnerabilitiesPage"
import { targetPaths } from "./projectPaths"

// Compatibility redirects: the canonical Target/Trial routes are primary, and
// every legacy eval deep link keeps its full Trial identity.
function LegacyTargetRedirect() {
  const { targetId = "" } = useParams()
  return <Navigate to={targetPaths.target(targetId)} replace />
}

function LegacyTrialRedirect() {
  const { targetId = "", targetRunId = "", trialId = "" } = useParams()
  return <Navigate to={targetPaths.trial(targetId, targetRunId, trialId)} replace />
}

// The route table without a router, so tests can drive it with a MemoryRouter.
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<ProjectsPage />} />
      {/* `/p` is the legacy bare project path: the catalog now owns `/`. */}
      <Route path="/p" element={<Navigate to="/" replace />} />
      <Route path="/p/:projectId" element={<GraphPage />} />
      <Route path="/p/:projectId/runs" element={<RunsPage />} />
      {/* The project eval subtree shares one provider for list and detail. */}
      <Route path="/p/:projectId/evals" element={<ProjectEvalLayout />}>
        <Route index element={<ProjectEvalsPage />} />
        <Route
          path=":targetId/:targetRunId/:trialId"
          element={<ProjectTrialPage />}
        />
        {/* The primary, project-scoped artifact index. */}
        <Route
          path=":targetId/:targetRunId/:trialId/artifacts"
          element={<ProjectArtifactsPage variant="workspace" />}
        />
        <Route
          path=":targetId/:targetRunId/:trialId/artifacts/:artifactId"
          element={<ProjectArtifactPage variant="workspace" />}
        />
      </Route>
      {/* The eval layout holds one data provider for every child route. */}
      {/* The canonical Target -> Trial workspace. */}
      <Route path="/targets" element={<EvalPage />}>
        <Route path=":targetId" element={<TargetPage />} />
        <Route
          path=":targetId/trials/:targetRunId/:trialId"
          element={<TrialPage />}
        />
      </Route>
      <Route path="/eval" element={<EvalPage />}>
        <Route index element={<EvalDashboard />} />
        <Route path="datasets/:datasetId" element={<DatasetPage />} />
        {/* Legacy eval links redirect to the canonical Target/Trial routes. */}
        <Route path="targets/:targetId" element={<LegacyTargetRedirect />} />
        <Route
          path="trials/:targetId/:targetRunId/:trialId"
          element={<LegacyTrialRedirect />}
        />
        {/* The compatibility artifact index for the eval routes. */}
        <Route
          path="trials/:targetId/:targetRunId/:trialId/project-artifacts"
          element={<ProjectArtifactsPage variant="eval" />}
        />
        <Route
          path="trials/:targetId/:targetRunId/:trialId/project-artifacts/:artifactId"
          element={<ProjectArtifactPage variant="eval" />}
        />
        {/* The four materialized artifacts, each with its own readable view. */}
        <Route
          path="trials/:targetId/:targetRunId/:trialId/manifest"
          element={<TrialArtifactPage artifact="manifest" />}
        />
        <Route
          path="trials/:targetId/:targetRunId/:trialId/verdicts"
          element={<TrialArtifactPage artifact="verdicts" />}
        />
        <Route
          path="trials/:targetId/:targetRunId/:trialId/diagnoses"
          element={<TrialArtifactPage artifact="diagnoses" />}
        />
        <Route
          path="trials/:targetId/:targetRunId/:trialId/evidence"
          element={<TrialArtifactPage artifact="evidence" />}
        />
        <Route path="versions/:evalSha/:stackFingerprint" element={<VersionPage />} />
        <Route path="vulnerabilities" element={<SuccessfulVulnerabilitiesPage />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
