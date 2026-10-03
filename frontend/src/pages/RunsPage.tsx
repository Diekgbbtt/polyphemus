import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { getRunningRuns } from "../api/client"
import type { RunningRun } from "../api/types"
import { projectPaths } from "../projectPaths"
import { ProjectNav } from "./ProjectNav"

export function RunsPage() {
  const { projectId = "" } = useParams()
  const [runs, setRuns] = useState<RunningRun[]>([])
  useEffect(() => {
    let alive = true
    const tick = () => getRunningRuns().then((r) => { if (alive) setRuns(r.runs) }).catch(() => {})
    tick()
    const h = setInterval(tick, 2500)
    return () => { alive = false; clearInterval(h) }
  }, [])
  const mine = runs.filter((r) => r.project_id === projectId)
  return (
    <main>
      <header style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Link to={projectPaths.live(projectId)}>back to graph</Link>
        <ProjectNav projectId={projectId} active="runs" />
      </header>
      <h1>Running recon runs</h1>
      {mine.length === 0 && <p>No running runs.</p>}
      <ul>{mine.map((r) => (
        <li key={r.run_id}>
          <span>{r.run_id.slice(0, 8)}</span>
          <span data-liveness={r.liveness}> [{r.liveness}]</span>
          <span> phase {r.current_phase ?? "-"} - {r.jobs.success}/{r.jobs.total} jobs</span>
        </li>
      ))}</ul>
    </main>
  )
}
