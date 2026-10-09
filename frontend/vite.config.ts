import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// Dev-server proxy: the SPA fetches the BFF with relative paths (BASE=""), so
// without this every /projects and /runs call hits Vite's SPA fallback and gets
// index.html back ("Unexpected token '<'"). Forward the API prefixes to the BFF.
// Client routes (/, /p/:id, /p/:id/runs, /eval) don't collide with these prefixes.
const AGENT_TARGET = process.env.AGENT_PROXY_TARGET ?? "http://localhost:8080"
// The eval read API is a separate service; it is proxied under its own prefix so
// a relative VITE_EVAL_API_BASE_URL (e.g. "/eval-api") reaches it in dev.
const EVAL_TARGET = process.env.EVAL_PROXY_TARGET ?? "http://localhost:8090"

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/projects": { target: AGENT_TARGET, changeOrigin: true },
      "/runs": { target: AGENT_TARGET, changeOrigin: true },
      "/app-state": { target: AGENT_TARGET, changeOrigin: true },
      "/eval-api": { target: EVAL_TARGET, changeOrigin: true, rewrite: (p) => p.replace(/^\/eval-api/, "") },
    },
  },
  test: { environment: "jsdom", globals: true },
})
