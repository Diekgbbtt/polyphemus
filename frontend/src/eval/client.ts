import type { EvalSnapshot } from "./types"

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
