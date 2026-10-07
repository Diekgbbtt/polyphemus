import { render } from "@testing-library/react"
import { afterEach, expect, test, vi } from "vitest"
import { SavedOn } from "./SavedOn"

// The browser timezone is part of the rendering, so each case pins it and then
// restores the ambient value for the rest of the suite.
afterEach(() => {
  vi.unstubAllEnvs()
})

test("renders the saved instant in the browser timezone with a machine-readable time element", () => {
  // 2024-01-02T10:30:00+02:00 is 08:30 on the UTC clock: the expected local
  // rendering is fixed and independently checkable, not re-derived from the
  // component's own formatter.
  vi.stubEnv("TZ", "UTC")
  render(<SavedOn copiedAt="2024-01-02T10:30:00+02:00" />)

  const time = document.querySelector("time")
  expect(time).not.toBeNull()
  // The stored value stays available to machines, unchanged.
  expect(time?.getAttribute("dateTime")).toBe("2024-01-02T10:30:00+02:00")
  // The visible text is the browser-local instant, with the zone named so the
  // reader knows which clock it is; the raw offset-bearing text is not shown.
  expect(time?.textContent).not.toContain("10:30")
  expect(time?.textContent).toMatch(/8:30/)
  expect(time?.textContent).toMatch(/UTC/)
  expect(document.body.textContent).toContain("Saved at")
})

test("two spellings of the same instant render the same text", () => {
  // 10:30+02:00 and 08:30Z are the same instant, so they must read identically
  // on whatever clock the browser uses. A raw passthrough could not do that.
  const { container, rerender } = render(<SavedOn copiedAt="2024-01-02T10:30:00+02:00" />)
  const fromOffset = container.querySelector("time")?.textContent
  rerender(<SavedOn copiedAt="2024-01-02T08:30:00Z" />)
  const fromZulu = container.querySelector("time")?.textContent
  expect(fromOffset).toBeTruthy()
  expect(fromZulu).toBe(fromOffset)
})

test("missing or invalid timestamps render the fallback and no synthesized time", () => {
  const { container, rerender } = render(<SavedOn copiedAt={null} />)
  expect(container.textContent).toContain("Date unavailable")
  expect(container.querySelector("time")).toBeNull()
  expect(container.textContent).not.toMatch(/\d{4}/)

  rerender(<SavedOn copiedAt="not-a-timestamp" />)
  expect(container.textContent).toContain("Date unavailable")
  expect(container.querySelector("time")).toBeNull()
  expect(container.textContent).not.toContain("not-a-timestamp")
})
