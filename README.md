# polymerhus — platform stack

Autonomous vulnerability-discovery harness. Iteration 1 (recon MVP) substrate:
four containers the recon pipeline and documentation-ingestion subsystem run on.

## Prerequisites
Two base images must exist locally (reused, not rebuilt):
`redamon-agent:latest`, `redamon-kali-sandbox:latest` (`docker images` to check).

## Run
    cp .env.example .env
    docker compose up -d --build                # prod-ish
    # dev (agent hot-reload + live source):
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

Services: agent `:8080/health` · kali fastmcp `:8000/mcp` · neo4j `:7474`/`:7687` (neo4j/polymerhus) · postgres `:5432`.

## Verify

Tests are tiered. Full reference: `docs/design/testing-strategy.md`.

    # UNIT tier - needs nothing running. Must never touch a real database
    # (enforced: tests/conftest.py raises on any live Neo4j access).
    .venv/bin/python -m pytest tests/ -q

    # INTEGRATION / E2E tier - run INSIDE the compose network, so it resolves
    # `neo4j` by service DNS exactly as the agent does.
    docker compose -f docker-compose.yml -f docker-compose.dev.yml \
      run --rm tests tests/integration -q

    .venv/bin/python -m pytest tests/e2e/ -q   # deep e2e + observability

Expected (2026-07-22): unit tier 892 passed / 37 skipped / 0 failed; in-network
integration 41 passed / 0 skipped.

Note `tests/e2e/test_stack_smoke.py` runs `docker compose up -d --build`, so a
plain suite run rebuilds your stack - do not run it concurrently with an
in-network run.

`tests/e2e/` covers real work + failure paths: a live jsluice URL-extraction run,
idempotent neo4j MERGE, pgvector cosine search, checkpoint persistence, and the
observability paths (a degraded backend is reported *and diagnosed*, exec failures
surface returncode/stderr/timeout).

`GET /health` returns `{"status":"ok","checks":{...},"errors":{}}` when healthy; on a
degraded backend, `status` is `degraded`, its check is `false`, and `errors.<backend>`
carries the reason (e.g. connection refused).

## Reload during dev
- agent: automatic (`uvicorn --reload`).
- kali MCP server / gap-fill: `docker restart kali`.
- schemas: neo4j re-applied by the agent on reload; postgres `init.sql` re-runs only on `down -v`.

## Schemas
- Neo4j Layer-0 constraints: `db/neo4j/schema.py` (applied by the agent at startup).
- Postgres app + `doc_chunks` corpus: `db/postgres/init.sql` (first DB init).
- LangGraph checkpoints: `AsyncPostgresSaver.setup()` at agent startup.

## Kali recon tools
`redamon-kali-sandbox` ships the ProjectDiscovery suite + arjun/masscan/nmap; `kali/postrun.sh`
gap-fills massdns/puredns/whois/graphql-cop/kiterunner into a persisted volume on first `up`.

## Launching a recon run

### Interfaces

The agent REST API (`:8080`) is the only interface that can create projects, configure a
target, and launch a run.
Everything is plain JSON over HTTP, so `curl`, the Python client, or any HTTP tool works.

    POST   /projects                          # {name} -> {project_id}
    GET    /projects                           # -> {projects: [...]}
    PUT    /projects/{id}/settings              # {recon: {target_domain, ...}} -> {ok}
    POST   /projects/{id}/recon                 # {jobs?: [...]} -> {run_id}
    GET    /projects/{id}/recon/{run_id}        # -> {status, current_phase, per_job}
    GET    /runs?status=running                 # -> {runs: [...], liveness_ttl_seconds}
    GET    /projects/{id}/graph                 # -> {nodes, links} (reads Neo4j live)

The frontend (`cd frontend && npm run dev`, default `:5173`) is a read-only viewer.
It proxies `/projects` and `/runs` to the agent (`vite.config.ts`, override the target with
`AGENT_PROXY_TARGET`) and renders the projects list, the live graph, and running-run status.
It has no launch or settings form, so a run always starts through the API above.

### Walkthrough

    # 1. create a project
    curl -s -X POST localhost:8080/projects -H 'Content-Type: application/json' \
      -d '{"name":"my-target"}'
    # -> {"project_id": "<id>"}

    # 2. point it at a target (see seed-host modes below)
    curl -s -X PUT localhost:8080/projects/<id>/settings -H 'Content-Type: application/json' \
      -d '{"recon":{"target_domain":"www.example.com"}}'

    # 2.b. [OPTIONAL] feed an auth context (see "Project settings" below for the full shape)
    e.g. authn cookies:
    curl -s -X PUT localhost:8080/projects/<id>/settings -H 'Content-Type: application/json' \
      -d '{"recon":{"auth_context":{"cookies":[{"name":"session","value":"..."}]}}}'
    # or an arbitrary auth header (header-agnostic: any non-reserved key is a request header):
    curl -s -X PUT localhost:8080/projects/<id>/settings -H 'Content-Type: application/json' \
      -d '{"recon":{"auth_context":{"Authorization":"Bearer <token>"}}}'

    # 3. launch a run (omit "jobs" to run the full phase plan)
    curl -s -X POST localhost:8080/projects/<id>/recon -H 'Content-Type: application/json' -d '{}'
    # -> {"run_id": "<run_id>"}

    # 4. poll until status leaves "running"
    curl -s localhost:8080/projects/<id>/recon/<run_id>

    # 5. pull the mapped attack surface once complete
    curl -s localhost:8080/projects/<id>/graph -o graph.json

### Project settings

Settings are the `recon` object sent to `PUT /projects/{id}/settings` and persisted as the
`settings.recon` JSONB blob. Writes are a **recursive (deep) merge**, so a PUT that sets only
`auth_context` preserves a previously-set `target_domain`, and a PUT that sets only
`auth_context.credentials` preserves a previously-set `auth_context.cookies` (nested items are
independent at any depth; scalars and arrays like the cookies list are replaced wholesale).
Everything below is optional except `target_domain`, which a run requires (a targetless
`POST /recon` is rejected 400).

| Setting | Type | Purpose |
|---|---|---|
| `target_domain` | string | The recon target. `example.com` / `app.example.com` = exact host (discovery suppressed); `*.example.com` = wildcard/zone (subdomain discovery fans out). See "Exact vs wildcard seed hosts" below. **Required to launch.** |
| `auth_context` | object | Authentication material, threaded into every `use_auth` job (httpx, katana, ffuf, steel_crawl, arjun). **Header-agnostic:** besides the reserved structural keys below (`cookies`, `scope`, `credentials`), any other key is treated as an arbitrary HTTP request header. All sub-fields optional; omit `auth_context` entirely for an anonymous run. |
| `auth_context.cookies` | list of `{name, value}` | Session cookies. Joined into the `Cookie: k=v; k2=v2` header for the **request-based** tools, and injected into the Steel browser context for a **non-interactive** authenticated agentic crawl. Each entry may also carry optional `domain`/`path`. This is the one source of the `Cookie` header; a literal `Cookie` header key is rejected. |
| `auth_context.<Header-Name>` | string | Any other key is an **arbitrary request header** sent verbatim by the request-based tools, e.g. `"Authorization": "Bearer <token>"` or `"X-Api-Key": "<key>"`. Header names must be HTTP tokens (letters/digits/hyphen); values are non-empty strings with no CR/LF (header-injection guard). Applies to the request-based tools only (not the Steel browser context yet). |
| `auth_context.scope` | string | Optional auth scope hint. Reserved structural key, not sent as a header. |
| `auth_context.credentials` | object | **Autonomous agentic-crawl login (D23).** The Steel crawl agent logs itself in with these before crawling - the credentials channel drives the *agentic* crawl, while `cookies` drive the *request-based* tools. |
| `auth_context.credentials.username` | string | Login username/email. **Required** inside `credentials`. |
| `auth_context.credentials.password` | string | Login password. **Required** inside `credentials`. Sent to the target you authorize; may appear in the crawl LLM trace (accepted under the pen-test threat model). |
| `auth_context.credentials.login_url` | string | URL of the sign-in page to navigate to. **Required** inside `credentials`. May be a different origin than the target (e.g. `login.example.com`); login succeeds only if it yields an in-scope target session. |
| `auth_context.credentials.domain` | string | Optional. Restricts which target host the login is attempted against (else derived from `login_url`), so one app's credentials are not submitted to every host in a run. |
| `auth_context.credentials.username_selector` | string | Optional CSS selector override for the username field (else auto-detected). |
| `auth_context.credentials.password_selector` | string | Optional CSS selector override for the password field (else `input[type=password]`). |
| `auth_context.credentials.submit_selector` | string | Optional CSS selector override for the submit control (else the form's submit). |

Launch-time (not persisted, sent to `POST /projects/{id}/recon`):

| Field | Type | Purpose |
|---|---|---|
| `jobs` | list of strings | Optional job subset, e.g. `{"jobs": ["httpx", "naabu"]}`. Omit to run the full phase plan. Rejected 400 if a selected job's input type isn't produced by an earlier selected job. |

Example with credentials:

    curl -s -X PUT localhost:8080/projects/<id>/settings -H 'Content-Type: application/json' -d '{
      "recon": {
        "target_domain": "*.example.com",
        "auth_context": {
          "cookies": [{"name": "session", "value": "..."}],
          "credentials": {
            "username": "user@example.com", "password": "...",
            "login_url": "https://login.example.com/", "domain": "example.com"
          }
        }
      }
    }'

> Note: deployment-level knobs (`MAX_PODS`, `MAX_JOB_ASSETS`, `CRAWL_*`, `STEEL_API_KEY`,
> `DISCORD_WEBHOOK_URL`, `LANGFUSE_*`, ...) are **environment variables**, not project settings -
> see `.env.example`. A `max_pods` key inside a project's `recon` blob is not read.

### Exact vs wildcard seed hosts

`target_domain` is parsed into a scope (`agent/recon/scope.py`, decision D14) that decides
whether subdomain discovery runs at all:

| `target_domain` value        | mode       | seeded host          | subdomain discovery |
|-------------------------------|------------|-----------------------|----------------------|
| `*.example.com`               | `wildcard` | `example.com` (apex)  | runs (subfinder, amass, dnsx, puredns fan out across the zone) |
| `example.com`                 | `exact`    | `example.com`         | suppressed - recon stays confined to that single host |
| `app.example.com`             | `exact`    | `app.example.com`     | suppressed - recon stays confined to that single host |
| unset / empty                 | `exact`    | `example.com` (default placeholder) | suppressed |

In `exact` mode `subfinder`/`amass`/`dnsx`/`puredns` are dropped from the phase plan and the
seeded host is injected directly into the post-discovery input set, so `httpx`/`naabu` still
probe it (D11).
`subdomain_takeover` and the passive harvesters (`whois`, `paramspider`) are never gated
by scope mode, since they either take an out-of-scope asset as a parameter or don't enumerate
subdomains in the first place.
Use wildcard (`*.example.com`) when you want the whole zone fanned out, and an exact host when
you already know the target and want a fast, narrow run.

### Phases

Jobs run in ordered, gated phases (`agent/recon/jobs.py`). A phase is a **hard barrier**: the next
phase does not start until every job in the current phase has finished. **Within a phase, jobs run
sequentially** (one at a time) - each job still fans its assets out across up to `MAX_PODS`
concurrent pods, but only one job's fan-out runs at once, so peak concurrency is bounded to a
single tool's `MAX_PODS` rather than `jobs x MAX_PODS` (the latter exhausted the agent's memory).

| Phase | Jobs | Produces |
|---|---|---|
| 0 | `subfinder`, `amass`†, `whois` | Subdomain, IP, Domain |
| 1 | `dnsx`, `puredns`, `subdomain_takeover` | IP, DNSRecord, Subdomain, ExternalDomain |
| 2 | `naabu` | IP, Port, Service |
| 3 | `httpx` | BaseURL, Endpoint, Technology, Certificate, Header (+ `profile`) |
| 4 | `katana`, `ffuf`, `paramspider`, `steel_crawl` | BaseURL, Endpoint, Parameter |
| 5 | `jsluice`◦ | Endpoint, Secret |
| 6 | `httpx_reprofile` | BaseURL, Endpoint, Technology, Certificate, Header (+ `profile`) |
| 7 | `kiterunner`◦ *(api enumeration)* | Endpoint |
| 8 | `arjun` | Parameter |
| 9 | `graphql-cop`◦ *(static api testing)* | Endpoint |

† `amass` is currently **deferred** (see Tool status below).  ◦ gated on an upstream attribute.

**Profile-based routing (data dependency).** Phase 3 `httpx` tags each BaseURL/Endpoint with a
`profile` - `webapp`, `restapi`, or `graphql_api` (path heuristic, `noise_filter.classify_profile`).
But the phase-4 crawlers (`katana`/`ffuf`) and `jsluice` (phase 5) mint **new** BaseURLs - notably
the JS-derived API hosts `jsluice` recovers from bundles - which `httpx` never probed and so carry
no `profile`. Phase 6 `httpx_reprofile` re-probes **every** BaseURL (idempotent over
already-profiled ones) and classifies it via the same `classify_profile` path, so the whole
discovered surface - not just `httpx`'s originals - is profiled before the API phases. The
API-surface tools are then **gated** and produce nothing unless a match was tagged: `kiterunner`
(phase 7, *api enumeration*) consumes only `restapi` BaseURLs, `graphql-cop` (phase 9, *static api
testing*) only `graphql_api`. `arjun` (phase 8) runs after api enumeration so it discovers
Parameters on the routes `kiterunner` just found as well as `jsluice`'s recovered Endpoints. These
gates are real data dependencies: withdraw the upstream producer/attribute and the gated tool has
an empty input set.

In `exact` scope mode, phases 0 and 1 shrink to just `whois` and `subdomain_takeover` - the rest of
the pipeline is unaffected.

### Tool status

The pipeline schedules 17 tools (`agent/recon/jobs.py::JOBS`). `auth` tools receive the
`auth_context` cookies/headers; gated tools consume only a matching upstream asset.

| Tool | Phase | Status | Gating / notes |
|---|---|---|---|
| `subfinder` | 0 | active | subdomain discovery |
| `amass` | 0 | **deferred** | amass v4.2.0 removed the `-json` flag, so it currently degrades; fix pending |
| `whois` | 0 | active | registrant / nameservers |
| `dnsx` | 1 | active | DNS resolution |
| `puredns` | 1 | active | mass DNS resolution |
| `subdomain_takeover` | 1 | active | dangling-CNAME check |
| `naabu` | 2 | active | port scan |
| `httpx` | 3 | active · auth | HTTP probe; sets the `webapp`/`restapi`/`graphql_api` `profile` |
| `katana` | 4 | active · auth | crawler; mints the `.js`/`.mjs` Endpoints `jsluice` consumes |
| `ffuf` | 4 | active · auth | content discovery; rate-throttled under WAF steering |
| `paramspider` | 4 | active | passive URL/param harvest |
| `steel_crawl` | 4 | active · auth | agentic browser crawl (cookies + autonomous credentialed login) |
| `jsluice` | 5 | active | gated to `.js`/`.mjs` Endpoints; batched; JS URLs + secrets + sourcemaps |
| `httpx_reprofile` | 6 | active · auth | re-probes every BaseURL (incl. crawler/JS-minted) to assign `profile`; reuses the `httpx` parser |
| `kiterunner` | 7 | active · auth | *api enumeration*; gated to `profile == restapi` |
| `arjun` | 8 | active · auth | parameter discovery (after api enumeration, so it sees `kiterunner` routes) |
| `graphql-cop` | 9 | active · auth | *static api testing*; gated to `profile == graphql_api` |
| `gau` | - | **deferred** | passive URL harvest, withdrawn (D-gau, 2026-07-09); to be reintroduced behind a noise filter |
