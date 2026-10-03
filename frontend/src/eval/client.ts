import type { EvalSnapshot, HistoricalProjectGraph } from "./types"

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
    // Carry only the server's stable failure code; never the body or any path
    // beyond the safe request path.
    let detail: string | null = null
    try {
      const body = (await res.json()) as unknown
      if (
        body &&
        typeof body === "object" &&
        typeof (body as { detail?: unknown }).detail === "string"
      ) {
        detail = (body as { detail: string }).detail
      }
    } catch {
      detail = null
    }
    throw new Error(detail ?? `${path} -> ${res.status}`)
  }
  return (await res.json()) as HistoricalProjectGraph
}
