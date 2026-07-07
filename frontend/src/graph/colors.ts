export const NODE_COLORS: Record<string, string> = {
  Domain: "#1e3a8a", Subdomain: "#2563eb",
  IP: "#0d9488", Port: "#0e7490", Service: "#06b6d4", DNSRecord: "#164e63",
  BaseURL: "#6366f1", Endpoint: "#8b5cf6", Parameter: "#c026d3",
  Technology: "#22c55e", Certificate: "#d97706", Header: "#78716c",
  Secret: "#e11d48", ExternalDomain: "#8b8178", Traceroute: "#164e63",
  Observation: "#f59e0b",
  Default: "#6b7280",
}

export function nodeColor(type: string): string {
  return NODE_COLORS[type] ?? NODE_COLORS.Default
}
