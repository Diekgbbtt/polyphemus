# Recon auth coverage verification (arm J re-pass)

Date: 2026-10-17.
Branch: `feat/recon-coverage-and-eval-wellformedness`.
Scope: verify whether recon ran authenticated and whether API enumeration ran with auth headers; quantify the chaining-branch defect; check typist/assigner auth-context and HTTP-history access.

## TL;DR

1. Recon ran authenticated on white-jotter (both runs); comfyui needs no auth by design.
2. API enumeration (kiterunner) ran authenticated on white-jotter (99.98% of probes carried the session cookies) but produced **zero graph assets on every executed run**.
   Root cause: the job never selects a machine-readable output format, so the parser and the pod triager only ever see kiterunner's settings table. Filed as #361.
3. Relative-endpoint chaining minted wrong branches that later probes classified as normal endpoints (comfyui 73 x 404 of 91 chained); a role-gated endpoint (`/api/menu`) was recorded as 404 although it is real. Filed as #363.
4. The typist and the assigner cannot read the auth context (no `auth_store` binding) although the typist used HTTP-history queries heavily for request shapes. Filed as #364.
5. Steel-local reachability, CDP network capture, and per-phase job-specialised agents are covered by #359, #360, #362.

## 1. Runs under measurement

| Label | Project ID | Run ID | Window (UTC) | Target |
|---|---|---|---|---|
| comfyui baseline | `2df3ad9d-eb9c-4789-a118-44139a745ca2` | `9ae295dc-d6fc-4180-a386-11598881a679` | 2026-10-15 22:02:38 - 22:17:28 | `t-1fc05262.target` |
| wj baseline | `bf0d9408-d403-457f-b769-076dd9cd9138` | `131ba77d-6abc-44fd-83fb-329d4635f46c` | 2026-10-15 23:05:57 - 23:13:51 | `t-1618c524.target` |
| comfyui formal | `d04b947f-d6c3-48be-9b18-1c4eef851241` | `6f377607-b16a-4b62-9253-3e656081c820` | 2026-10-16 19:40:20 - 19:54:49 | `t-1fc05262.target` |
| wj formal | `f16de150-b032-4566-871b-2df6fa4d48a9` | `0f9c7df9-ae9c-446e-8c9d-7ed23b87cabc` | 2026-10-16 20:36:22 - 20:53:49 | `t-1618c524.target` |

Sources: `recon_runs` (Postgres), per-project flow stores (`/data/<project>/http-history/history.sqlite3`), Neo4j graphs, Langfuse observations.

## 2. Q1 - did recon run authenticated?

Verdict: comfyui does not need auth (mechanism `none`); white-jotter ran authenticated in both runs.

Evidence, white-jotter.

- The auth store holds the in-run minted bootstrap account `wjprobe_1790894002-first_authn_bootstrap` with a `JSESSIONID` (`A254B58583CB18A8FA25F4E0A56D38D8`) and a `rememberMe` value.
- Every request-based job command carries the cookie pair, e.g. kiterunner wj formal: `-H 'Cookie: rememberMe=...; JSESSIONID=...; ...'`.
- Flow-store transport: wj formal 22,085 of 22,425 target-host flows are cookie-bearing (~98.5%); wj baseline 5,103 of 5,441.
- Live verification: `GET /api/authentication` returns 200 with the session cookie and 302 without it.
- The kiterunner probes carried **both** cookies on 16,899 of 16,903 requests (~99.98%).

Evidence, comfyui.

- Auth mechanism `none`; the baseline flow store holds 33,148 flows with 0 cookie-bearing requests.

Caveat - identity ceiling.

- The bootstrap identity is a plain registered user (role 2, not admin).
- Role-gated endpoints are invisible to it: `GET /api/menu` returns 302 (Shiro redirect to `/nowhere`) for the recon session, while hunt pods with self-escalated (role-binding) sessions get 200.
- A 404 or 302 recorded for a chained branch can therefore be a role-gate artifact, not evidence of a wrong branch (see section 4).

## 3. Q2 - did API enumeration (kiterunner) run with auth headers?

Verdict: transport YES, yield ZERO.

Job-level results (`recon_jobs.stats`).

| Run | Status | produced_assets | produced_observations | exec_seconds | Captured kiterunner flows | Status mix |
|---|---|---|---|---|---|---|
| comfyui baseline | success | 0 | 0 | 290.36 | 26,994 | 405 x15,373; 404 x11,601; 200 x16; 403 x2; 500 x2 |
| comfyui formal | success | 0 | 0 | 262.53 | 26,994 | 404 x16,726; 405 x10,248; 200 x16; 403 x2; 500 x2 |
| wj baseline | skipped | 0 | 0 | 0.02 | 0 | no `profile=restapi` endpoint, so the job never ran |
| wj formal | success | 0 | 0 | 522.89 | 16,903 | 405 x9,571; 404 x7,262; 200 x62; status-less x8 |

- Zero `source=kiterunner` endpoints exist in any of the four graphs (source census: comfyui baseline httpx 183 / katana 105 / jsluice 1 / steel 1; comfyui formal httpx 228 / katana 102 / jsluice 4 / steel 1; wj baseline httpx 54 / katana 2 / steel 1; wj formal httpx 65 / jsluice 25 / katana 2 / steel 1).
- Findable results were found and lost: comfyui `GET /` (x7), `GET /api/` (x8), `GET /api/users` (x1); wj `GET /api/search/`, `GET /api/search`, `GET /api/login/`, `GET /api/admin/`, `POST /api/admin/users`, plus admin-shaped paths (x62 flows).
  `POST /api/admin/users` is absent from the graph; `GET /api/search` sits with `status_code NULL` from a jsluice chained record.

Root cause chain (proven by live reproduction, details in section 6).

1. The command template `kr scan {target} -w /opt/localbin/routes-small.kite {auth_flags}` uses kiterunner's default pretty output.
   Live: stdout carries **exactly the settings table** (3,588 bytes, byte-identical across runs).
2. When kr finds routes, the pretty result lines look like `GET     200 [      5,    1,   1] http://host/path` with ANSI colour codes.
   `_kiterunner_text_line` expects `parts[2]` to be the URL, so the bracket and ANSI tokens make every result line unparseable.
   Local proof: `parse_kiterunner` returns `[]` for that exact line, with and without ANSI.
3. `parse_kiterunner`'s JSON branch expects the `-o json` shape (`{"method","target","path","responses":[{"sc"}]}`); the template never passes `-o json`.
   Local proof: the real JSON line parses to BaseURL + Endpoint deltas with `source=kiterunner`, `profile=restapi`, `status_code=200`.
4. The pod triager's prompt embeds `stdout[:4000]`; the settings table alone fills ~3.5 KB.
   The triager recorded: "No parsed assets were produced by this run - the output is only kiterunner's settings banner (delay, etc.) with no route, response, or host data."
5. Budget context: the wj formal job reports `exec_seconds 522.89` with `EXEC_TIMEOUT_S=300` (one pod, one triager generation).
   The pod gate retries any non-zero exit up to `MAX_POD_ITERS`; reconcile the metric and retry semantics while fixing the template.

Answer to the operator's question: the enumeration did run with the correct auth material, but its results were structurally discarded before parsing.
Fix: #361.

### Arjun - second zero-yield enumeration phase

| Run | Status | produced_assets | exec_seconds |
|---|---|---|---|
| comfyui baseline | success | 0 | 277.40 |
| wj baseline | success | 0 | 46.94 |
| comfyui formal | success | 0 | 289.42 |
| wj formal | success | 0 | 68.59 |

- The wiring is correct: the command seeds `printf '{}' > arjun.json`, runs `arjun -i <urls> --rate-limit 5 -oJ arjun.json`, and `cat`s the file; `_loads_lenient` tolerates the zero-finding `{}`.
- Zero is therefore genuine: arjun found no parameters in any run.
- The input set is tiny: 3-5 URLs per run (wj formal: `/api/register`, `/api/logout`, `/`, and a bundle manifest), selected from the route-deduped endpoint population.
- Every arjun command carries the cookie pair (duplicated) and a static `--rate-limit 5`.
- Owner: the per-phase shaping work (#362); see also #37 and #357.

## 4. Chaining-branch defect quantification

Counts (endpoints carrying `chained_prefix`).

| Run | Chained endpoints | 404 | 200 | Other |
|---|---|---|---|---|
| comfyui baseline | 4 | 1 | 2 | 1 |
| comfyui formal | 91 | 73 | 17 | 1 x 405 |
| wj baseline | 0 | - | - | - |
| wj formal | 36 | 11 | 3 | 22 never probed |

Mechanics and evidence.

- `jsluice_scan.py` runtime-base chaining mints `/api/<literal>` twins from JS bundle literals.
- Garbage fragments and SPA route literals entered the graph as API endpoints: `/api/I4U`, `/api/bpg`, `/api/i/W`, `/api/ocq`, `/api/index`, `/api/jotter`, `/api/jotter/article`, `/api/library`, `/api/home`.
  These come from minified-bundle string fragments (for example `I4U`, `bpg`, `ocq`) and client-side route names.
- `httpx_reprofile` probed them later; it runs with follow-redirects, so the recorded status is the final hop.
- The role-gate trap: `/api/menu` probe returned 302 directly (Location `/nowhere`), the followed request 404.
  The graph node carries 404 with `content_type: text/html`; the capture plane recorded the first hop (302); a privileged session gets 200.
  A naive "404 means wrong branch" rule would drop a real endpoint.
- The reprofile command shape is correct by contrast: it writes an endpoint list, runs httpx with `-o reprofile.json`, and `cat`s the file.

Proposed rule and fix: #363.

## 5. Analysis-phase auth-context and HTTP-history access

Bindings today (`src/polymerhus/analysis/proposer_turn.py::_surface_tools`).

- Assigner: HTTP-history pair only (`search_http_history`, `get_http_artifact`); the `graph_view` binding was rolled back deliberately.
- Mechanism-typist: read-only `graph_view` + the HTTP-history pair + the bounded `exec` term.
- No other role binds surface tools.
- Neither role binds `auth_store`; `recon/CONTEXT.md` states "the analysis-domain agents never bind it".

Census (Langfuse, formal windows).

| Tool | wj typist | wj assigner | comfyui typist | comfyui assigner |
|---|---|---|---|---|
| `search_http_history` | 14 | 14 | 32 | 48 |
| `get_http_artifact` | 12 | 8 | 10 | 9 |
| `auth_store` | 0 | 0 | 0 | 0 |

`auth_store` calls appear only recon-side (job_orchestrator 8, pod_runner 9 on wj).
Note: every analysis tool call is traced twice (once with the explicit `project_id` key, once without), so the distinct call count is about half of the traced count.

Sample typist queries (request shapes).

- wj: `request.url contains /api/`; `response.status eq 307`; `response.set-cookie contains JSESSIONID`; `request.JSESSIONID contains A254B`; `text=/static/js/11.728d3bfb9f2fa89a4f29.js`; `text=index.html`.
- comfyui: `text=firebase`; `text=firebaseio`; `request.url contains cloud`; `text=websocket`; `response.location contains t-1fc05262`; `response.server contains nginx`; `response.set-cookie absent`; `request.path contains experiment/models`.

Sample assigner queries.

- wj: `response.status eq 307`; `request.url eq http://t-1618c524.target/`; `response.content-type contains text/html`; `request.host eq t-1618c524.target`.
- comfyui: `response.status_class eq 3xx`; `request.url prefix https://t-1fc05262.target`; `response.location absent`; `request.method eq GET; response.content-type contains text/html`; `text=t-1fc05262.target/models`.

Verdict.

- The typist did use HTTP-history queries for request shapes (yes, extensively on both targets).
- Neither role can read the auth context. The typist filtered on `request.JSESSIONID contains A254B` but cannot see what that cookie is, where it came from, or when it expires.
- Fix: #364 (read-only `auth_store` binding for typist and assigner, D223-5 pattern).

## 6. Reproductions and methods

Kiterunner output contract (live, 2026-10-17, container `ph-dd131acc-kali-1`).

- Static server inside kali; four routes.
- Pretty: `kr brute <target> -w routes` with no `-o`.
  Stdout: 3,484 bytes - the settings table plus `GET     200 [      5,    1,   1] http://127.0.0.1:8765/a.txt` with ANSI colour codes.
  Stderr: ASCII banner, progress bar, `INF scan complete ... results=2`.
- JSON: `kr brute <target> -w routes -o json`.
  Stdout: 276 bytes, two JSON lines: `{"method":"GET","target":"http://127.0.0.1:8765","path":"/a.txt","responses":[{"uri":"","sc":200,"len":5}],"time":"2026-10-17T09:50:26Z"}`.
  The settings table is suppressed.
- Parser: `parse_kiterunner(pretty_line)` returns `[]` (with and without ANSI); `parse_kiterunner(json_line)` returns BaseURL + Endpoint deltas.
- The URL helpers filter loopback hosts by design; the pod targets parse normally (verified with the real target host).

Data pulls.

- Flows: read `/data/<project>/http-history/history.sqlite3` inside kali; attribute tools from `capture_context.session_id` (`<run>-<index>-<tool>-<specid>`).
- Jobs: `recon_jobs.stats` (`produced_assets`, `produced_observations`, `exec_seconds`, `commands`).
- Graph: `cypher-shell` against `ph-dd131acc-neo4j-1`; endpoint source census per project.
- Langfuse: observations API v2, `type=TOOL` + `name=<tool>` + `fields=core,basic,io`; the pod triager session is `<run>:<index>:kiterunner:<target>:triager`.

Auth-material duplication (finding for #362).

- Every request-based wj formal command carries `JSESSIONID` and `rememberMe` twice: arjun, ffuf, httpx, httpx_reprofile, katana, kiterunner.
- jsluice's batched command carries none.

## 7. Tickets filed

| Ticket | Summary | Operator ask |
|---|---|---|
| #359 | Local Steel deployment must reach non-internet targets (eval instances, intranets); child of #245 | (a) |
| #360 | steel_crawl must capture CDP network interactions (XHR/fetch) and feed them into the surface + HTTP history; part of #50, related #353 | (b) |
| #361 | kiterunner zero assets on every run - never selects a machine-readable output format | measurement |
| #362 | Per-phase job-specialised agents shape inputs, request shape, output contract, and budget before dispatch; builds on the `job_agent.py` stub | (c) |
| #363 | Validate relative-endpoint chaining branches with a light HTTP probe (wrong-branch rule) | chaining check |
| #364 | Bind the read-only `auth_store` to mechanism_typist and assigner | typist/assigner check |

Presence check against existing tickets.

- (a) #245 exists (local Steel stack) but motivates it by egress stability and reCAPTCHA cost; the non-internet reachability case is new and filed as its child #359.
- (b) #50 is the steel_crawl parent with children #38 (login-first bug) and #51 (DOM-delta); network capture is not covered, so #360 is new.
- (c) #336 covers the orchestrator decision node by auth posture only; the per-phase shaping agents are new as #362.

## 8. Loose ends (recorded, non-blocking)

- `exec_seconds 522.89` exceeds `EXEC_TIMEOUT_S=300` on wj formal kiterunner; confirm the metric and the retry semantics during #361.
- The `httpx_reprofile` record for `/api/menu` stores status 404 (after redirect-follow) while the capture plane stores the direct 302; both must stay distinguishable in the graph (#363).
- Arjun consumed only 3-5 URLs per run; the input-set policy has no owner (#362, #37, #357).
- Every analysis tool call is traced twice; confirm the tracing semantics before re-measuring analysis cache ratios.
- wj baseline never produced a `profile=restapi` endpoint, so kiterunner was skipped there; this is a profile-coverage gap, not a transport failure.
