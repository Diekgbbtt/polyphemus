import { BrowserRouter, Routes, Route } from "react-router-dom"
import { ProjectsPage } from "./pages/ProjectsPage"
import { GraphPage } from "./pages/GraphPage"
import { RunsPage } from "./pages/RunsPage"

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/p/:id" element={<GraphPage />} />
        <Route path="/p/:id/runs" element={<RunsPage />} />
      </Routes>
    </BrowserRouter>
  )
}
