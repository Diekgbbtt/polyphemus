import { useEffect, useState } from "react"

// The operator-only ground-truth client.
//
// This is deliberately independent of the eval read API and of the agent BFF:
// the reference is served by its own service, reached through a second SSH
// forward. A missing forward must simply leave the reference unavailable - it
// must never make the client try another API, and it must never surface a raw
// HTTP body, a host path, or a filesystem detail.

export interface GroundTruthEntry {
  vuln_id: string
  location: string
  type: string
  scoring: string[]
}

export interface OperatorGroundTruth {
  target_id: string
  provenance: "current_benchmark_checkout"
  vulnerabilities: GroundTruthEntry[]
}

export type GroundTruthState =
  | { status: "disabled" }
  | { status: "loading" }
  | { status: "unavailable" }
  | { status: "ready"; data: OperatorGroundTruth }

export const DEFAULT_OPERATOR_GT_BASE_URL = "http://localhost:18091"
export const OPERATOR_GT_UNAVAILABLE = "operator ground truth unavailable"
export const GROUND_TRUTH_FALLBACK = "Ground truth unavailable"

// One stable, path-free failure: every rejection mode (bad configuration,
// network error, non-2xx, malformed or mismatched payload) is this error.
export class OperatorGroundTruthError extends Error {
  constructor() {
    super(OPERATOR_GT_UNAVAILABLE)
    this.name = "OperatorGroundTruthError"
  }
}

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"])

// The configured base, or the loopback default. An override is accepted only
// when it is an http(s) loopback origin with no credentials, query or fragment;
// anything else is a configuration error rather than a silent fallback.
export function operatorGroundTruthBaseUrl(): string {
  const raw = import.meta.env.VITE_OPERATOR_GT_API_BASE_URL
  if (!raw) return DEFAULT_OPERATOR_GT_BASE_URL
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    throw new OperatorGroundTruthError()
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new OperatorGroundTruthError()
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new OperatorGroundTruthError()
  }
  if (!LOOPBACK_HOSTS.has(url.hostname.toLowerCase())) {
    throw new OperatorGroundTruthError()
  }
  return `${url.protocol}//${url.host}${url.pathname.replace(/\/+$/, "")}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isSafeIdentifier(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value !== "." &&
    value !== ".." &&
    !value.includes("/") &&
    !value.includes("\\")
  )
}

// The wire shape, checked before it is trusted: the response must be for the
// target that was asked for, carry the expected provenance, and describe each
// vulnerability once. A conflicting duplicate is rejected outright rather than
// letting the first or last copy win.
export function parseOperatorGroundTruth(
  payload: unknown,
  targetId: string,
): OperatorGroundTruth {
  if (!isRecord(payload)) throw new OperatorGroundTruthError()
  if (payload.target_id !== targetId) throw new OperatorGroundTruthError()
  if (payload.provenance !== "current_benchmark_checkout") {
    throw new OperatorGroundTruthError()
  }
  if (!Array.isArray(payload.vulnerabilities)) throw new OperatorGroundTruthError()

  const entries: GroundTruthEntry[] = []
  const signatures = new Map<string, string>()
  for (const raw of payload.vulnerabilities) {
    if (!isRecord(raw)) throw new OperatorGroundTruthError()
    if (!isSafeIdentifier(raw.vuln_id)) throw new OperatorGroundTruthError()
    if (typeof raw.location !== "string" || typeof raw.type !== "string") {
      throw new OperatorGroundTruthError()
    }
    if (!Array.isArray(raw.scoring)) throw new OperatorGroundTruthError()
    const scoring: string[] = []
    for (const signal of raw.scoring) {
      if (typeof signal !== "string") throw new OperatorGroundTruthError()
      scoring.push(signal)
    }
    const entry: GroundTruthEntry = {
      vuln_id: raw.vuln_id,
      location: raw.location,
      type: raw.type,
      scoring,
    }
    const signature = JSON.stringify(entry)
    const previous = signatures.get(entry.vuln_id)
    if (previous !== undefined) {
      if (previous !== signature) throw new OperatorGroundTruthError()
      continue
    }
    signatures.set(entry.vuln_id, signature)
    entries.push(entry)
  }
  return {
    target_id: targetId,
    provenance: "current_benchmark_checkout",
    vulnerabilities: entries,
  }
}

export async function getOperatorGroundTruth(
  targetId: string,
  signal?: AbortSignal,
): Promise<OperatorGroundTruth> {
  const base = operatorGroundTruthBaseUrl()
  const url = `${base}/ground-truth/targets/${encodeURIComponent(targetId)}`
  let response: Response
  try {
    response = await fetch(url, { signal })
  } catch {
    throw new OperatorGroundTruthError()
  }
  if (!response.ok) throw new OperatorGroundTruthError()
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new OperatorGroundTruthError()
  }
  return parseOperatorGroundTruth(payload, targetId)
}

// The request lifecycle: exactly one request per displayed target, nothing at
// all when disabled, and an abort on identity change. The stored state is keyed
// by the target it belongs to, so the render between a target change and the
// effect cleanup can never show the previous target's reference.
export function useOperatorGroundTruth(
  targetId: string,
  enabled: boolean,
): GroundTruthState {
  const [stored, setStored] = useState<{ targetId: string; state: GroundTruthState }>(
    () => ({
      targetId,
      state: enabled ? { status: "loading" } : { status: "disabled" },
    }),
  )

  useEffect(() => {
    if (!enabled) {
      setStored({ targetId, state: { status: "disabled" } })
      return
    }
    const controller = new AbortController()
    let active = true
    setStored({ targetId, state: { status: "loading" } })
    getOperatorGroundTruth(targetId, controller.signal)
      .then((data) => {
        if (active) setStored({ targetId, state: { status: "ready", data } })
      })
      .catch(() => {
        if (active) setStored({ targetId, state: { status: "unavailable" } })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [targetId, enabled])

  if (!enabled) return { status: "disabled" }
  if (stored.targetId !== targetId) return { status: "loading" }
  return stored.state
}
