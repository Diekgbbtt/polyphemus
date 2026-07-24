# Host (bare-IP) seeding - specification

Status: proposed (spec + assertions), not yet implemented.
Branch: `host-seeding` (worktree, off `feat/increment-1-chunk-httpx-gate`).
Owner decisions ratified 2026-07-24 (see Section 1).

This spec extends the recon pipeline so a Project can be seeded with a **bare IPv4 address** instead of a domain, and unfolds the same web-application recon it already runs for domains.
It is deliberately narrow: the seam of seed-type-agnosticism is a small, well-fenced layer, and everything downstream (naabu, httpx, and the whole `BaseURL` crawl chain) is reused unchanged.

---

## 1. Ratified decisions

| # | Decision | Ruling |
|---|----------|--------|
| D-HS1 | Target key | Generalise the project setting key to `target_seed` (agnostic), with `target_domain` accepted as a deprecated read-time alias for back-compat. |
| D-HS2 | Scope | Part A (IP -> httpx on 80/443 -> existing chain) **and** Part B (Service -> non-standard-port BaseURL bridge), the latter fenced to `mode == "host"` and non-standard ports only. |
| D-HS3 | IPv6 | Out of scope for this increment. An IPv6 seed is explicitly rejected at the launch guard (designed-not-built, Standard Section 12), never silently mis-parsed. |
| D-HS4 | Branch base | `feat/increment-1-chunk-httpx-gate`. |

---

## 2. Goal and non-goals

**Goal.**
A Project whose `target_seed` is a bare IPv4 (e.g. `93.184.216.34`) launches a run that:

- treats the IP as the engagement root (an `IP` node, never a `Domain`);
- suppresses subdomain discovery (meaningless for a bare host);
- port-scans the host (naabu) and HTTP-probes it (httpx) on the default web ports, minting `BaseURL` nodes;
- reaches web services on **non-standard ports** that naabu discovers (Part B);
- feeds every minted `BaseURL` into the existing crawl/param/JS/agentic-crawl chain, identically to a domain run.

**Invariants that must hold.**

- **No new asset type.** Only the existing L0 labels (`IP`, `Service`, `Port`, `BaseURL`, ...) are used. The only new *vocabulary* is a scope **mode** value (`"host"`) and one new **job** (an extension point, Standard Section 7).
- **Seed-agnosticism lives in one layer.** `parse_scope`, root-node materialization, the discovery gate, and one resolver. No web-discovery tool learns about the seed type.
- **Alias-free.** No BaseURL minted by this feature aliases another BaseURL for the same resource (see Section 6).

**Non-goals.**

- Non-web targets (the standing assumption is all targets are web-kind).
- IPv6 (D-HS3).
- CIDR ranges / multiple seed hosts in one Project.
- Reverse-DNS / certificate-SAN hostname recovery for an IP (a possible future enhancement, noted in Section 9).

---

## 3. Current-state anchor (what already works, unchanged)

The pipeline is already host-string-agnostic below one narrow layer.
The following are reused verbatim and must not regress:

- `_inject_seed_host` (`src/polymerhus/recon/control/pipeline.py:74`) injects `{name: seed_host}` into every `Subdomain`-consuming job (naabu/httpx/subdomain_takeover); the string may be a host or an IP.
- `fill_template` (`src/polymerhus/recon/domain/pod.py:88`) resolves `{target}` from `name`/`url`/`address`, a bare string.
- `httpx -u {target}` and `naabu -host {target}` accept an IP verbatim; httpx mints `BaseURL` directly from the injected seed host (`httpx_parser`), and the crawl chain (`katana`/`ffuf`/`jsluice`/`steel_crawl`/`arjun`/`kiterunner`) chains off `BaseURL`.
- Scope filter admits the seed itself: `host_in_scope(host, scope)` is true on `host == scope` (`src/polymerhus/recon/domain/noise_filter.py:223`), and `_host_of_url` strips the port, so `http://<ip>:8080` -> host `<ip>` -> in scope.

The only domain-specific elements, all re-homed by this spec:

1. `parse_scope` computes a registrable apex (garbage for an IP).
2. `DISCOVERY_JOBS` (subfinder/amass/dnsx/puredns) are meaningless against a bare IP.
3. Root-node typing seeds a `Domain` and `_promote_seed_domain` rewrites the seed-named `Subdomain` to `Domain`.

---

## 4. Design - Part A (required core: IP on 80/443)

### S0. `target_seed` key + back-compat resolver

The setting is a free key in the open `recon` settings dict (`SettingsUpdate.recon: dict`, `src/polymerhus/project_management/api.py:33`); there is no per-key schema to migrate.

Add one pure resolver, the single source of truth for "the seed string", reused at every read site (Standard Section 8):

```
def resolve_seed(settings: dict) -> str | None:
    # target_seed is canonical; target_domain is the deprecated alias kept so
    # already-persisted projects launch unchanged (regression safety).
    return settings.get("target_seed") or settings.get("target_domain")
```

Read-site changes (all currently `settings.get("target_domain")`):

- `pipeline.py:57, 244, 269, 330, 348` -> `resolve_seed(settings)`.
- `repository.py:92` launch guard -> `resolve_seed(load_settings(...) or {})`.

The launch-guard error text and `save`/`load` jsonb-merge path (`pg.save_settings`, recursive `jsonb_deep_merge`, memory `settings-partial-put-merge`) are unchanged; a partial PUT still never wipes siblings.

### S1. `parse_scope` host mode (IPv4)

Add a pure classifier and a third mode.
`parse_scope` stays non-raising.

```
def seed_kind(raw: str) -> Literal["ipv4", "ipv6", "domain"]:
    # ipaddress.ip_address distinguishes v4/v6; anything else is a domain.

parse_scope(raw):
  kind = seed_kind(raw)
  if kind == "ipv4": return {apex: raw, seed_host: raw, mode: "host"}
  if kind == "ipv6": return {apex: raw, seed_host: raw, mode: "host"}   # safety net; guard rejects before launch (D-HS3)
  # ... existing wildcard / exact logic unchanged ...
```

IPv6 returns `host` mode (never falls through to domain parsing, so it can never be mis-modeled as a Domain), but the launch guard (S7) rejects it before any run starts, keeping the IPv6 path inert (Standard Section 12).

### S2. Discovery gate widened to host mode

`_gate_plan_by_scope` (`pipeline.py:62`) currently drops `DISCOVERY_JOBS` when `mode == "exact"`.
Widen the predicate to `mode in {"exact", "host"}`.
In host mode this also suppresses `whois`/`paramspider` usefulness; add them to a host-mode-only suppression set (`HOST_MODE_SUPPRESSED = {"whois", "paramspider"}`) dropped alongside `DISCOVERY_JOBS`, because a WHOIS/passive-archive harvest keyed on an IP is low-to-zero signal and risks off-scope fan-out.

### S3. Root-node materialization as `IP`, and `_promote_seed_root`

Two coordinated changes at the existing chokepoints:

- The deterministic root seed (`pipeline.py:269-275`) becomes mode-aware: in host mode emit `AssetDelta(type="IP", identity={"address": seed_host})` instead of `type="Domain"`.
- Generalise `curator._promote_seed_domain` (`src/polymerhus/recon/domain/curator.py:207`) to `_promote_seed_root(assets, seed, mode)`:
  - domain modes: rewrite `Subdomain{name == seed}` -> `Domain` (today's behaviour, unchanged).
  - host mode: rewrite `Subdomain{name == seed}` -> `IP`, remapping identity `name` -> `address`, for both top-level deltas and edge targets.

This is why S6 (`_bare_host` port strip) is required: the back-link host must be the bare `<ip>` for this rename to match the seed.

The curate call site (`pipeline.py:337`) passes `mode` (or a `seed_root_type`) alongside the existing `seed_domain`, threaded through `curate(...)`.

### S4. Seed injection and passive harvesters in host mode

- `_inject_seed_host` is reused unchanged: in host mode the IP is injected into naabu/httpx/subdomain_takeover (all `consumes="Subdomain"`), so both run against the IP.
- `_seed_domain_host` (later-phase Domain consumer, paramspider) is moot because paramspider is suppressed by S2 in host mode.
- `apex_registrable` for batched jsluice (`pipeline.py:348`): in host mode pass the IP itself (not `registrable_domain(ip)`, which is garbage) as the first-party key.

### Part A net flow (host mode)

`IP root (S3)` -> injected into `naabu` + `httpx` (S4) -> `httpx -u <ip>` mints `BaseURL{http://<ip>}` / `BaseURL{https://<ip>}` (default ports, portless) -> existing crawl chain unfolds. Discovery/whois/paramspider suppressed (S2). Zero change to any web-discovery tool's consume contract.

---

## 5. Design - Part B (Service -> non-standard-port BaseURL bridge, host-mode only)

Part B reaches web apps naabu finds on **non-default** ports (8080, 8443, 8000, 3000, ...), which Part A's default-port httpx probe never hits.
It is fenced to `mode == "host"` to avoid the vhost/host-vs-IP alias (Section 6, Trap 2).

### S5. New job `httpx_services`

```
"httpx_services": JobSpec(
    tool="httpx_services",           # registered in PARSERS -> parse_httpx (reuse, not duplication)
    skill="http_probe",
    command_template="httpx -u {target} -sc -title -server -td -fr -silent -json -irh {auth_header}",
    produces=["BaseURL","Endpoint","Technology","Certificate","Header"],
    consumes="Service",
    use_auth=True,
)
```

- Registered in `PARSERS` under this name mapped to `parse_httpx`, mirroring `httpx_reprofile` (Standard Section 8, "Reuse, not duplication").
- Placed in its own phase **between `httpx` and the crawl phase**, so its BaseURLs enter `katana`/`ffuf`/`jsluice`/`steel_crawl` exactly like httpx's.
- **Host-mode-only:** add to `HOST_MODE_ONLY_JOBS = {"httpx_services"}`, which `_gate_plan_by_scope` drops in every non-host mode (empty phase then removed). In domain/exact/wildcard runs it never appears.

### S5a. Service -> probe-URL preprocess (the one new mechanic)

naabu names services by **port number** (`_SERVICE_NAMES`, `naabu_parser.py`), so an HTTP service on 8000 is labeled `"unknown"`, not `"http"`.
A name-based gate would miss it.
Therefore the design uses **httpx as the protocol detector**: feed httpx every discovered non-default open port and let its probe decide (a non-web port yields no HTTP response, hence no BaseURL).

Implemented on the existing `preprocess_fn` seam of the job agent (`build_job_agent(*, preprocess_fn)`, Standard Section 6 DI), mirroring the synthesis already in `control/targeted.py:87`:

For each consumed `Service{name, port_number, ip_address}`:

- **Skip** `port_number in {80, 443}` - Part A already covers those, portlessly; re-probing them would mint the default-port alias (Section 6, Trap 1).
- Otherwise synthesize `{"url": f"{ip_address}:{port_number}", "target": same}` (scheme-less) so httpx probes the port and emits a BaseURL with its own detected scheme. `parse_httpx` then normalizes the BaseURL to `scheme://<ip>:<port>` (`_split_url`).

The synthesis and the 80/443 skip live in exactly one place.

### Part B net flow

`naabu` (Part A phase) mints `Service` nodes -> `httpx_services` preprocess synthesizes `<ip>:<port>` for non-default ports -> httpx probes -> `BaseURL{scheme://<ip>:<port>}` for responsive web ports -> existing crawl chain.

---

## 6. Alias safety (the core correctness argument)

**Trap 1 - default-port alias.**
`urlparse("http://<ip>:80").netloc` -> `<ip>:80`, so `_split_url` would key a BaseURL on `http://<ip>:80`, distinct from Part A's canonical portless `http://<ip>`.
Prevented by S5a skipping ports 80/443 entirely; Part A owns the standard ports and produces the portless canonical identity.

**Trap 2 - host-vs-IP / vhost alias.**
In a domain run httpx already produces host-addressed `https://app.example.com:8080` (correct `Host:` header, correct vhost routing); an IP-addressed `https://<ip>:8080` would be a second BaseURL for the same app and would break virtual hosting.
naabu's `Service` carries only the IP, so the hostname cannot be reconstructed.
Prevented by S5 fencing `httpx_services` to `mode == "host"`, where no hostname exists and there is nothing to alias against.

**Back-link integrity (S6).**
See Section 7.

---

## 7. S6 - `_bare_host` must strip the port

`httpx_parser` back-links every BaseURL to `Subdomain{name: _bare_host(input)}` (`httpx_parser.py:98-107`).
`_bare_host` (`httpx_parser.py:21-24`) strips scheme and path but **keeps the port**: `_bare_host("<ip>:8080")` -> `<ip>:8080`, and `_bare_host("http://<ip>:8080")` -> `<ip>:8080`.
That mints a malformed `Subdomain{name: "<ip>:8080"}` no other tool's identity matches, and it defeats the S3 `_promote_seed_root` rename (keyed on `name == seed`, i.e. the bare `<ip>`).

Fix: make `_bare_host` return a true bare host - strip the `:port` from the netloc (IPv4-aware; IPv6 is out of scope, D-HS3).
This is safe for the existing domain paths: httpx's normal `input` is a bare host, and `httpx_reprofile`'s `input` is a default-port domain URL whose netloc carries no explicit `:port`, so both are unchanged.

Ordering: S6 (bare host) must be in place for S3 (`<ip>` -> `IP` promotion) to match.

---

## 8. Touch-point summary

| Area | File / symbol | Change |
|------|---------------|--------|
| Seed resolver | `recon/control/scope.py` (new `resolve_seed`, `seed_kind`) | add pure helpers |
| Scope | `recon/control/scope.py` `parse_scope` | add `host` mode (IPv4) |
| Discovery/harvester gate | `recon/control/pipeline.py` `_gate_plan_by_scope`, `DISCOVERY_JOBS`, new `HOST_MODE_SUPPRESSED`, `HOST_MODE_ONLY_JOBS` | widen to `host`; drop whois/paramspider; add/drop httpx_services |
| Read sites | `recon/control/pipeline.py:57,244,269,330,348`; `project_management/repository.py:92-96` | `resolve_seed(...)` |
| Root seed | `recon/control/pipeline.py:269-275` | mode-aware `IP` vs `Domain` |
| Root promotion | `recon/domain/curator.py:207` `_promote_seed_domain` -> `_promote_seed_root`; `curate(...)` signature | generalise to IP; thread `mode` |
| Job B | `recon/control/jobs.py` `JOBS`, `PHASES`; `recon/domain/parsers/__init__.py` `PARSERS` | add `httpx_services` -> `parse_httpx` |
| Preprocess B | job-agent `preprocess_fn` wiring (`recon/control/job_agent.py` / `pipeline.py`) | Service -> `<ip>:<port>`, skip 80/443 |
| Back-link | `recon/domain/parsers/httpx_parser.py` `_bare_host` | strip port |
| Launch guard | `project_management/repository.py` `validate_launch` | reject IPv6 seed with clear error |
| Ubiquitous language | `src/polymerhus/recon/CONTEXT.md`; `docs/design/domain-model.md`; `docs/design/recon-pipeline-forward-decisions.md` | record `host` mode, `target_seed`, `httpx_services`, D-HS decisions |

---

## 9. Deferred / designed-not-built

- IPv6 seeding (D-HS3) - rejected at the guard; the `parse_scope` IPv6 -> host-mode safety net is inert until the guard is lifted and URL synthesis is bracketed.
- Reverse-DNS / certificate-SAN hostname recovery for an IP (would let a host run rejoin host-addressed BaseURLs and lift the Trap-2 fence) - future enhancement.
- CIDR / multi-host seeds.
- Selector-level numeric/port predicates (S5a does the 80/443 skip in the preprocess because `AssetSelector` is string-only, no negation).

---

## 10. Regression contract for domain seeding (must not change)

Enumerated as assertions in `host-seeding-assertions.md`, Section R.
In one line: for any non-IP `target_seed` (or legacy `target_domain`), `parse_scope` returns `exact`/`wildcard` exactly as today, `httpx_services` never appears in the plan, `_bare_host` returns the same bare host, `_promote_seed_root` behaves as `_promote_seed_domain` did, and no BaseURL identity changes.
