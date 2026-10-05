import { createContext, useCallback, useContext, useMemo } from "react"
import type { ReactNode } from "react"
import { usePolledResource } from "../usePolledResource"
import { getResolvedArtifacts } from "./client"
import { useEvalRefreshToken } from "./EvalDataProvider"
import { buildArtifactPathIndex, resolveEvidenceReference } from "./projectArtifacts"
import type { EvidenceResolution } from "./projectArtifacts"
import type { ResolvedArtifactInventory } from "./types"

// The ONE resolved-artifact inventory of a Trial.
//
// The Trial workspace wraps its results and its artifact list in this provider,
// so both read a single poll instead of fetching the same endpoint twice. A
// consumer outside the workspace simply has no provider: it renders plain text
// and never issues a request of its own.
export interface ResolvedArtifactsResource {
  data: ResolvedArtifactInventory | null
  error: string | null
  loading: boolean
  lastUpdatedAt: number | null
}

const ResolvedArtifactsContext = createContext<ResolvedArtifactsResource | null>(null)

// The single inventory poll for one Trial: the immutable capture when it exists,
// otherwise the allowlisted raw project directory. Reused verbatim by the
// provider and by the standalone section, so the two can never drift.
export function useResolvedInventory({
  targetId,
  targetRunId,
  trialId,
  expectedProjectId,
}: {
  targetId: string
  targetRunId: string
  trialId: string
  expectedProjectId?: string | null
}): ResolvedArtifactsResource {
  const refreshToken = useEvalRefreshToken()
  const identity = `${targetId}\u0000${targetRunId}\u0000${trialId}\u0000${expectedProjectId ?? ""}`

  const load = useCallback(
    async (signal: AbortSignal): Promise<ResolvedArtifactInventory> => {
      const inventory = await getResolvedArtifacts(targetId, targetRunId, trialId, signal)
      // A resolved inventory that names a different project is a safe error,
      // never a silent render, and never a fallback to another source.
      if (expectedProjectId && inventory.project_id !== expectedProjectId) {
        throw new Error("Artifact inventory does not match this Trial (mismatch).")
      }
      return inventory
    },
    [targetId, targetRunId, trialId, expectedProjectId],
  )

  const resource = usePolledResource<ResolvedArtifactInventory>({
    key: identity,
    load,
    refreshToken,
  })

  return useMemo(
    () => ({
      data: resource.data,
      error: resource.error,
      loading: resource.loading,
      lastUpdatedAt: resource.lastUpdatedAt,
    }),
    [resource.data, resource.error, resource.loading, resource.lastUpdatedAt],
  )
}

export function ResolvedArtifactsProvider({
  targetId,
  targetRunId,
  trialId,
  expectedProjectId,
  children,
}: {
  targetId: string
  targetRunId: string
  trialId: string
  expectedProjectId?: string | null
  children: ReactNode
}) {
  const resource = useResolvedInventory({ targetId, targetRunId, trialId, expectedProjectId })
  return (
    <ResolvedArtifactsContext.Provider value={resource}>
      {children}
    </ResolvedArtifactsContext.Provider>
  )
}

export function useResolvedArtifactsResource(): ResolvedArtifactsResource | null {
  return useContext(ResolvedArtifactsContext)
}

// Resolve one verdict evidence reference to a detail route from the shared
// inventory. Outside the provider - or before the first load settles, or after
// an inventory error - nothing is linked and nothing is claimed absent.
export function useEvidenceResolver(
  projectId: string | null,
): (reference: string) => EvidenceResolution {
  const resource = useResolvedArtifactsResource()
  const data = resource?.data ?? null
  const index = useMemo(() => {
    if (!data || data.status !== "available") return null
    return buildArtifactPathIndex(data.groups, projectId ?? data.project_id)
  }, [data, projectId])
  const loading = !!resource && resource.loading && !data
  return useCallback(
    (reference: string): EvidenceResolution => {
      if (index) return resolveEvidenceReference(reference, index)
      if (loading) return { kind: "loading" }
      return { kind: "plain" }
    },
    [index, loading],
  )
}
