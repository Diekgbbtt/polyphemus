import type { Project, GraphData, RunsResponse } from "./types"

const BASE = import.meta.env.VITE_AGENT_BASE_URL ?? ""

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${path} -> ${res.status}`)
  return res.json() as Promise<T>
}

export async function getProjects(): Promise<Project[]> {
  return (await getJSON<{ projects: Project[] }>("/projects")).projects
}
export async function getGraph(projectId: string): Promise<GraphData> {
  return getJSON<GraphData>(`/projects/${projectId}/graph`)
}
export async function getRunningRuns(): Promise<RunsResponse> {
  return getJSON<RunsResponse>("/runs?status=running")
}
