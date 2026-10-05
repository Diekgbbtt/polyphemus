import { useCallback, useEffect, useRef, useState } from "react"

// The dashboard is read-only, so every view refreshes by re-reading the same
// endpoints. This one hook owns that cadence for every resource: an immediate
// load, a periodic re-read only while the tab is visible, a re-read when the
// tab becomes visible again, and a manual `refresh()`. It never overlaps two
// requests for the same resource, aborts the in-flight one when the identity
// changes or the component unmounts, and bounds every request with a finite
// timeout so a hung connection can never freeze the polling forever.
export const DEFAULT_POLL_INTERVAL_MS = 15_000
export const DEFAULT_REQUEST_TIMEOUT_MS = 15_000

export interface PolledResource<T> {
  // The last successfully loaded value; kept across a failed refresh.
  data: T | null
  // The most recent failure, or null once a request succeeds.
  error: string | null
  // True only until the first request for the current identity settles, so a
  // poll never flashes the full-page loading state over visible data.
  loading: boolean
  // When the last request succeeded. Distinct from any trial's recorded time.
  lastUpdatedAt: number | null
  refresh: () => void
}

export interface UsePolledResourceOptions<T> {
  // The resource identity. Changing it resets the state and re-reads.
  key: string
  load: (signal: AbortSignal) => Promise<T>
  intervalMs?: number
  timeoutMs?: number
  // Bumping this re-reads without resetting the visible value: the way a single
  // "Aggiorna" button reaches sources owned by nested components.
  refreshToken?: number
  // Injectable for tests; default reads the real tab visibility.
  isVisible?: () => boolean
  now?: () => number
}

interface PolledState<T> {
  data: T | null
  error: string | null
  loading: boolean
  lastUpdatedAt: number | null
}

function initialState<T>(): PolledState<T> {
  return { data: null, error: null, loading: true, lastUpdatedAt: null }
}

// The tab polls only while visible. A hidden tab does no periodic work and
// re-reads the moment it comes back.
export function isBrowserVisible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden"
}

function timeoutError(): Error {
  const error = new Error("request timed out")
  error.name = "TimeoutError"
  return error
}

// A tiny deterministic clock for the "last updated" indicator: local wall time,
// always HH:MM:SS, never a locale-dependent format.
export function formatClockTime(timestamp: number): string {
  const date = new Date(timestamp)
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function toMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function usePolledResource<T>({
  key,
  load,
  intervalMs = DEFAULT_POLL_INTERVAL_MS,
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  refreshToken,
  isVisible = isBrowserVisible,
  now = Date.now,
}: UsePolledResourceOptions<T>): PolledResource<T> {
  const [state, setState] = useState<PolledState<T>>(initialState)
  // Read the latest callbacks through refs so a caller may pass inline closures
  // without restarting the poll on every render.
  const loadRef = useRef(load)
  const isVisibleRef = useRef(isVisible)
  const nowRef = useRef(now)
  const runRef = useRef<((force?: boolean) => void) | null>(null)
  const tokenRef = useRef(refreshToken)

  useEffect(() => {
    loadRef.current = load
    isVisibleRef.current = isVisible
    nowRef.current = now
  })

  useEffect(() => {
    let disposed = false
    let inFlight = false
    let pending = false
    let controller: AbortController | null = null

    setState(initialState<T>())

    const run = (force = false) => {
      if (disposed) return
      // One request per resource: a tick while one is open is skipped, and an
      // explicit refresh is deferred until it settles, so a slow response can
      // never be overlapped or silently drop a manual "Aggiorna".
      if (inFlight) {
        if (force) pending = true
        return
      }
      inFlight = true
      const current = new AbortController()
      controller = current
      let timeoutId: ReturnType<typeof setTimeout> | undefined

      const timeout = new Promise<never>((_resolve, reject) => {
        timeoutId = setTimeout(() => {
          current.abort()
          reject(timeoutError())
        }, timeoutMs)
      })

      Promise.race([loadRef.current(current.signal), timeout])
        .then((value) => {
          if (disposed || controller !== current) return
          setState({ data: value, error: null, loading: false, lastUpdatedAt: nowRef.current() })
        })
        .catch((error: unknown) => {
          // A failure keeps the previous value on screen and only records the
          // error; the next request clears it.
          if (disposed || controller !== current) return
          setState((prev) => ({ ...prev, error: toMessage(error), loading: false }))
        })
        .finally(() => {
          if (timeoutId !== undefined) clearTimeout(timeoutId)
          if (controller !== current) return
          controller = null
          inFlight = false
          if (pending && !disposed) {
            pending = false
            run()
          }
        })
    }

    runRef.current = run
    run()

    const timer = setInterval(() => {
      if (isVisibleRef.current()) run()
    }, intervalMs)
    const onVisibility = () => {
      if (isVisibleRef.current()) run()
    }
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility)
    }

    return () => {
      disposed = true
      runRef.current = null
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility)
      }
      clearInterval(timer)
      controller?.abort()
    }
  }, [key, intervalMs, timeoutMs])

  // A manual refresh from a parent reaches this resource without resetting it.
  useEffect(() => {
    if (tokenRef.current === refreshToken) return
    tokenRef.current = refreshToken
    runRef.current?.(true)
  }, [refreshToken])

  const refresh = useCallback(() => {
    runRef.current?.(true)
  }, [])

  return {
    data: state.data,
    error: state.error,
    loading: state.loading,
    lastUpdatedAt: state.lastUpdatedAt,
    refresh,
  }
}
