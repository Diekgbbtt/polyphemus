import type { Project, GraphData, ProjectUsage, RunsResponse } from "./types"

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

export async function getProjects(signal?: AbortSignal): Promise<Project[]> {
  return (await getJSON<{ projects: Project[] }>("/projects", signal)).projects
}
export async function getGraph(projectId: string, signal?: AbortSignal): Promise<GraphData> {
  return getJSON<GraphData>(`/projects/${projectId}/graph`, signal)
}
export async function getRunningRuns(signal?: AbortSignal): Promise<RunsResponse> {
  return getJSON<RunsResponse>("/runs?status=running", signal)
}
// The project's CUMULATIVE token usage, read straight from the app's in-memory
// ledger. It is not per-run and it resets with the process, so callers label it
// "Usage corrente progetto" and never present it as a current context window.
export async function getProjectUsage(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectUsage> {
  return getJSON<ProjectUsage>(`/projects/${projectId}/usage`, signal)
}
