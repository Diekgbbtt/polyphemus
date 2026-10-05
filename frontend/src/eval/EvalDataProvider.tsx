import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react"
import { usePolledResource } from "../usePolledResource"
import { getSnapshot } from "./client"
import type { EvalSnapshot } from "./types"

export type EvalStatus = "loading" | "error" | "ready"

export interface EvalData {
  status: EvalStatus
  snapshot: EvalSnapshot | null
  // The first-load failure. It is a hard error only while nothing is on screen.
  error: string | null
  // A failure that happened while data was already visible: the previous
  // snapshot stays, and the shell shows this as a soft notice.
  refreshError: string | null
  // When `/snapshot` last succeeded. Distinct from any Trial's copied_at.
  lastUpdatedAt: number | null
  refresh: () => void
}

const EvalDataContext = createContext<EvalData | null>(null)
// A counter bumped by every manual refresh. Nested read-only sources (a Trial's
// resolved graph and inventory) watch it so one "Aggiorna" reaches them too.
const EvalRefreshContext = createContext<number>(0)

// Loads `/snapshot`, re-reads it every 15s while the tab is visible, re-reads it
// when the tab returns, and exposes a manual `refresh()`. A refresh never blanks
// the section: the previous snapshot stays until a newer one replaces it.
export function EvalDataProvider({ children }: { children: ReactNode }) {
  const [refreshToken, setRefreshToken] = useState(0)
  const resource = usePolledResource<EvalSnapshot>({
    key: "snapshot",
    load: (signal) => getSnapshot(signal),
  })

  const refresh = useCallback(() => {
    setRefreshToken((token) => token + 1)
    resource.refresh()
  }, [resource.refresh])

  const value: EvalData = {
    status: resource.loading ? "loading" : resource.data ? "ready" : "error",
    snapshot: resource.data,
    error: resource.data ? null : resource.error,
    refreshError: resource.data ? resource.error : null,
    lastUpdatedAt: resource.lastUpdatedAt,
    refresh,
  }

  return (
    <EvalDataContext.Provider value={value}>
      <EvalRefreshContext.Provider value={refreshToken}>
        {children}
      </EvalRefreshContext.Provider>
    </EvalDataContext.Provider>
  )
}

export function useEvalData(): EvalData {
  const context = useContext(EvalDataContext)
  if (!context) {
    throw new Error("useEvalData must be used inside an EvalDataProvider")
  }
  return context
}

// The manual-refresh generation. It reads 0 outside a provider, so the read-only
// sections stay usable in isolation (and in their own unit tests).
export function useEvalRefreshToken(): number {
  return useContext(EvalRefreshContext)
}
