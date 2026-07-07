import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// Dev-server proxy: the SPA fetches the BFF with relative paths (BASE=""), so
// without this every /projects and /runs call hits Vite's SPA fallback and gets
// index.html back ("Unexpected token '<'"). Forward the API prefixes to the BFF.
// Client routes (/, /p/:id, /p/:id/runs) don't collide with these prefixes.
const AGENT_TARGET = process.env.AGENT_PROXY_TARGET ?? "http://localhost:8080"

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/projects": { target: AGENT_TARGET, changeOrigin: true },
      "/runs": { target: AGENT_TARGET, changeOrigin: true },
    },
  },
  test: { environment: "jsdom", globals: true },
})
