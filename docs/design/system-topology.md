# polymerhus — System Topology

*Top-down architecture set, document 1 of 3 · Explanation + Reference*

## Purpose and how to read this

`polymerhus` is an autonomous vulnerability-discovery harness; its iteration-1 substrate is a
recon pipeline that runs on **four containers** plus a browser-based viewer. This document maps the
*macro topology*: the running pieces, where they sit on the network, and the wire-and-protocol by
which each pair communicates. It goes exactly one level deep — components and the links between
them. Anything *inside* a component (the LangGraph pipeline, the Neo4j entity model, the Kali
tool-call machinery) is deferred to the two deeper documents:

- **Technical architecture** — inside each macro component.
- **Technological architecture** — frameworks and framework-artifacts of the agent and frontend.

The code is the source of truth here; identifiers and ports below are quoted from
`docker-compose.yml`, `docker-compose.dev.yml`, and the client/server modules, not from memory.

## Topology at a glance

Four services share a single Docker bridge network, `polymerhus-net` (`docker-compose.yml`). The
**agent** is the hub: it is the only component on the data plane — it dials all three backends
(Neo4j, Postgres, Kali) and is the only public control surface. The **frontend SPA** runs outside
compose and reaches the agent over HTTP. Two classes of traffic leave the host entirely: the agentic
crawler drives an **external Steel cloud browser** over CDP, and the agent calls **external LLM
providers** (with optional trace export to Langfuse).

```mermaid
flowchart LR
    subgraph host["Developer host"]
        spa["frontend SPA<br/>Vite dev server :5173<br/>(react-force-graph-2d)"]
        subgraph net["Docker network: polymerhus-net (bridge)"]
            agent["agent<br/>polymerhus-agent:latest<br/>FastAPI/uvicorn · host :8080"]
            pg[("postgres<br/>pgvector/pgvector:pg16<br/>host :5432")]
            neo[("neo4j<br/>neo4j:5.26-community<br/>host :7474 / :7687")]
            kali["kali<br/>redamon-kali-sandbox:latest<br/>FastMCP · host :8000"]
        end
    end
    subgraph ext["External / internet"]
        steel["Steel cloud browser<br/>connect.steel.dev"]
        llm["LLM providers<br/>openai / openrouter / swissai"]
        lf["Langfuse<br/>(optional)"]
    end

    spa -->|"HTTP/REST+JSON<br/>proxy /projects,/runs → :8080"| agent
    dev["curl / Python client"] -->|"HTTP/REST+JSON :8080"| agent
    agent -->|"Bolt :7687"| neo
    agent -->|"PostgreSQL wire :5432<br/>(psycopg)"| pg
    agent -->|"MCP / streamable-http<br/>http://kali:8000/mcp"| kali
    agent -.->|"CDP over WSS"| steel
    agent -.->|"HTTPS (OpenAI-compat)"| llm
    agent -.->|"OTLP/HTTP (optional)"| lf
```

*Solid edges are in-network or host-local links; dashed edges leave the host to the public internet.*

## Components

Each compose **service name is the container identifier** used below (e.g. `agent`, `neo4j`).

### `agent` — orchestrator and control plane
`polymerhus-agent:latest`, built from the `redamon-agent:latest` base (`agent/Dockerfile`). Runs a
FastAPI app under `uvicorn` on `:8080` (published to host). It hosts the recon pipeline **and** the
REST API that is the only way to create projects, configure targets, launch runs, and read the
mapped attack surface (`README.md` "Interfaces"). It is the sole component that talks to the three
backends. In dev, source is bind-mounted with `uvicorn --reload` (`docker-compose.dev.yml`).

### `postgres` — registry, settings, and document corpus
`pgvector/pgvector:pg16`, published `:5432`, backed by the `pg-data` volume. Holds the application
domain model (projects, settings, the run/job registry) and a pgvector document corpus. It also
stores the LangGraph checkpoint tables. `db/postgres/init.sql` runs on first init.

### `neo4j` — attack-surface graph
`neo4j:5.26-community`, publishing `:7474` (HTTP browser) and `:7687` (Bolt), backed by `neo4j-data`.
Stores the discovered attack surface as a labelled property graph. Layer-0 constraints are applied
by the agent at startup (`db/neo4j/schema.py`).

### `kali` — tool execution sandbox
`redamon-kali-sandbox:latest`, publishing `:8000`. Runs a single-tool FastMCP server
(`kali/mcp_server.py`, `FastMCP("kali-exec")`) exposing `execute_command` over native HTTP at `/mcp`.
It carries the ProjectDiscovery recon suite; `kali/postrun.sh` gap-fills extra tools into the
persisted `kali-tools` volume on first `up`. Volumes: `kali-tools`, `resolvers`, `work` (per-session
workdirs).

### `frontend` — read-only viewer SPA
Not a compose service: a Vite/React single-page app (`frontend/`), served by the Vite dev server on
`:5173` (`npm run dev`) or as a static bundle. React 19, `react-router-dom` 7, and
`react-force-graph-2d` (`frontend/package.json`). It is a **read-only** viewer — it renders the
projects list, the live attack-surface graph, and running-run status, and has no launch/settings
path, so a run always starts through the agent API.

### External egress targets
The **Steel cloud browser** (`connect.steel.dev`) is the authenticated remote browser the agentic
crawler drives per crawl session (`agent/recon/crawl/steel_provider.py`). The **LLM providers**
(`agent/app/llm/providers.py`) serve the agent's reasoning roles. **Langfuse** optionally receives
traces. All three are reached over the public internet, not `polymerhus-net`.

| Container id | Image | Host ports | In-network address | Volumes |
|---|---|---|---|---|
| `agent` | `polymerhus-agent:latest` (base `redamon-agent:latest`) | `8080` | `agent:8080` | (bind-mounts in dev) |
| `postgres` | `pgvector/pgvector:pg16` | `5432` | `postgres:5432` | `pg-data` |
| `neo4j` | `neo4j:5.26-community` | `7474`, `7687` | `neo4j:7687` (Bolt) | `neo4j-data` |
| `kali` | `redamon-kali-sandbox:latest` | `8000` | `kali:8000/mcp` | `kali-tools`, `resolvers`, `work` |
| `frontend` | Vite/React (host, not compose) | `5173` | — | — |

## Network configuration

All four services attach to `polymerhus-net`, a single `bridge` network (`docker-compose.yml`), and
address each other by **service name** — the agent's environment defaults wire in-network URLs so a
clean clone works without a `.env`: `NEO4J_URI=bolt://neo4j:7687`,
`POSTGRES_DSN=postgresql://polymerhus:polymerhus@postgres:5432/polymerhus`,
`KALI_MCP_URL=http://kali:8000/mcp`. Every service also publishes its port to the host, so an
operator can reach Postgres, the Neo4j browser, the Kali MCP endpoint, and the agent API directly for
inspection; in normal operation only the agent's `:8080` and the SPA's `:5173` matter.

The `kali` service adds an `extra_hosts` entry, `app.online.orders.com:host-gateway`, routing that
lab hostname to the Docker host gateway — where an nginx front-end reverse-proxies to the correct
backend. This exists so recon tools inside the Kali container can resolve and reach the local target
app as if it were on the internet. The agent's `depends_on` gates startup on Postgres and Neo4j
health and on Kali having started (`docker-compose.yml`).

## Communication protocols and interfaces

The agent sits on the client side of every internal link; each backend runs the matching server.

| Link | Client module | Server | Transport / address | Payload |
|---|---|---|---|---|
| agent → neo4j | `agent/app/clients/neo4j_client.py` (`GraphDatabase.driver`) | neo4j server | **Bolt** `bolt://neo4j:7687` | Cypher + params |
| agent → postgres | `agent/app/clients/pg.py` (`psycopg`; `AsyncPostgresSaver`) | postgres server | **PostgreSQL wire** `:5432` | SQL / JSONB; LangGraph checkpoints |
| agent → kali | `agent/app/clients/kali_mcp.py` (`MultiServerMCPClient`, transport `streamable_http`) | `kali/mcp_server.py` (`FastMCP`) | **MCP over streamable-HTTP** `http://kali:8000/mcp` | `execute_command` tool calls |
| SPA / curl → agent | `frontend/src/api/client.ts` (`fetch`) / any HTTP tool | `agent/app/routes.py` (FastAPI) | **HTTP/REST + JSON** `:8080` | projects, settings, runs, graph |
| agent → Steel | `agent/recon/crawl/steel_provider.py` (Playwright) | Steel cloud | **CDP over WSS** `connect.steel.dev` | browser automation |
| agent → LLM | `agent/app/llm/providers.py` (`ChatOpenAI`) | provider | **HTTPS** (OpenAI-compatible) | chat/tool-calling |
| agent → Langfuse | `agent/app/observability/langfuse_tracing.py` | Langfuse | **OTLP/HTTP** (optional) | trace spans |

The three backend links form the data plane and are exclusive to the agent — no other component
reads or writes Postgres, Neo4j, or Kali. The SPA touches only the agent's REST surface, and only its
read endpoints: `getProjects()` → `/projects`, `getGraph()` → `/projects/{id}/graph`,
`getRunningRuns()` → `/runs?status=running` (`frontend/src/api/client.ts`).

```mermaid
flowchart TB
    subgraph agentbox["agent container — the only data-plane client"]
        rest["FastAPI REST (routes.py) :8080"]
        pgc["pg.py (psycopg)"]
        neoc["neo4j_client.py (Bolt driver)"]
        kalic["kali_mcp.py (MultiServerMCPClient)"]
    end
    rest --- pgc
    rest --- neoc
    pgc -->|"PostgreSQL :5432"| PG[("postgres")]
    neoc -->|"Bolt :7687"| NEO[("neo4j")]
    kalic -->|"MCP streamable-http :8000/mcp"| KALI["kali FastMCP execute_command"]
    SPA["frontend SPA"] -->|"HTTP/REST :8080 (read-only)"| rest
```

## Frontend SPA

The viewer is a **client-side-rendered single-page application**. Its dev server proxies the two API
prefixes it needs to the agent — `vite.config.ts` forwards `/projects` and `/runs` to
`AGENT_PROXY_TARGET` (default `http://localhost:8080`), so the SPA can fetch with relative paths
(`BASE=""` in `api/client.ts`) and still hit the agent rather than the SPA's own index. Client routes
(`/`, `/p/:id`, `/p/:id/runs`) do not collide with those API prefixes. Because it is read-only, the
SPA never mutates state — every run is launched through the agent REST API. How the SPA renders (its
router, the force-graph canvas) is covered in the technological-architecture document.

## Request lifecycle — launching a run across the topology

A launch shows how control crosses component boundaries. The agent accepts the request, writes the
run row synchronously, then returns immediately and drives the pipeline in the background; the
pipeline is what dials Kali and Neo4j (`agent/app/routes.py`, `agent/recon/pipeline.py`).

```mermaid
sequenceDiagram
    actor Op as curl / SPA
    participant A as agent :8080 (FastAPI)
    participant P as postgres :5432
    participant K as kali :8000/mcp
    participant N as neo4j :7687

    Op->>A: POST /projects/{id}/recon (HTTP/JSON)
    A->>P: create_run (PostgreSQL)
    A-->>Op: 200 {run_id} (returns before pipeline runs)
    note over A: pipeline runs async (background task)
    loop each phase / job / pod
        A->>K: execute_command (MCP streamable-http)
        K-->>A: {stdout,stderr,returncode}
        A->>N: MERGE assets (Bolt)
        A->>P: upsert_job status (PostgreSQL)
    end
    Op->>A: GET /projects/{id}/recon/{run_id} (poll)
    A->>P: read run/job status
    Op->>A: GET /projects/{id}/graph
    A->>N: read attack surface (Bolt)
    A-->>Op: {nodes, links}
```

The intra-agent detail behind "pipeline runs async" — phases, pods, the LangGraph graphs — is the
subject of the technical and technological documents.

## Pointers

- **Inside the components** — Neo4j entity model, Postgres domain model, the Kali tool-call
  mechanism end-to-end, and the agent's skill/steering/BFF internals → *Technical architecture*.
- **Frameworks and artifacts** — LangGraph configuration, the artifact taxonomy, observability, the
  LLM client, and the agentic crawling stack → *Technological architecture*.
