export interface Project { project_id: string; name: string; created_at: string }
export interface GraphNode { id: string; name: string; type: string; properties: Record<string, unknown> }
export interface GraphLink { source: string; target: string; type: string }
export interface GraphData { project_id: string; nodes: GraphNode[]; links: GraphLink[] }
export interface JobCounts {
  total: number; in_progress: number; success: number; degraded: number; skipped: number; failed: number
}
export interface RunningRun {
  run_id: string; project_id: string; project_name: string; status: string
  liveness: "live" | "stalled"; current_phase: number | null
  started_at: string | null; last_heartbeat_at: string | null; jobs: JobCounts
}
export interface RunsResponse { runs: RunningRun[]; liveness_ttl_seconds: number }

// The verified wire shape of `GET /projects/{id}/usage`: the process-wide,
// in-memory ledger's CUMULATIVE per-project counters plus the per-agent
// breakdown. The counters are integers and reset when the app process
// restarts; there is no per-run attribution.
//
// `context_tokens` is the prompt side (cache reads vs fresh input),
// `generated_tokens` is the output side (reasoning vs visible), `total_tokens`
// is the whole spend, and `capped_tokens` is the total minus the cache reads.
export interface UsageTokens {
  context_tokens: { cached: number; uncached: number }
  generated_tokens: { reasoning: number; visible: number }
  total_tokens: number
  capped_tokens: number
  calls: number
}
export interface ProjectUsage extends UsageTokens {
  project_id: string
  by_agent: Record<string, UsageTokens>
}
