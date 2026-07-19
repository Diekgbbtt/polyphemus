import { NODE_COLORS, nodeColor } from "./colors"

const L0_TYPES = [
  "Domain", "Subdomain", "IP", "Port", "Service", "DNSRecord", "BaseURL",
  "Endpoint", "Parameter", "Technology", "Certificate", "Header", "Secret",
  "ExternalDomain", "Traceroute", "Observation",
]
const L1_SUBTYPES = ["L1Service", "L1System", "L1DataItem"]

test("each L1 subtype has a distinct, non-default colour", () => {
  const seen = new Set<string>()
  for (const t of L1_SUBTYPES) {
    const c = nodeColor(t)
    expect(c).not.toBe(NODE_COLORS.Default) // never the fallback grey
    expect(seen.has(c)).toBe(false) // distinct from the other L1 subtypes
    seen.add(c)
  }
})

test("L1 colours are disjoint from the Layer-0 palette", () => {
  const l0 = new Set(L0_TYPES.map(nodeColor))
  for (const t of L1_SUBTYPES) {
    expect(l0.has(nodeColor(t))).toBe(false)
  }
})

test("controlled-vocabulary catalogues are muted (and share one reference tone)", () => {
  expect(nodeColor("SystemKind")).toBe(nodeColor("DataRelationshipKind"))
  expect(nodeColor("SystemKind")).not.toBe(NODE_COLORS.Default)
})

test("an unknown type still falls back to the default grey", () => {
  expect(nodeColor("SomethingElse")).toBe(NODE_COLORS.Default)
})
