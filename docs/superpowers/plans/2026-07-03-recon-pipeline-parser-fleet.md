# Recon Pipeline - Parser Fleet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port every remaining deterministic recon parser from Redamon into the `agent/recon/parsers/` fleet, each as a pure `parse(stdout: str) -> list[AssetDelta]` registered in `PARSERS`, so that after this sub-plan every non-agentic recon tool's output maps to typed Layer-0 assets. (Agentic crawl / steel and on-demand nuclei are separate later sub-plans.)

**Architecture:** Follows the reference parser from the Foundation sub-plan (`agent/recon/parsers/httpx_parser.py`) exactly: read the tool's structured (`-json`/`-jsonl`/line) stdout, iterate lines with a per-line JSON guard, emit `AssetDelta`s with identity/props/edges matching design §10.3, register under the tool name. Each parser is pure and deterministic - no I/O, no tool execution (that is the pod's `execute_command`), no Neo4j writes (that is the curator).

**Tech Stack:** Python 3.11, pydantic (`AssetDelta`/`Edge` from `agent/recon/types.py`), pytest. Redamon parse sources live in the `redamon-recon:latest` image under `/app/recon/`.

## Global Constraints

- Every parser: signature `parse(stdout: str) -> list[AssetDelta]`, pure + deterministic, per-line `try/except json.JSONDecodeError: continue` (a malformed line is skipped, never fatal), tolerate missing optional keys via `.get()` (never `KeyError`), emit deltas in a deterministic order (iterate lists, never sets).
- Register each new parser in `agent/recon/parsers/__init__.py::PARSERS` under its tool name; `get_parser(tool)` must resolve it. Do not redefine `AssetDelta`/`Edge` - import from `agent.recon.types`.
- Node identity keys and properties MUST match design §10.3 exactly (reproduced per task). Every node carries only its identity keys in the delta `identity`; everything else goes in `props`. `project_id`/`first_seen`/`last_seen` are injected by the curator - parsers never set them.
- Edges use the design §5 relationship names and point in the semantically correct direction (`dir="in"` = other-node → this-node; `dir="out"` = this-node → other-node). Reproduced per task.
- Findings-type tools (graphql_scan misconfig, subdomain_takeover) emit **`Observation`**-shaped results, NOT `Vulnerability` nodes (design §5). Since the triager owns Observations in the pod, a parser that inherently produces findings returns them as `AssetDelta`s of a dedicated shape only where the finding is a graph asset (e.g. an Endpoint discovered); pure security findings are surfaced via the pod's triager - see the per-task notes for graphql_scan / subdomain_takeover, which clarify the split.
- To read a Redamon parse source: `docker run --rm --entrypoint sh redamon-recon:latest -c 'sed -n "<start>,<end>p" <file>'`. The `entry.get("<key>")` calls in each source reveal the exact raw tool-JSON keys - port those keys, drop all Docker/execution/accumulator/AI-annotation code.
- Reference implementation to mirror for structure, registry wiring, and test style: `agent/recon/parsers/httpx_parser.py` + `tests/recon/test_httpx_parser.py` (already in the branch).
- Tests run from repo root; gitignored `.venv/` has deps. Each task: fixture built from the real tool `-json` line shape (derive from the source's `entry.get` keys), 3-5 assertions on emitted delta types/identity/edges, plus a malformed-line-skipped test.

---

### Task 1: Subdomain-discovery parsers (subfinder, amass)

**Files:** Create `agent/recon/parsers/subdomain_parser.py`; Modify `agent/recon/parsers/__init__.py`; Create `tests/recon/fixtures/subfinder.jsonl`, `tests/recon/fixtures/amass.jsonl`, `tests/recon/test_subdomain_parser.py`.

**Port sources:**
- subfinder: `main_recon_modules/domain_recon.py::run_subfinder` (~line 261-318). Raw line shape: `{"host": "sub.example.com", ...}` (subfinder `-json -silent`). Key: `host`.
- amass: `main_recon_modules/domain_recon.py::run_amass` (~line 319-424). Read the source for amass's `-json` line shape (`name`/`domain` keys + `addresses`).

**Target schema (§10.3):** `Subdomain` identity `(name)`; edge `BELONGS_TO` dir `out` to `Domain (name)` (subdomain → domain). If amass yields resolved addresses, also emit `IP (address)` + edge `RESOLVES_TO` dir `out` from Subdomain, with `{record_type}` on the edge props.

**Interfaces - Produces:** `subdomain_parser.parse_subfinder(stdout) -> list[AssetDelta]`, `parse_amass(stdout) -> list[AssetDelta]`; registered as `PARSERS["subfinder"]`, `PARSERS["amass"]`. The parent domain for the `BELONGS_TO` edge is derived from the subdomain name (registrable parent) - implement a small `_parent_domain(host) -> str` helper (last two labels, or the full apex if the source provides it).

- [ ] **Step 1:** Write `tests/recon/test_subdomain_parser.py`: fixtures with 2 subfinder lines + 2 amass lines; assert subfinder emits `Subdomain` deltas with `identity["name"]` set and a `BELONGS_TO`→`Domain` edge; assert amass emits `Subdomain` (+ `IP`/`RESOLVES_TO` if addresses present); assert malformed line skipped; assert `get_parser("subfinder")` and `get_parser("amass")` resolve.
- [ ] **Step 2:** Run `pytest tests/recon/test_subdomain_parser.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement `subdomain_parser.py` (both parse fns + `_parent_domain`) porting the source key mapping; register both in `__init__.py`.
- [ ] **Step 4:** Run the test → PASS.
- [ ] **Step 5:** `git add` the files; `git commit -m "feat(recon): subdomain-discovery parsers (subfinder, amass)"`.

---

### Task 2: DNS-resolution parsers (dnsx, puredns)

**Files:** Create `agent/recon/parsers/dns_parser.py`; Modify `__init__.py`; Create fixtures + `tests/recon/test_dns_parser.py`.

**Port sources:**
- dnsx: `main_recon_modules/domain_recon.py::resolve_all_dns` / `dns_lookup` (~467-635). dnsx `-json` line shape includes `host`, `a`/`aaaa` (address lists), `cname`, record types.
- puredns: `main_recon_modules/domain_recon.py::run_puredns_resolve` (~636+). puredns resolve output: resolved hostnames (+ optionally `A` records). Read the source for exact shape.

**Target schema (§10.3):** `Subdomain (name)` (mark resolved via props `has_dns_records=true`); `IP (address)` with edge `RESOLVES_TO {record_type}` dir `out` from Subdomain; `DNSRecord (type, value, subdomain)` with edge `HAS_DNS_RECORD` dir `out` from Subdomain.

**Interfaces - Produces:** `dns_parser.parse_dnsx(stdout)`, `parse_puredns(stdout)`; `PARSERS["dnsx"]`, `PARSERS["puredns"]`.

- [ ] **Step 1:** Test: dnsx fixture with A + CNAME records → assert `IP` delta + `RESOLVES_TO` edge with `record_type`, `DNSRecord` delta; puredns fixture → assert resolved `Subdomain` deltas; malformed-line skipped; registry resolves.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement porting the record-type mapping.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): DNS-resolution parsers (dnsx, puredns)"`.

---

### Task 3: WHOIS parser (whois)

**Files:** Create `agent/recon/parsers/whois_parser.py`; Modify `__init__.py`; fixture + `tests/recon/test_whois_parser.py`.

**Port source:** `main_recon_modules/whois_recon.py::whois_to_dict` (~95-125) - it already produces a clean dict from a whois result; port its field extraction (registrar, creation_date, expiration_date, name servers, etc.).

**Target schema (§10.3):** `Domain (name)` with props `registrar, creation_date, expiration_date`; optionally `ExternalDomain`/name-server data as props (do not invent new node types beyond §10.3). Note the whois command template emits text or JSON depending on tool - the parser input is the tool stdout; if whois output is key:value text, port `whois_to_dict`'s parsing of it.

**Interfaces - Produces:** `whois_parser.parse(stdout) -> list[AssetDelta]`; `PARSERS["whois"]`.

- [ ] **Step 1:** Test: a whois-output fixture → assert one `Domain` delta with `identity["name"]` and `props["registrar"]`/`props["expiration_date"]` populated; malformed/empty input → `[]` (no crash); registry resolves.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): whois parser (Domain registrant props)"`.

---

### Task 4: Port-scan parser (naabu)

**Files:** Create `agent/recon/parsers/naabu_parser.py`; Modify `__init__.py`; fixture + `tests/recon/test_naabu_parser.py`.

**Port source:** `main_recon_modules/port_scan.py::parse_naabu_output` (~332-465). Raw naabu `-json` line keys: `host`, `ip`, `port`, `cdn`, `cdn-name`. Service name derived via `get_service_name(port)` (port it, or a minimal common-port map - see the source's `get_service_name`).

**Target schema (§10.3):** `IP (address)` props `version`; `Port (number, protocol, ip_address)` props `state="open"` with edge `HAS_PORT` dir `in` from `IP`; `Service (name, port_number, ip_address)` with edge `RUNS_SERVICE` dir `in` from `Port`. Protocol is `"tcp"`.

**Interfaces - Produces:** `naabu_parser.parse(stdout)`; `PARSERS["naabu"]`.

- [ ] **Step 1:** Test: fixture with 2 naabu lines (same IP, two ports) → assert one `IP`, two `Port` deltas each with `HAS_PORT`←IP edge, `Service` deltas with `RUNS_SERVICE`←Port edge; assert Port identity carries `(number, protocol, ip_address)`; malformed-line skipped; registry resolves.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (+ `get_service_name` mapping ported). **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): naabu parser (IP/Port/Service)"`.

---

### Task 5: Crawl parser (katana)

**Files:** Create `agent/recon/parsers/katana_parser.py`; Modify `__init__.py`; fixture + `tests/recon/test_katana_parser.py`.

**Port source:** `helpers/resource_enum/katana_helpers.py` (`run_katana_crawler` + the merge-into-by_base_url logic). Katana `-jsonl` line shape: `{"request":{"endpoint":..,"method":..},"response":{"status_code":..}}` (read the source for exact nesting).

**Target schema (§10.3):** `BaseURL (url)`; `Endpoint (path, method, baseurl)` props `url, status_code, content_type, source="resource_enum"` with edge `HAS_ENDPOINT` dir `in` from `BaseURL`. Extract query parameters into `Parameter (name, position="query", endpoint_path, baseurl)` with edge `HAS_PARAMETER` dir `in` from `Endpoint` where katana surfaces them.

**Interfaces - Produces:** `katana_parser.parse(stdout)`; `PARSERS["katana"]`.

- [ ] **Step 1:** Test: katana jsonl fixture (2 crawled URLs, one with a query param) → assert `BaseURL` + `Endpoint` deltas with `HAS_ENDPOINT` edge and correct `path`/`method`; assert query param → `Parameter` delta with `HAS_PARAMETER` edge; malformed-line skipped; registry resolves.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): katana crawl parser (BaseURL/Endpoint/Parameter)"`.

---

### Task 6: Passive-URL parsers (gau, paramspider)

**Files:** Create `agent/recon/parsers/passive_url_parser.py`; Modify `__init__.py`; fixtures + `tests/recon/test_passive_url_parser.py`.

**Port sources:**
- gau: `helpers/resource_enum/gau_helpers.py::parse_gau_url_to_endpoint` (~325) + `detect_gau_methods`. gau emits plain-text URLs (one per line, NOT json) - the parser splits lines and URL-parses each into an endpoint + query params.
- paramspider: `helpers/resource_enum/paramspider_helpers.py::run_paramspider_discovery` / `merge_paramspider_into_by_base_url` (~92/163). paramspider emits URLs with `FUZZ`-marked params; port the param extraction.

**Target schema (§10.3):** `BaseURL (url)`; `Endpoint (path, method="GET", baseurl)` edge `HAS_ENDPOINT` dir `in` from BaseURL; `Parameter (name, position="query", endpoint_path, baseurl)` edge `HAS_PARAMETER` dir `in` from Endpoint. `source` prop `"gau"`/`"paramspider"`.

**Interfaces - Produces:** `passive_url_parser.parse_gau(stdout)`, `parse_paramspider(stdout)`; `PARSERS["gau"]`, `PARSERS["paramspider"]`. Share a `_url_to_deltas(url, source)` helper (URL → BaseURL+Endpoint+Parameters).

- [ ] **Step 1:** Test: gau fixture (plain-text URLs incl. one `?id=1&q=x`) → assert `Endpoint` + two `Parameter` deltas with correct positions/edges; paramspider fixture → assert params extracted; blank/garbage line skipped; both registry names resolve.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (shared `_url_to_deltas`). **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): passive-URL parsers (gau, paramspider)"`.

---

### Task 7: Active param/route parsers (arjun, ffuf, kiterunner)

**Files:** Create `agent/recon/parsers/active_param_parser.py`; Modify `__init__.py`; fixtures + `tests/recon/test_active_param_parser.py`.

**Port sources:**
- arjun: `helpers/resource_enum/arjun_helpers.py::run_arjun_discovery` (~232) + `merge_arjun_into_by_base_url` (~325). arjun `-oJ` JSON: `{url: {params:[...], method:..}}` (read source).
- ffuf: `helpers/resource_enum/ffuf_helpers.py::run_ffuf_discovery` (~144) + `merge_ffuf_into_by_base_url` (~300). ffuf `-of json`: `{results:[{url, status, ...}]}`.
- kiterunner: `helpers/resource_enum/kiterunner_helpers.py::run_kiterunner_discovery` (~180) + `merge_kiterunner_into_by_base_url` (~422). kiterunner route output.

**Target schema (§10.3):** arjun → `Parameter (name, position, endpoint_path, baseurl)` + `HAS_PARAMETER` edge from `Endpoint (path, method, baseurl)`. ffuf/kiterunner → discovered `Endpoint (path, method, baseurl)` props `status_code, source` + `HAS_ENDPOINT` edge from `BaseURL`.

**Interfaces - Produces:** `active_param_parser.parse_arjun(stdout)`, `parse_ffuf(stdout)`, `parse_kiterunner(stdout)`; `PARSERS["arjun"|"ffuf"|"kiterunner"]`.

- [ ] **Step 1:** Test one behavior per tool: arjun fixture → `Parameter` deltas with `HAS_PARAMETER` edge; ffuf fixture (`results` array, mixed status) → `Endpoint` deltas with `status_code`; kiterunner fixture → `Endpoint` deltas; malformed input tolerated per parser; all three registry names resolve.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): active param/route parsers (arjun, ffuf, kiterunner)"`.

---

### Task 8: JS-analysis parser (jsluice)

**Files:** Create `agent/recon/parsers/jsluice_parser.py`; Modify `__init__.py`; fixture + `tests/recon/test_jsluice_parser.py`.

**Port source:** `helpers/resource_enum/jsluice_helpers.py::run_jsluice_analysis` (~269) + `merge_jsluice_into_by_base_url` (~391). jsluice emits JSON lines of two kinds: `url` objects (`{url, method, ...}`) and `secret` objects (`{kind, ...}`).

**Target schema (§10.3):** `Endpoint (path, method, baseurl)` + `HAS_ENDPOINT` from `BaseURL` for discovered URLs; `Secret (value_hash)` props `kind, source="jsluice", redacted=true` + edge `HAS_SECRET` dir `in` from `BaseURL`. Hash secret values (`sha1`), never store the raw secret (design §10.3 `Secret` is redacted).

**Interfaces - Produces:** `jsluice_parser.parse(stdout)`; `PARSERS["jsluice"]`.

- [ ] **Step 1:** Test: jsluice jsonl fixture (one url object, one secret object) → assert `Endpoint` delta + `HAS_ENDPOINT` edge; assert `Secret` delta with `value_hash` (hashed, not raw) + `redacted=true` + `HAS_SECRET` edge; malformed-line skipped; registry resolves.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement (with `sha1` redaction). **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): jsluice parser (Endpoint + redacted Secret)"`.

---

### Task 9: GraphQL-scan parser (graphql_scan / graphql-cop)

**Files:** Create `agent/recon/parsers/graphql_parser.py`; Modify `__init__.py`; fixture + `tests/recon/test_graphql_parser.py`.

**Port source:** `recon/graphql_scan/` (`introspection.py`, `misconfig.py`, `normalizers.py`) and the `graphql-cop` JSON output shape. graphql-cop emits a JSON array of checks `[{title, description, impact, result, ...}]`.

**Target schema:** the GraphQL endpoint itself → `Endpoint (path, method="POST", baseurl)` props `endpoint_type="graphql"` + `HAS_ENDPOINT` from `BaseURL`. Misconfiguration findings are **Observations**, not vulnerabilities (§5). Since parsers emit `AssetDelta`s (not Observations) and the pod's triager owns Observations, THIS parser returns the graph asset (the graphql Endpoint) as an `AssetDelta`, and **exposes the parsed findings as a separate structured return for the triager**: implement `parse(stdout) -> list[AssetDelta]` (endpoint asset only) plus `parse_findings(stdout) -> list[dict]` (normalized `{title, severity, evidence}` finding dicts) that the pod's triager step can turn into `Observation`s. Document this two-output shape in the module docstring; register only `parse` in `PARSERS`.

**Interfaces - Produces:** `graphql_parser.parse(stdout)`, `graphql_parser.parse_findings(stdout)`; `PARSERS["graphql-cop"]`.

- [ ] **Step 1:** Test: graphql-cop JSON fixture (2 checks, one failing) → `parse` returns a graphql `Endpoint` delta; `parse_findings` returns finding dicts with `title`/`severity`/`evidence` for the failing check; malformed input tolerated; registry resolves.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): graphql-cop parser (Endpoint + finding dicts for triager)"`.

---

### Task 10: Subdomain-takeover parser (subdomain_takeover)

**Files:** Create `agent/recon/parsers/takeover_parser.py`; Modify `__init__.py`; fixture + `tests/recon/test_takeover_parser.py`.

**Port source:** `main_recon_modules/subdomain_takeover.py` + `graph_db/mixins/recon/takeover_mixin.py` + `helpers/takeover_helpers.py`. Output: per-subdomain takeover candidacy `{subdomain, service, vulnerable, cname, ...}`.

**Target schema:** takeover results are **Observations** (§5, no vulnerability nodes). Mirror Task 9's split: `parse(stdout) -> list[AssetDelta]` returns any graph asset it confirms (e.g. an `ExternalDomain (domain)` for a dangling CNAME target, edge `HAS_EXTERNAL_DOMAIN` from `Domain`), and `parse_findings(stdout) -> list[dict]` returns takeover finding dicts (`{title:"potential_subdomain_takeover", severity, evidence, anchor:{type:"Subdomain", identity:{name}}}`) for the triager to emit as `Observation`s. Register only `parse`.

**Interfaces - Produces:** `takeover_parser.parse(stdout)`, `parse_findings(stdout)`; `PARSERS["subdomain_takeover"]`.

- [ ] **Step 1:** Test: fixture with one vulnerable + one safe subdomain → `parse_findings` returns one finding anchored to the vulnerable Subdomain with a `Subdomain` anchor; `parse` returns `ExternalDomain` delta when a dangling CNAME target is present; safe entry yields no finding; registry resolves.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): subdomain-takeover parser (ExternalDomain + finding dicts)"`.

---

## Self-Review (author checklist, completed)

- **Coverage:** the fleet now covers every §7 job-set tool + the D1 scope-expansion tools except the two that are their own sub-plans (steel/agentic-crawl → sub-plan 4; nuclei → sub-plan 5). Enumerated against the memory parser list: subfinder, amass, puredns, dnsx, whois, naabu, katana, gau, arjun, ffuf, jsluice, kiterunner, paramspider, graphql_scan, subdomain_takeover - all present (httpx done in Foundation). None forgotten.
- **Placeholder scan:** each task names the exact Redamon source function + file + line range and the authoritative §10.3 target schema, following the proven Task-4 port pattern (the source is the detailed spec for a port; the implementer reads it as in Foundation Task 4). No "similar to"/"TBD".
- **Findings-vs-assets split:** graphql_scan and subdomain_takeover use the documented `parse` (assets) + `parse_findings` (dicts → triager Observations) split, honoring design §5 "security_check → Observations, never Vulnerability nodes".
- **Type consistency:** all parsers share the `parse(stdout) -> list[AssetDelta]` contract, register in `PARSERS`, and reuse `AssetDelta`/`Edge`; the `parse_findings` second output is only on the two findings-tools and is explicitly documented.
