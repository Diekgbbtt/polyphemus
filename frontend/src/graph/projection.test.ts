import { projectGraph, isL1Type, layerKey } from "./projection"
import type { GraphData } from "../api/types"

// A small mixed graph:
//   L0-L0:      Domain -HAS_SUBDOMAIN-> Endpoint (attack surface)
//   cross-layer: L1Service -AGGREGATES-> Endpoint
//                L1System  -EVIDENCED_BY-> Header
//                L1DataItem-SURFACES_AT-> Parameter
//   L1-internal: L1System  -OF_KIND-> SystemKind
//   unanchored L0: Secret (touched by no L1 edge)
const node = (id: string, type: string) => ({ id, name: id, type, properties: {} })
const link = (source: string, target: string, type: string) => ({ source, target, type })

const DATA: GraphData = {
  project_id: "p1",
  nodes: [
    node("dom", "Domain"),
    node("ep", "Endpoint"),
    node("hdr", "Header"),
    node("param", "Parameter"),
    node("secret", "Secret"),
    node("svc", "L1Service"),
    node("sys", "L1System"),
    node("data", "L1DataItem"),
    node("kind", "SystemKind"),
  ],
  links: [
    link("dom", "ep", "HAS_SUBDOMAIN"),
    link("svc", "ep", "AGGREGATES"),
    link("sys", "hdr", "EVIDENCED_BY"),
    link("data", "param", "SURFACES_AT"),
    link("sys", "kind", "OF_KIND"),
  ],
}

const BOTH = { l0: true, l1: true }
const L0_ONLY = { l0: true, l1: false }
const L1_ONLY = { l0: false, l1: true }
const NEITHER = { l0: false, l1: false }

test("isL1Type classifies L1 labels (incl. catalogues) and rejects L0", () => {
  for (const t of ["L1Service", "L1System", "L1DataItem", "SystemKind", "DataRelationshipKind"]) {
    expect(isL1Type(t)).toBe(true)
  }
  for (const t of ["Domain", "Endpoint", "Parameter", "Observation", "Header"]) {
    expect(isL1Type(t)).toBe(false)
  }
})

test("layerKey gives each combination a distinct stable identity", () => {
  const keys = [BOTH, L0_ONLY, L1_ONLY, NEITHER].map(layerKey)
  expect(new Set(keys).size).toBe(4)
  expect(layerKey({ l0: true, l1: true })).toBe(layerKey(BOTH))
})

test("both layers on returns the full graph unchanged", () => {
  const { nodes, links } = projectGraph(DATA, BOTH)
  expect(nodes).toHaveLength(DATA.nodes.length)
  expect(links).toHaveLength(DATA.links.length)
})

test("both layers off returns the empty graph", () => {
  const { nodes, links } = projectGraph(DATA, NEITHER)
  expect(nodes).toEqual([])
  expect(links).toEqual([])
})

test("L0 only keeps L0 nodes and L0-L0 edges", () => {
  const { nodes, links } = projectGraph(DATA, L0_ONLY)
  expect(nodes.map((n) => n.id).sort()).toEqual(["dom", "ep", "hdr", "param", "secret"])
  expect(nodes.every((n) => !isL1Type(n.type))).toBe(true)
  // Only the Domain->Endpoint edge survives; every cross-layer edge is dropped.
  expect(links).toEqual([{ source: "dom", target: "ep", type: "HAS_SUBDOMAIN" }])
})

test("L1 only keeps every L1 node plus only its anchored L0 nodes", () => {
  const { nodes } = projectGraph(DATA, L1_ONLY)
  const ids = nodes.map((n) => n.id).sort()
  // L1 nodes: svc, sys, data, kind. Anchored L0: ep, hdr, param.
  // Unanchored L0 (dom, secret) are hidden.
  expect(ids).toEqual(["data", "ep", "hdr", "kind", "param", "svc", "sys"])
  expect(ids).not.toContain("dom")
  expect(ids).not.toContain("secret")
})

test("L1 only keeps cross-layer + L1-internal edges, drops L0-L0 edges", () => {
  const { links } = projectGraph(DATA, L1_ONLY)
  const types = links.map((l) => l.type).sort()
  expect(types).toEqual(["AGGREGATES", "EVIDENCED_BY", "OF_KIND", "SURFACES_AT"])
  expect(types).not.toContain("HAS_SUBDOMAIN")
})

test("projectGraph never mutates its input", () => {
  const before = JSON.stringify(DATA)
  for (const layers of [L0_ONLY, L1_ONLY, NEITHER, BOTH]) projectGraph(DATA, layers)
  expect(JSON.stringify(DATA)).toBe(before)
})
