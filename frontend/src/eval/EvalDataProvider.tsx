import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { getSnapshot } from "./client"
import type { EvalSnapshot } from "./types"

export type EvalStatus = "loading" | "error" | "ready"

export interface EvalData {
  status: EvalStatus
  snapshot: EvalSnapshot | null
  error: string | null
}

const EvalDataContext = createContext<EvalData | null>(null)

// Loads `/snapshot` exactly once and shares loading/error/data with every eval
// route. No polling, no mutation: one fetch for the whole section.
export function EvalDataProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<EvalData>({
    status: "loading",
    snapshot: null,
    error: null,
  })

  useEffect(() => {
    let alive = true
    getSnapshot()
      .then((snapshot) => {
        if (alive) setState({ status: "ready", snapshot, error: null })
      })
      .catch((e: unknown) => {
        if (alive) {
          setState({
            status: "error",
            snapshot: null,
            error: e instanceof Error ? e.message : String(e),
          })
        }
      })
    return () => {
      alive = false
    }
  }, [])

  return <EvalDataContext.Provider value={state}>{children}</EvalDataContext.Provider>
}

export function useEvalData(): EvalData {
  const context = useContext(EvalDataContext)
  if (!context) {
    throw new Error("useEvalData must be used inside an EvalDataProvider")
  }
  return context
}
