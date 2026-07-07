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
