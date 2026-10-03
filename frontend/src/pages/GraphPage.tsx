import { Link, useParams } from "react-router-dom"
import { useGraphData } from "../graph/useGraphData"
import { GraphView } from "../graph/GraphView"
import { projectPaths } from "../projectPaths"
import { ProjectNav } from "./ProjectNav"

export function GraphPage() {
  const { projectId = "" } = useParams()
  const { data, loading, error } = useGraphData(projectId)
  return (
    <main>
      <header style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Link to="/">back</Link> <Link to={projectPaths.runs(projectId)}>running runs</Link>
        <ProjectNav projectId={projectId} active="graph" />
      </header>
      <GraphView
        data={data}
        loading={loading}
        error={error}
        label="Live project graph"
      />
    </main>
  )
}
