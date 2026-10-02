import { BrowserRouter, Routes, Route } from "react-router-dom"
import { ProjectsPage } from "./pages/ProjectsPage"
import { GraphPage } from "./pages/GraphPage"
import { RunsPage } from "./pages/RunsPage"
import { EvalPage } from "./eval/EvalPage"
import { EvalDashboard } from "./eval/EvalDashboard"
import { DatasetPage } from "./eval/DatasetPage"
import { TargetPage } from "./eval/TargetPage"
import { TrialPage } from "./eval/TrialPage"
import { TrialArtifactPage } from "./eval/TrialArtifactPage"
import { VersionPage } from "./eval/VersionPage"
import { SuccessfulVulnerabilitiesPage } from "./eval/SuccessfulVulnerabilitiesPage"

// The route table without a router, so tests can drive it with a MemoryRouter.
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<ProjectsPage />} />
      <Route path="/p/:id" element={<GraphPage />} />
      <Route path="/p/:id/runs" element={<RunsPage />} />
      {/* The eval layout holds one data provider for every child route. */}
      <Route path="/eval" element={<EvalPage />}>
        <Route index element={<EvalDashboard />} />
        <Route path="datasets/:datasetId" element={<DatasetPage />} />
        <Route path="targets/:targetId" element={<TargetPage />} />
        <Route path="trials/:targetId/:targetRunId/:trialId" element={<TrialPage />} />
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
