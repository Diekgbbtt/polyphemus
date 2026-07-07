import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { getProjects } from "../api/client"
import type { Project } from "../api/types"

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getProjects().then(setProjects).catch((e) => setError(String(e))) }, [])
  if (error) return <p role="alert">Failed to load projects: {error}</p>
  return (
    <main>
      <h1>Projects</h1>
      <ul>{projects.map((p) => (
        <li key={p.project_id}><Link to={`/p/${p.project_id}`}>{p.name}</Link></li>
      ))}</ul>
    </main>
  )
}
