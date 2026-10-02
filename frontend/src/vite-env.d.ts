/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** BFF base URL for the agent API (projects, runs, graph). */
  readonly VITE_AGENT_BASE_URL?: string
  /** Base URL of the separate eval read API; independent of VITE_AGENT_BASE_URL. */
  readonly VITE_EVAL_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
