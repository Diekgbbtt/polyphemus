import type {
  EvalSnapshot,
  HistoricalProjectGraph,
  ProjectArtifactDetail,
  ProjectArtifactInventory,
} from "./types"

// The eval read API is its own service, so its base URL is deliberately
// independent of VITE_AGENT_BASE_URL (the BFF's). Read at call time so tests can
// stub the environment per case.
export function evalApiBaseUrl(): string {
  return import.meta.env.VITE_EVAL_API_BASE_URL ?? ""
}

export async function getSnapshot(): Promise<EvalSnapshot> {
  const res = await fetch(`${evalApiBaseUrl()}/snapshot`)
  if (!res.ok) throw new Error(`/snapshot -> ${res.status}`)
  return (await res.json()) as EvalSnapshot
}

// The eval API's safe failure text: the server's stable `detail` code when the
// body carries one, otherwise a path-and-status fallback. The body itself is
// never surfaced.
async function failureText(res: Response, path: string): Promise<string> {
  try {
    const body = (await res.json()) as unknown
    if (
      body &&
      typeof body === "object" &&
      typeof (body as { detail?: unknown }).detail === "string"
    ) {
      return (body as { detail: string }).detail
    }
  } catch {
    // A non-JSON body: fall through to the safe path/status text.
  }
  return `${path} -> ${res.status}`
}

function trialPath(targetId: string, targetRunId: string, trialId: string): string {
  return `/trials/${encodeURIComponent(targetId)}/${encodeURIComponent(targetRunId)}/${encodeURIComponent(trialId)}`
}

// The immutable historical graph of one materialized Trial. The eval base is
// used exclusively: VITE_AGENT_BASE_URL never influences this request.
export async function getTrialProjectGraph(
  targetId: string,
  targetRunId: string,
  trialId: string,
  signal?: AbortSignal,
): Promise<HistoricalProjectGraph> {
  const path =
    `/trials/${encodeURIComponent(targetId)}/` +
    `${encodeURIComponent(targetRunId)}/${encodeURIComponent(trialId)}/project-graph`
  const res = await fetch(`${evalApiBaseUrl()}${path}`, { signal })
  if (!res.ok) {
    throw new Error(await failureText(res, path))
  }
  return (await res.json()) as HistoricalProjectGraph
}

// The grouped artifact inventory of one materialized Trial. It stays on the
// eval API base exclusively.
export async function getProjectArtifacts(
  targetId: string,
  targetRunId: string,
  trialId: string,
  signal?: AbortSignal,
): Promise<ProjectArtifactInventory> {
  const path = `${trialPath(targetId, targetRunId, trialId)}/artifacts`
  const res = await fetch(`${evalApiBaseUrl()}${path}`, { signal })
  if (!res.ok) throw new Error(await failureText(res, path))
  return (await res.json()) as ProjectArtifactInventory
}

// One artifact's metadata plus its one safe representation.
export async function getProjectArtifact(
  targetId: string,
  targetRunId: string,
  trialId: string,
  artifactId: string,
  signal?: AbortSignal,
): Promise<ProjectArtifactDetail> {
  const path = `${trialPath(targetId, targetRunId, trialId)}/artifacts/${encodeURIComponent(artifactId)}`
  const res = await fetch(`${evalApiBaseUrl()}${path}`, { signal })
  if (!res.ok) throw new Error(await failureText(res, path))
  return (await res.json()) as ProjectArtifactDetail
}

// The raw content URL for an artifact. Pure: it builds a URL and never fetches.
export function projectArtifactContentUrl(
  targetId: string,
  targetRunId: string,
  trialId: string,
  artifactId: string,
): string {
  return (
    `${evalApiBaseUrl()}${trialPath(targetId, targetRunId, trialId)}` +
    `/artifacts/${encodeURIComponent(artifactId)}/content`
  )
}
