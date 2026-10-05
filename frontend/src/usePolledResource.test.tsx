import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, expect, test, vi } from "vitest"
import { usePolledResource } from "./usePolledResource"

const INTERVAL = 15_000

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

// A promise whose settlement the test controls, so a slow request can be held
// open across a poll tick.
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

test("loads immediately and records the last successful update", async () => {
  const load = vi.fn(async () => "one")
  const { result } = renderHook(() =>
    usePolledResource({ key: "k", load, now: () => 111 }),
  )

  expect(result.current.loading).toBe(true)
  await act(async () => {})

  expect(result.current.data).toBe("one")
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeNull()
  expect(result.current.lastUpdatedAt).toBe(111)
})

test("re-reads on the interval and replaces the value", async () => {
  let n = 0
  const load = vi.fn(async () => `v${++n}`)
  const { result } = renderHook(() =>
    usePolledResource({ key: "k", load, intervalMs: INTERVAL, timeoutMs: 60_000, now: () => 0 }),
  )

  await act(async () => {})
  expect(result.current.data).toBe("v1")

  await act(async () => {
    await vi.advanceTimersByTimeAsync(INTERVAL)
  })
  expect(result.current.data).toBe("v2")
  expect(load).toHaveBeenCalledTimes(2)
})

test("suspends periodic polling while hidden and refreshes when visible again", async () => {
  let visible = false
  let n = 0
  const load = vi.fn(async () => `v${++n}`)
  const { result } = renderHook(() =>
    usePolledResource({
      key: "k",
      load,
      intervalMs: INTERVAL,
      timeoutMs: 60_000,
      isVisible: () => visible,
      now: () => 0,
    }),
  )

  // The first load happens even while hidden; only the periodic poll is paused.
  await act(async () => {})
  expect(result.current.data).toBe("v1")

  await act(async () => {
    await vi.advanceTimersByTimeAsync(INTERVAL * 4)
  })
  expect(load).toHaveBeenCalledTimes(1)

  visible = true
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"))
  })
  expect(load).toHaveBeenCalledTimes(2)

  await act(async () => {
    await vi.advanceTimersByTimeAsync(INTERVAL)
  })
  expect(load).toHaveBeenCalledTimes(3)
})

test("keeps one request in flight so a slow response is never overlapped", async () => {
  const first = deferred<string>()
  let calls = 0
  const load = vi.fn((_signal: AbortSignal) => {
    calls += 1
    return calls === 1 ? first.promise : Promise.resolve("second")
  })
  const { result } = renderHook(() =>
    usePolledResource({ key: "k", load, intervalMs: INTERVAL, timeoutMs: 60_000, now: () => 0 }),
  )

  await act(async () => {})
  expect(load).toHaveBeenCalledTimes(1)

  // A tick while the first request is still open must not start a second.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(INTERVAL)
  })
  expect(load).toHaveBeenCalledTimes(1)

  first.resolve("first")
  await act(async () => {})
  expect(result.current.data).toBe("first")

  await act(async () => {
    await vi.advanceTimersByTimeAsync(INTERVAL)
  })
  expect(load).toHaveBeenCalledTimes(2)
  expect(result.current.data).toBe("second")
})

test("keeps the previous value on a refresh error and recovers on the next poll", async () => {
  const load = vi
    .fn<() => Promise<string>>()
    .mockResolvedValueOnce("one")
    .mockRejectedValueOnce(new Error("boom"))
    .mockResolvedValueOnce("three")
  const { result } = renderHook(() =>
    usePolledResource({ key: "k", load, intervalMs: INTERVAL, timeoutMs: 60_000, now: () => 0 }),
  )

  await act(async () => {})
  expect(result.current.data).toBe("one")

  await act(async () => {
    await vi.advanceTimersByTimeAsync(INTERVAL)
  })
  expect(result.current.data).toBe("one")
  expect(result.current.error).toContain("boom")
  expect(result.current.loading).toBe(false)

  await act(async () => {
    await vi.advanceTimersByTimeAsync(INTERVAL)
  })
  expect(result.current.data).toBe("three")
  expect(result.current.error).toBeNull()
})

test("aborts the in-flight request and drops a late response when the identity changes", async () => {
  const first = deferred<string>()
  const signals: AbortSignal[] = []
  let currentKey = "a"
  const load = vi.fn((signal: AbortSignal) => {
    signals.push(signal)
    return currentKey === "a" ? first.promise : Promise.resolve("second")
  })
  const { result, rerender } = renderHook(
    ({ key }: { key: string }) =>
      usePolledResource({ key, load, intervalMs: INTERVAL, timeoutMs: 60_000, now: () => 0 }),
    { initialProps: { key: "a" } },
  )

  await act(async () => {})
  currentKey = "b"
  rerender({ key: "b" })
  await act(async () => {})

  expect(signals[0].aborted).toBe(true)
  expect(result.current.data).toBe("second")

  first.resolve("late")
  await act(async () => {})
  expect(result.current.data).toBe("second")
})

test("aborts the in-flight request on unmount", async () => {
  const pending = deferred<string>()
  const signals: AbortSignal[] = []
  const load = vi.fn((signal: AbortSignal) => {
    signals.push(signal)
    return pending.promise
  })
  const { unmount } = renderHook(() =>
    usePolledResource({ key: "k", load, intervalMs: INTERVAL, timeoutMs: 60_000, now: () => 0 }),
  )

  await act(async () => {})
  unmount()
  expect(signals[0].aborted).toBe(true)
})

test("times out a request that never settles, reports it, and unblocks later polls", async () => {
  let calls = 0
  const load = vi.fn((signal: AbortSignal) => {
    calls += 1
    if (calls === 1) {
      return new Promise<string>((_resolve, reject) => {
        signal.addEventListener("abort", () =>
          reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
        )
      })
    }
    return Promise.resolve("recovered")
  })
  const { result } = renderHook(() =>
    usePolledResource({
      key: "k",
      load,
      intervalMs: 60_000,
      timeoutMs: 10_000,
      now: () => 0,
    }),
  )

  await act(async () => {})
  expect(result.current.loading).toBe(true)

  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000)
  })
  expect(result.current.loading).toBe(false)
  expect(result.current.error).toBeTruthy()

  await act(async () => {
    await vi.advanceTimersByTimeAsync(50_000)
  })
  expect(result.current.data).toBe("recovered")
  expect(result.current.error).toBeNull()
})

test("a manual refresh re-reads immediately", async () => {
  let n = 0
  const load = vi.fn(async () => `v${++n}`)
  const { result } = renderHook(() =>
    usePolledResource({ key: "k", load, intervalMs: INTERVAL, timeoutMs: 60_000, now: () => 0 }),
  )

  await act(async () => {})
  expect(result.current.data).toBe("v1")

  await act(async () => {
    result.current.refresh()
  })
  expect(result.current.data).toBe("v2")
  expect(load).toHaveBeenCalledTimes(2)
})

test("a manual refresh during a slow request runs as soon as it settles", async () => {
  const first = deferred<string>()
  let calls = 0
  const load = vi.fn((_signal: AbortSignal) => {
    calls += 1
    return calls === 1 ? first.promise : Promise.resolve("second")
  })
  const { result } = renderHook(() =>
    usePolledResource({ key: "k", load, intervalMs: INTERVAL, timeoutMs: 60_000, now: () => 0 }),
  )

  await act(async () => {})
  expect(load).toHaveBeenCalledTimes(1)

  // The manual refresh must not be dropped while the first request is open.
  await act(async () => {
    result.current.refresh()
  })
  expect(load).toHaveBeenCalledTimes(1)

  first.resolve("first")
  await act(async () => {})
  expect(load).toHaveBeenCalledTimes(2)
  expect(result.current.data).toBe("second")
})

test("a changed refresh token re-reads without blanking the visible value", async () => {
  let n = 0
  const load = vi.fn(async () => `v${++n}`)
  const { result, rerender } = renderHook(
    ({ token }: { token: number }) =>
      usePolledResource({
        key: "k",
        load,
        intervalMs: INTERVAL,
        timeoutMs: 60_000,
        refreshToken: token,
        now: () => 0,
      }),
    { initialProps: { token: 0 } },
  )

  await act(async () => {})
  expect(result.current.data).toBe("v1")

  rerender({ token: 1 })
  expect(result.current.data).toBe("v1")
  await act(async () => {})
  expect(result.current.data).toBe("v2")
})
