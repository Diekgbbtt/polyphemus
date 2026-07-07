import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Routes, Route } from "react-router-dom"
import { RunsPage } from "./RunsPage"

test("runs page shows a stalled badge", async () => {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ liveness_ttl_seconds: 30, runs: [
      { run_id: "r1", project_id: "p1", project_name: "acme", status: "running",
        liveness: "stalled", current_phase: 1, started_at: null, last_heartbeat_at: null,
        jobs: { total: 2, in_progress: 0, success: 1, degraded: 1, skipped: 0, failed: 0 } }] }),
      { status: 200 })) as typeof fetch
  render(<MemoryRouter initialEntries={["/p/p1/runs"]}>
    <Routes><Route path="/p/:id/runs" element={<RunsPage />} /></Routes></MemoryRouter>)
  await waitFor(() => expect(screen.getByText(/stalled/i)).toBeDefined())
})
