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
    python -m pytest tests/ -v          # integration + e2e
    python -m pytest tests/e2e/ -v      # deep e2e + observability only

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

    # 3. launch a run (omit "jobs" to run the full phase plan)
    curl -s -X POST localhost:8080/projects/<id>/recon -H 'Content-Type: application/json' -d '{}'
    # -> {"run_id": "<run_id>"}

    # 4. poll until status leaves "running"
    curl -s localhost:8080/projects/<id>/recon/<run_id>

    # 5. pull the mapped attack surface once complete
    curl -s localhost:8080/projects/<id>/graph -o graph.json

### Project settings

Settings are the `recon` object sent to `PUT /projects/{id}/settings` and persisted as the
`settings.recon` JSONB blob. Writes are a **shallow merge**, so a PUT that sets only `auth_context`
preserves a previously-set `target_domain` (and vice versa). Everything below is optional except
`target_domain`, which a run requires (a targetless `POST /recon` is rejected 400).

| Setting | Type | Purpose |
|---|---|---|
| `target_domain` | string | The recon target. `example.com` / `app.example.com` = exact host (discovery suppressed); `*.example.com` = wildcard/zone (subdomain discovery fans out). See "Exact vs wildcard seed hosts" below. **Required to launch.** |
| `auth_context` | object | Authentication material, threaded into every `use_auth` job (httpx, katana, ffuf, steel_crawl, arjun). All sub-fields optional; omit `auth_context` entirely for an anonymous run. |
| `auth_context.cookies` | list of `{name, value}` | Session cookies. Used as the `-H "Cookie: ..."` header by the **request-based** tools, and injected into the Steel browser context for a **non-interactive** authenticated agentic crawl. Each entry may also carry optional `domain`/`path`. |
| `auth_context.scope` | string | Optional auth scope hint. |
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
`subdomain_takeover` and the passive harvesters (`whois`, `gau`, `paramspider`) are never gated
by scope mode, since they either take an out-of-scope asset as a parameter or don't enumerate
subdomains in the first place.
Use wildcard (`*.example.com`) when you want the whole zone fanned out, and an exact host when
you already know the target and want a fast, narrow run.

### Phases

Jobs run in ordered, gated phases (`agent/recon/jobs.py`); a phase is a hard barrier - every job
in it runs concurrently and the next phase doesn't start until all of them finish.

| Phase | Jobs | Produces |
|---|---|---|
| 0 | `subfinder`, `amass`, `whois` | Subdomain, IP, Domain |
| 1 | `dnsx`, `puredns`, `subdomain_takeover` | IP, DNSRecord, Subdomain, ExternalDomain |
| 2 | `naabu` | IP, Port, Service |
| 3 | `httpx` | BaseURL, Endpoint, Technology, Certificate, Header |
| 4 | `katana`, `ffuf`, `kiterunner`, `graphql-cop`, `gau`, `paramspider`, `steel_crawl` | BaseURL, Endpoint, Parameter |
| 5 | `jsluice` | Endpoint, Secret |
| 6 | `arjun` | Parameter |

`jsluice` runs after the phase-4 crawlers on purpose: it consumes the `.js`/`.mjs` Endpoints
that `katana`/`gau` just discovered, so it needs its own phase to see them.
In `exact` scope mode, phase 0 and 1 shrink to just `whois` and `subdomain_takeover` - the rest
of the pipeline is unaffected.
