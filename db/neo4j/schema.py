"""Layer-0 schema — Redamon-derived, adapted for polymerhus.
  * user_id dropped from every identity key (keep project_id).
  * Security/CVE/OSINT/attack-chain node types removed.
  * Observation(id) uniqueness added.
Identity keys follow recon-mvp-design §10.3."""

CONSTRAINTS = [
    "CREATE CONSTRAINT domain_unique IF NOT EXISTS FOR (d:Domain) REQUIRE (d.name, d.project_id) IS UNIQUE",
    "CREATE CONSTRAINT subdomain_unique IF NOT EXISTS FOR (s:Subdomain) REQUIRE (s.name, s.project_id) IS UNIQUE",
    "CREATE CONSTRAINT ip_unique IF NOT EXISTS FOR (i:IP) REQUIRE (i.address, i.project_id) IS UNIQUE",
    "CREATE CONSTRAINT port_unique IF NOT EXISTS FOR (p:Port) REQUIRE (p.number, p.protocol, p.ip_address, p.project_id) IS UNIQUE",
    "CREATE CONSTRAINT service_unique IF NOT EXISTS FOR (svc:Service) REQUIRE (svc.name, svc.port_number, svc.ip_address, svc.project_id) IS UNIQUE",
    "CREATE CONSTRAINT dnsrecord_unique IF NOT EXISTS FOR (dns:DNSRecord) REQUIRE (dns.type, dns.value, dns.subdomain, dns.project_id) IS UNIQUE",
    "CREATE CONSTRAINT baseurl_unique IF NOT EXISTS FOR (u:BaseURL) REQUIRE (u.url, u.project_id) IS UNIQUE",
    "CREATE CONSTRAINT endpoint_unique IF NOT EXISTS FOR (e:Endpoint) REQUIRE (e.path, e.method, e.baseurl, e.project_id) IS UNIQUE",
    "CREATE CONSTRAINT parameter_unique IF NOT EXISTS FOR (p:Parameter) REQUIRE (p.name, p.position, p.endpoint_path, p.baseurl, p.project_id) IS UNIQUE",
    "CREATE CONSTRAINT header_unique IF NOT EXISTS FOR (h:Header) REQUIRE (h.name, h.value, h.baseurl, h.project_id) IS UNIQUE",
    "CREATE CONSTRAINT certificate_unique IF NOT EXISTS FOR (c:Certificate) REQUIRE (c.subject_cn, c.project_id) IS UNIQUE",
    "CREATE CONSTRAINT technology_unique IF NOT EXISTS FOR (t:Technology) REQUIRE (t.name, t.version, t.project_id) IS UNIQUE",
    "CREATE CONSTRAINT secret_unique IF NOT EXISTS FOR (s:Secret) REQUIRE (s.value_hash, s.project_id) IS UNIQUE",
    "CREATE CONSTRAINT traceroute_unique IF NOT EXISTS FOR (tr:Traceroute) REQUIRE (tr.ip_address, tr.project_id) IS UNIQUE",
    "CREATE CONSTRAINT externaldomain_unique IF NOT EXISTS FOR (ed:ExternalDomain) REQUIRE (ed.domain, ed.project_id) IS UNIQUE",
    "CREATE CONSTRAINT observation_unique IF NOT EXISTS FOR (o:Observation) REQUIRE (o.id) IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX idx_domain_tenant IF NOT EXISTS FOR (d:Domain) ON (d.project_id)",
    "CREATE INDEX idx_subdomain_tenant IF NOT EXISTS FOR (s:Subdomain) ON (s.project_id)",
    "CREATE INDEX idx_baseurl_tenant IF NOT EXISTS FOR (u:BaseURL) ON (u.project_id)",
    "CREATE INDEX idx_endpoint_tenant IF NOT EXISTS FOR (e:Endpoint) ON (e.project_id)",
    "CREATE INDEX subdomain_name IF NOT EXISTS FOR (s:Subdomain) ON (s.name)",
    "CREATE INDEX ip_address IF NOT EXISTS FOR (i:IP) ON (i.address)",
    "CREATE INDEX tech_name IF NOT EXISTS FOR (t:Technology) ON (t.name)",
]
