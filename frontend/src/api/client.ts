import type { Project, GraphData, RunsResponse } from "./types"

const BASE = import.meta.env.VITE_AGENT_BASE_URL ?? ""

// The live-agent HTTP failure, carrying the status so a caller can tell "this
// project has no current graph" (404) apart from a real error.
export class HttpError extends Error {
  readonly status: number

  constructor(path: string, status: number) {
    super(`${path} -> ${status}`)
    this.name = "HttpError"
    this.status = status
  }
}

async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, signal ? { signal } : undefined)
  if (!res.ok) throw new HttpError(path, res.status)
  return res.json() as Promise<T>
}

export async function getProjects(): Promise<Project[]> {
  return (await getJSON<{ projects: Project[] }>("/projects")).projects
}
export async function getGraph(projectId: string, signal?: AbortSignal): Promise<GraphData> {
  return getJSON<GraphData>(`/projects/${projectId}/graph`, signal)
}
export async function getRunningRuns(): Promise<RunsResponse> {
  return getJSON<RunsResponse>("/runs?status=running")
}
