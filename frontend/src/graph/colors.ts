export const NODE_COLORS: Record<string, string> = {
  // Layer 0 - descriptive attack surface (a cool blue/teal/violet/green palette).
  Domain: "#1e3a8a", Subdomain: "#2563eb",
  IP: "#0d9488", Port: "#0e7490", Service: "#06b6d4", DNSRecord: "#164e63",
  BaseURL: "#6366f1", Endpoint: "#8b5cf6", Parameter: "#c026d3",
  Technology: "#22c55e", Certificate: "#d97706", Header: "#78716c",
  Secret: "#e11d48", ExternalDomain: "#8b8178", Traceroute: "#164e63",
  Observation: "#f59e0b",
  // Layer 1 - service/system model. A deliberately WARM palette, disjoint from the
  // Layer-0 hues above, so the two layers are instantly separable and each L1
  // subtype is distinct (fixes "L1 nodes are all dark-grey / indistinguishable").
  L1Service: "#ec4899",       // pink - business functions
  L1System: "#f97316",        // orange - cross-cutting technical systems
  L1DataItem: "#facc15",      // yellow - the Tier-1 data (the crown jewel)
  L1TestableUnit: "#ec4899",  // supertype fallback (should resolve to a subtype)
  // Controlled-vocabulary catalogues (SystemKind / DataRelationshipKind) are
  // registry/reference data, not model nodes - muted so they recede behind the
  // actual services/systems/data items.
  SystemKind: "#a1a1aa",
  DataRelationshipKind: "#a1a1aa",
  Default: "#6b7280",
}

export function nodeColor(type: string): string {
  return NODE_COLORS[type] ?? NODE_COLORS.Default
}
