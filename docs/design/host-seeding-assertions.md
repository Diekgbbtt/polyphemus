# Host (bare-IP) seeding - assertions

Companion to `host-seeding-spec.md`.
Each assertion is a verifiable check with a tier: **U** unit (mock Neo4j, no live DB - Standard Section 10), **I** integration (in-network), **E** e2e (real target).
An assertion is CONFIRMED only when a maker-independent checker reproduces it (Standard Section 11).

Legend for identity: `IP{address}`, `Subdomain{name}`, `Domain{name}`, `Service{name, port_number, ip_address}`, `BaseURL{url = scheme://netloc}`.

---

## A. Seed resolution and classification (`resolve_seed`, `seed_kind`, `parse_scope`)

- **A1 (U).** `resolve_seed({"target_seed": "x"})  == "x"`.
- **A2 (U).** `resolve_seed({"target_domain": "x"}) == "x"` (deprecated alias still resolves - regression safety for persisted projects).
- **A3 (U).** `resolve_seed({"target_seed": "new", "target_domain": "old"}) == "new"` (canonical key wins over the alias).
- **A4 (U).** `resolve_seed({}) is None` and `resolve_seed({"target_seed": ""}) is None` (empty is not a target).
- **A5 (U).** `seed_kind("93.184.216.34") == "ipv4"`; `seed_kind("::1") == "ipv6"`; `seed_kind("2001:db8::1") == "ipv6"`; `seed_kind("example.com") == "domain"`; `seed_kind("app.example.com") == "domain"`.
- **A6 (U).** `seed_kind("999.1.1.1") == "domain"` and `seed_kind("1.2.3") == "domain"` (not a valid IPv4 -> treated as a hostname string, never raises).
- **A7 (U).** `parse_scope("93.184.216.34") == {"apex": "93.184.216.34", "seed_host": "93.184.216.34", "mode": "host"}`.
- **A8 (U).** `parse_scope` on an IPv4 does **not** call/produce a registrable-apex last-two-labels result (apex equals the full IP, not `216.34`).
- **A9 (U).** `parse_scope("::1")["mode"] == "host"` (IPv6 safety net: never `domain`/`exact`).
- **A10 (U).** `parse_scope` never raises for any string input including malformed IPs and empty string (existing contract preserved).

## B. Discovery / harvester gate in host mode (`_gate_plan_by_scope`)

- **B1 (U).** For `mode == "host"`, the gated plan contains **none** of `{subfinder, amass, dnsx, puredns}` (DISCOVERY_JOBS).
- **B2 (U).** For `mode == "host"`, the gated plan contains **neither** `whois` **nor** `paramspider` (HOST_MODE_SUPPRESSED).
- **B3 (U).** For `mode == "host"`, `subdomain_takeover` **survives** the gate (it is not a discovery job - the exact-mode carve-out holds for host mode too).
- **B4 (U).** For `mode == "host"`, `naabu` and `httpx` **survive** the gate.
- **B5 (U).** Any phase left empty by the host-mode gate is dropped (no empty phase reaches the executor).

## C. Root node materialization and promotion (`pipeline` seed, `_promote_seed_root`)

- **C1 (U).** In host mode the deterministic root seed emits exactly one `AssetDelta(type="IP", identity={"address": <ip>})`, never a `Domain`.
- **C2 (U).** `_promote_seed_root([Subdomain{name: <ip>}], seed=<ip>, mode="host")` rewrites it to `IP{address: <ip>}` (type changed, identity key `name` -> `address`).
- **C3 (U).** `_promote_seed_root` rewrites a matching `Subdomain` **edge target** (e.g. a BaseURL's `BELONGS_TO`) to `IP{address}` as well, not only top-level deltas.
- **C4 (U).** `_promote_seed_root(..., mode="exact")` and `mode="wildcard"` reproduce the legacy `_promote_seed_domain` behaviour exactly: `Subdomain{name == seed}` -> `Domain{name}` (identity key unchanged).
- **C5 (U).** `_promote_seed_root` leaves non-seed `Subdomain` nodes untouched in every mode.
- **C6 (I).** After a host-mode run of httpx against the seed IP, the graph has exactly one `IP{address: <ip>}` root and no `Subdomain{name: <ip>}` and no `Domain{name: <ip>}` (no duplicate/mis-typed root).

## D. Seed injection and first-party key (host mode)

- **D1 (U).** `_inject_seed_host(input_assets, {mode: host, seed_host: <ip>})` prepends `{name: <ip>}` when absent, and is a no-op when already present (idempotent, unchanged behaviour with an IP string).
- **D2 (U).** In host mode a batched job's `apex_registrable` extra equals the IP itself, not `registrable_domain(<ip>)` (which would be `216.34`).

## E. Part A end-to-end (IP on default ports)

- **E1 (U).** Given a stub httpx output for `input == <ip>` (default ports), `parse_httpx` yields `BaseURL{url: "http://<ip>"}` / `BaseURL{url: "https://<ip>"}` (portless, no `:80`/`:443`).
- **E2 (U).** The BaseURL's `BELONGS_TO` back-link target host is the bare `<ip>` (depends on S6), so `_promote_seed_root` remaps it to `IP{address: <ip>}`.
- **E3 (I).** A host-mode run over a live IP serving http/https on 80/443 produces at least one `BaseURL`, and downstream `katana`/`ffuf` receive it (BaseURL population non-empty at the crawl phase).
- **E4 (E).** Full host-mode run against a real IP web target unfolds the crawl/param chain and writes `Endpoint`/`Parameter` nodes anchored to the IP-hosted BaseURL, mirroring a domain run's shape.

## F. Part B - `httpx_services` bridge (host mode, non-standard ports)

- **F1 (U).** `httpx_services` is present in the phase plan **only** when `mode == "host"`; for `exact`/`wildcard` it is absent (HOST_MODE_ONLY_JOBS dropped).
- **F2 (U).** `httpx_services` sits in a phase **after** `naabu` (its `Service` producer) and **before** the crawl phase (`katana`/`ffuf`/`jsluice`/`steel_crawl`).
- **F3 (U).** `validate_job_subset`/phase-availability accepts `httpx_services` (its `consumes="Service"` is produced by naabu in an earlier phase); it does not raise.
- **F4 (U).** The Service preprocess **skips** `Service{port_number: 80}` and `Service{port_number: 443}` (no probe URL synthesized - Trap 1 defence).
- **F5 (U).** The Service preprocess synthesizes `{"url": "<ip>:8080", "target": "<ip>:8080"}` (scheme-less) for `Service{port_number: 8080}`, and likewise for a `Service{name: "unknown", port_number: 8000}` (naabu's numeric naming does not cause a miss - httpx is the protocol detector).
- **F6 (U).** `PARSERS["httpx_services"] is parse_httpx` (reuse, not a duplicated parser).
- **F7 (U).** Given a stub httpx output for `input == "<ip>:8080"`, `parse_httpx` yields `BaseURL{url: "http://<ip>:8080"}` (port retained; this is the unique canonical id, not an alias).
- **F8 (I).** A host-mode run where naabu finds an http service on a non-standard port yields a `BaseURL{scheme://<ip>:<port>}` for it, and that BaseURL reaches the crawl phase.
- **F9 (I).** A host-mode run where a non-web port (e.g. 22/ssh) is open yields **no** `BaseURL` for that port (httpx gets no HTTP response - naabu's open port is filtered by the probe, not by name).

## G. Back-link / `_bare_host` (S6)

- **G1 (U).** `_bare_host("<ip>:8080") == "<ip>"` (port stripped).
- **G2 (U).** `_bare_host("http://<ip>:8080") == "<ip>"` (scheme and port stripped).
- **G3 (U).** `_bare_host("app.example.com") == "app.example.com"` and `_bare_host("https://app.example.com") == "app.example.com"` (domain paths unchanged - no regression).
- **G4 (U).** `_bare_host("https://app.example.com:8443") == "app.example.com"` (explicit port stripped for domains too - the belt case; still a bare host).

## H. Launch guard (`validate_launch`)

- **H1 (U).** `validate_launch` raises `ValueError` when neither `target_seed` nor `target_domain` is present (targetless run still refused).
- **H2 (U).** `validate_launch` passes when only the legacy `target_domain` is set (persisted-project regression).
- **H3 (U).** `validate_launch` passes when `target_seed` is a bare IPv4.
- **H4 (U).** `validate_launch` raises `ValueError` with a clear "IPv6 seeding not supported" message when `target_seed` is IPv6 (D-HS3, inert IPv6 path).

## R. Regression contract for domain seeding (must not change)

- **R1 (U).** `parse_scope("*.example.com")` and `parse_scope("app.example.com")` return byte-identical descriptors to pre-change (wildcard/exact, same apex/seed_host).
- **R2 (U).** For every non-IP seed, `httpx_services` never appears in the built phase plan.
- **R3 (U).** For every non-IP seed, the root is materialized as `Domain` (exact mode) exactly as today; no `IP` root is minted.
- **R4 (U).** `_promote_seed_root` in `exact`/`wildcard` mode is behaviourally equal to the former `_promote_seed_domain` across a table of representative deltas (top-level and edge-target Subdomains).
- **R5 (U).** `_bare_host` output for all pre-existing inputs (bare hosts, default-port domain URLs) is unchanged (G3).
- **R6 (U).** No existing BaseURL identity changes: for a domain run, every `BaseURL.url` produced is the same string as before (portless default-port URLs unaffected by S6/S5a, which touch only port-bearing and IP inputs).
- **R7 (I).** The existing domain-seed e2e (`tests/recon/test_pipeline_e2e.py` and the full-stack e2e) pass unchanged - same node census, same phase plan, same job set.
- **R8 (U).** The `pg.save_settings` partial-PUT jsonb-deep-merge is untouched: a PUT adding `auth_context` still does not drop `target_seed`/`target_domain` (memory `settings-partial-put-merge`).

## V. Cross-cutting invariants

- **V1 (U).** No label outside the existing L0 allowlist (`curator.ALLOWED_LABELS`) is emitted anywhere in the host-seeding path (no new asset type).
- **V2 (U).** Importing every changed module performs no network I/O and needs no env var (Standard Section 6).
- **V3 (U).** All new pure helpers (`resolve_seed`, `seed_kind`, the Service preprocess, `_bare_host`) are exercised with mocked Neo4j only; none reaches a live driver (Standard Section 10).
- **V4 (I).** A host-mode run reaches a terminal `set_run_status(run_id, "complete")` even when the IP is down / all pods fail (fail-open rings preserved, Standard Section 5).
