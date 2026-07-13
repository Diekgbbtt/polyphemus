# Platform Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the reconnaissance platform substrate — a `docker compose` stack of four services (agent, kali, neo4j, postgres/pgvector) with their schemas initialized — that both the recon pipeline and the ingestion subsystem will sit on.

**Architecture:** Reuse two heavy pre-built images to avoid rebuild/pull bottlenecks. **Kali** = `redamon-kali-sandbox:latest` (already ships the ProjectDiscovery suite + arjun/paramspider/masscan/nmap) with its entrypoint **overridden** to run a small post-run gap-fill script (`massdns`/`puredns`/`whois` + `graphql-cop` + `kiterunner`, persisted in a volume) and then our single `fastmcp execute_command` server. **Agent** = `FROM redamon-agent:latest` (inherits python 3.11, langgraph, `langchain-mcp-adapters`, fastapi, neo4j/psycopg, and the pre-baked `e5-large-v2` + `bge-reranker-base` models) with our thin FastAPI health skeleton on top. **Postgres/pgvector** holds the app schema + `doc_chunks` corpus + LangGraph checkpoint tables; **Neo4j** (`5.26-community`) holds the Layer-0 graph (`user_id` dropped from constraints, security/CVE nodes removed, `Observation` added). Recon pods, the ingestion pipeline, and the Steel crawling agent are **out of scope** here — this plan delivers only the substrate.

**Tech Stack:** Docker Compose, `redamon-kali-sandbox:latest`, `redamon-agent:latest` (python 3.11), `fastmcp` (server), `langchain-mcp-adapters` (client), `neo4j:5.26-community`, `pgvector/pgvector:pg16`, FastAPI, `AsyncPostgresSaver`, pytest.

## Global Constraints

- **Reuse existing images; do not rebuild from scratch.** `redamon-agent:latest` and `redamon-kali-sandbox:latest` must exist locally (`docker images`). No new base pulls except `pgvector/pgvector:pg16` and `neo4j:5.26-community`.
- **Single project / single user:** `project_id` only; `admin:admin`; **no** `user_id` in any constraint.
- **No security/CVE graph nodes:** exclude `CVE`, `MitreData`, `Capec`, `Vulnerability`, `Exploit`, `Github*`, `Trufflehog*`, `JsReconFinding`, OTX, `AttackChain`/`Chain*`, `KBChunk`, `UserInput`.
- **Neo4j writes are parameterized `MERGE` only.** Identity keys per `recon-mvp-design §10.3`, each with `project_id` appended.
- **Embedding dimension:** `EMBED_DIM=1024` (local `intfloat/e5-large-v2`, pre-baked in the agent base). `doc_chunks.embedding` = `vector(1024)`.
- **MCP:** server = one fastmcp tool `execute_command` → `{stdout, stderr, returncode, duration_ms}`, native HTTP at `/mcp`, per-session workdir `/work/{session_id}`, ANSI-stripped, **no scope enforcement** (MVP). Client = `langchain-mcp-adapters` `MultiServerMCPClient`, `streamable_http`.
- **Checkpointer:** `AsyncPostgresSaver`, `.setup()` once at startup, `thread_id=run_id`, `checkpoint_ns=phase/job`, `LANGGRAPH_STRICT_MSGPACK=true`. **Graph is embedded in the custom FastAPI app** (not LangGraph Server / `langgraph dev`).
- **Idempotent schema init:** all constraints/indexes `IF NOT EXISTS`; all SQL DDL `IF NOT EXISTS`; the Kali post-run script is idempotent (check-then-install into a persisted volume).
- **Dev ergonomics:** a `docker-compose.dev.yml` overlay bind-mounts source so agent hot-reloads (`uvicorn --reload`) and kali reloads on `docker restart`.

---

## File Structure

```
polymerhus/
├── docker-compose.yml            # 4 services + volumes + network
├── docker-compose.dev.yml        # dev overlay (bind-mounts + agent --reload)
├── .env.example                  # env matrix
├── requirements-dev.txt          # pytest, psycopg, neo4j, fastmcp, httpx (host test deps)
├── db/
│   ├── __init__.py
│   ├── postgres/
│   │   └── init.sql              # extension + app schema + doc_chunks + HNSW
│   └── neo4j/
│       ├── __init__.py
│       ├── schema.py             # adapted CONSTRAINTS + INDEXES
│       └── init_schema.py        # idempotent runner
├── kali/
│   ├── mcp_server.py             # fastmcp execute_command (bind-mounted into the image)
│   └── postrun.sh                # gap-fill (massdns/puredns/whois/graphql-cop/kiterunner) + fastmcp
├── agent/
│   ├── __init__.py
│   ├── Dockerfile                # FROM redamon-agent:latest
│   └── app/
│       ├── __init__.py
│       ├── config.py
│       ├── clients/
│       │   ├── __init__.py
│       │   ├── pg.py             # check + AsyncPostgresSaver.setup
│       │   ├── neo4j_client.py   # driver + schema init + MERGE helper
│       │   └── kali_mcp.py       # langchain-mcp-adapters health call
│       └── main.py               # FastAPI + GET /health
└── tests/
    ├── conftest.py
    ├── test_compose_config.py
    ├── test_postgres_schema.py
    ├── test_neo4j_schema.py
    ├── test_kali_mcp.py
    ├── test_agent_health.py
    └── test_stack_smoke.py
```

---

## Task 1: Repo scaffold, compose base, and test harness

**Files:**
- Create: `docker-compose.yml`, `.env.example`, `requirements-dev.txt`, `tests/conftest.py`, `tests/test_compose_config.py`

**Interfaces:**
- Produces: compose with `polymerhus-net` and volumes `neo4j-data`, `pg-data`, `kali-tools`, `resolvers`, `work`; `tests.conftest.wait_for(fn, timeout, interval)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compose_config.py
import subprocess

def test_compose_config_is_valid():
    result = subprocess.run(["docker", "compose", "config"], capture_output=True, text=True, cwd=".")
    assert result.returncode == 0, result.stderr
    assert "polymerhus-net" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_compose_config.py -v`
Expected: FAIL — no `docker-compose.yml`.

- [ ] **Step 3: Create the compose base**

```yaml
# docker-compose.yml
name: polymerhus

networks:
  polymerhus-net:
    driver: bridge

volumes:
  neo4j-data:
  pg-data:
  kali-tools:      # persists massdns/puredns/kr so recreation never recompiles
  resolvers:
  work:
```

- [ ] **Step 4: Create `.env.example`**

```dotenv
# .env.example — copy to .env
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=polymerhus
POSTGRES_DSN=postgresql://polymerhus:polymerhus@postgres:5432/polymerhus
KALI_MCP_URL=http://kali:8000/mcp
# fan-out / pod bounds (declared now; unused by the stack layer)
MAX_PODS=8
MAX_POD_ITERS=3
EXEC_TIMEOUT_S=300
OUTPUT_BYTE_CAP=1048576
# embeddings — local models are pre-baked into the agent base image
EMBED_MODEL=intfloat/e5-large-v2
EMBED_DIM=1024
# Steel crawling agent (ingestion iteration; declared now for forward-compat)
STEEL_API_KEY=
STEEL_BASE_URL=
# single-project tenancy
PROJECT_ID=default
LANGGRAPH_STRICT_MSGPACK=true
```

- [ ] **Step 5: Create dev requirements and conftest**

```text
# requirements-dev.txt
pytest==8.3.4
psycopg[binary]==3.2.3
neo4j==5.27.0
fastmcp==2.11.0
httpx==0.28.1
```

```python
# tests/conftest.py
import time

def wait_for(fn, timeout=120, interval=2):
    """Poll fn() until truthy or non-raising; re-raise last error on timeout."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = fn()
            if r:
                return r
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(interval)
    if last:
        raise last
    raise TimeoutError(f"wait_for timed out after {timeout}s")
```

- [ ] **Step 6: Install dev deps and run test to verify it passes**

Run: `pip install -r requirements-dev.txt && python -m pytest tests/test_compose_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml .env.example requirements-dev.txt tests/conftest.py tests/test_compose_config.py
git commit -m "chore: scaffold platform stack compose base + test harness"
```

---

## Task 2: Postgres/pgvector service + app schema

**Files:**
- Modify: `docker-compose.yml` (add `postgres`)
- Create: `db/__init__.py`, `db/postgres/init.sql`
- Test: `tests/test_postgres_schema.py`

**Interfaces:**
- Produces: `postgres` at `postgresql://polymerhus:polymerhus@localhost:5432/polymerhus`; tables `projects`, `settings`, `recon_runs`, `recon_jobs`, `ingest_runs`, `doc_chunks`; `vector` extension; `doc_chunks_hnsw` index.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_postgres_schema.py
import subprocess, psycopg
from tests.conftest import wait_for

DSN = "postgresql://polymerhus:polymerhus@localhost:5432/polymerhus"

def test_postgres_schema():
    subprocess.run(["docker", "compose", "up", "-d", "postgres"], check=True)
    wait_for(lambda: psycopg.connect(DSN, connect_timeout=3).close() or True, timeout=120)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname='vector'")
        assert cur.fetchone() is not None
        for t in ("projects", "settings", "recon_runs", "recon_jobs", "ingest_runs", "doc_chunks"):
            cur.execute("SELECT to_regclass(%s)", (f"public.{t}",))
            assert cur.fetchone()[0] == t, f"missing {t}"
        cur.execute("SELECT indexname FROM pg_indexes WHERE indexname='doc_chunks_hnsw'")
        assert cur.fetchone() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_postgres_schema.py -v`
Expected: FAIL — no `postgres` service.

- [ ] **Step 3: Add the postgres service to compose**

```yaml
# docker-compose.yml — under services:
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: polymerhus
      POSTGRES_PASSWORD: polymerhus
      POSTGRES_DB: polymerhus
    ports: ["5432:5432"]
    volumes:
      - pg-data:/var/lib/postgresql/data
      - ./db/postgres/init.sql:/docker-entrypoint-initdb.d/10-init.sql:ro
    networks: [polymerhus-net]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U polymerhus -d polymerhus"]
      interval: 5s
      timeout: 3s
      retries: 20
```

- [ ] **Step 4: Create the init SQL and package marker**

```bash
touch db/__init__.py
```

```sql
-- db/postgres/init.sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS projects (
    project_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS settings (
    project_id  TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    recon       JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS recon_runs (
    run_id        TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    status        TEXT NOT NULL,
    current_phase INT,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS recon_jobs (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    phase       INT,
    job         TEXT NOT NULL,
    status      TEXT NOT NULL,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    stats       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS ingest_runs (
    ingest_id   TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    status      TEXT NOT NULL,
    per_source  JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieval   TEXT NOT NULL DEFAULT 'deferred',
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS doc_chunks (
    id          BIGSERIAL PRIMARY KEY,
    doc_ref     TEXT NOT NULL,
    source_type TEXT NOT NULL,
    anchor      JSONB NOT NULL,
    chunk_text  TEXT NOT NULL,
    ordinal     INT NOT NULL,
    embedding   vector(1024) NOT NULL,
    provenance  JSONB NOT NULL,
    project_id  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS doc_chunks_hnsw    ON doc_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS doc_chunks_doc_ref ON doc_chunks (doc_ref);
CREATE INDEX IF NOT EXISTS doc_chunks_anchor  ON doc_chunks USING gin (anchor);
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_postgres_schema.py -v`
Expected: PASS. (If a stale volume predates `init.sql`, `docker compose down -v` first.)

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml db/__init__.py db/postgres/init.sql tests/test_postgres_schema.py
git commit -m "feat: postgres/pgvector service + app schema + doc_chunks corpus"
```

---

## Task 3: Neo4j service + adapted Layer-0 schema

**Files:**
- Modify: `docker-compose.yml` (add `neo4j`)
- Create: `db/neo4j/__init__.py`, `db/neo4j/schema.py`, `db/neo4j/init_schema.py`
- Test: `tests/test_neo4j_schema.py`

**Interfaces:**
- Produces: `db.neo4j.schema.CONSTRAINTS`/`INDEXES`; `db.neo4j.init_schema.init_schema(session)`; `neo4j` at `bolt://localhost:7687`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_neo4j_schema.py
import subprocess
from neo4j import GraphDatabase
from tests.conftest import wait_for
from db.neo4j.init_schema import init_schema

URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")

def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d

def test_neo4j_constraints_applied():
    subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=True)
    driver = wait_for(_driver, timeout=120)
    with driver.session() as s:
        init_schema(s)
        names = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name")}
    assert "endpoint_unique" in names
    assert "observation_unique" in names
    assert "cve_unique" not in names
    assert "vulnerability_unique" not in names
    driver.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_neo4j_schema.py -v`
Expected: FAIL — no `neo4j` service / `db.neo4j` module.

- [ ] **Step 3: Add the neo4j service to compose**

```yaml
# docker-compose.yml — under services:
  neo4j:
    image: neo4j:5.26-community
    environment:
      NEO4J_AUTH: neo4j/polymerhus
    ports: ["7474:7474", "7687:7687"]
    volumes: [neo4j-data:/data]
    networks: [polymerhus-net]
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 || exit 1"]
      interval: 5s
      timeout: 3s
      retries: 30
```

- [ ] **Step 4: Create the adapted schema**

```python
# db/neo4j/schema.py
"""Layer-0 schema for polymerhus.
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
```

- [ ] **Step 5: Create the runner and package markers**

```python
# db/neo4j/init_schema.py
from db.neo4j.schema import CONSTRAINTS, INDEXES

def init_schema(session):
    """Apply all constraints and indexes. Idempotent (every statement is IF NOT EXISTS)."""
    for stmt in CONSTRAINTS + INDEXES:
        session.run(stmt)
```

```bash
touch db/neo4j/__init__.py
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_neo4j_schema.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml db/neo4j/ tests/test_neo4j_schema.py
git commit -m "feat: neo4j 5.26 service + adapted Layer-0 constraints (no user_id/CVE, +Observation)"
```

---

## Task 4: Kali service (image reuse) + post-run gap-fill + fastmcp `execute_command`

**Files:**
- Create: `kali/mcp_server.py`, `kali/postrun.sh`
- Modify: `docker-compose.yml` (add `kali`)
- Test: `tests/test_kali_mcp.py`

**Interfaces:**
- Consumes: `redamon-kali-sandbox:latest`; volumes `work`, `kali-tools`, `resolvers`.
- Produces: `kali` serving `execute_command(command, session_id, timeout_s)` at `http://localhost:8000/mcp`; gap tools `puredns`, `massdns`, `kr`, `graphql-cop`, `whois` resolvable on `PATH`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kali_mcp.py
import asyncio, subprocess
from fastmcp import Client
from tests.conftest import wait_for

MCP_URL = "http://localhost:8000/mcp"

async def _call(command, session_id):
    async with Client(MCP_URL) as c:
        res = await c.call_tool("execute_command", {"command": command, "session_id": session_id})
        return res.data

def test_execute_command_roundtrip_isolation_and_tools():
    subprocess.run(["docker", "compose", "up", "-d", "kali"], check=True)
    # first up runs postrun (massdns compile, kr fetch) — allow generous time
    wait_for(lambda: asyncio.run(_call("echo hi", "smoke")), timeout=420)
    out = asyncio.run(_call("echo hello", "run1-pod1"))
    assert out["returncode"] == 0 and out["stdout"].strip() == "hello"
    # per-session workdir isolation
    asyncio.run(_call("echo data > f.txt", "run1-pod1"))
    assert asyncio.run(_call("cat f.txt", "run1-pod2"))["returncode"] != 0
    # gap tools installed and on PATH
    tools = asyncio.run(_call("command -v puredns massdns kr graphql-cop whois", "toolcheck"))
    assert tools["returncode"] == 0, tools["stdout"] + tools["stderr"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_kali_mcp.py -v`
Expected: FAIL — no `kali` service.

- [ ] **Step 3: Create the fastmcp server (bind-mounted into the reused image)**

```python
# kali/mcp_server.py
"""Single-tool fastmcp execution server for the reused Kali image.
Exposes execute_command over native HTTP at /mcp; per-session workdir isolation;
ANSI-stripped output; PATH primed for the ProjectDiscovery + gap tools.
No scope enforcement (MVP)."""
import os, re, subprocess, time
from fastmcp import FastMCP

# Prime PATH so subprocesses resolve go tools, the venv (arjun/paramspider/graphql-cop),
# and the persisted gap-fill volume (massdns/puredns/kr). Go httpx already wins via
# the base image's /opt/venv/bin symlink.
os.environ["PATH"] = ":".join([
    "/opt/localbin", "/root/go/bin", "/opt/venv/bin", "/usr/local/go/bin", os.environ.get("PATH", ""),
])

mcp = FastMCP("kali-exec")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

@mcp.tool()
def execute_command(command: str, session_id: str, timeout_s: int = 300) -> dict:
    """Run a shell command in /work/{session_id} and return
    {stdout, stderr, returncode, duration_ms}. ANSI stripped."""
    workdir = f"/work/{session_id}"
    os.makedirs(workdir, exist_ok=True)
    start = time.time()
    try:
        proc = subprocess.run(command, shell=True, cwd=workdir,
                              capture_output=True, text=True, timeout=timeout_s)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, (e.stdout or ""), f"timeout after {timeout_s}s"
    return {"stdout": _ANSI.sub("", out), "stderr": _ANSI.sub("", err),
            "returncode": rc, "duration_ms": int((time.time() - start) * 1000)}

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
```

- [ ] **Step 4: Create the idempotent post-run gap-fill script**

```bash
# kali/postrun.sh
#!/usr/bin/env bash
# Idempotent gap-fill for the reused redamon-kali-sandbox image. Installs the
# recon tools it lacks into a persisted volume (/opt/localbin) + the venv, so
# recreation never recompiles. Then execs nothing — caller runs the MCP server.
set -e
export PATH="/opt/localbin:/root/go/bin:/opt/venv/bin:/usr/local/go/bin:$PATH"
mkdir -p /opt/localbin /resolvers

# fastmcp for the exec server (into the existing venv)
/opt/venv/bin/pip show fastmcp >/dev/null 2>&1 || /opt/venv/bin/pip install --no-cache-dir fastmcp

# whois CLI (python-whois lib already present; add the binary too)
command -v whois >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq --no-install-recommends whois; }

# graphql-cop (Python CLI; replaces the dolevf/graphql-cop docker image)
/opt/venv/bin/pip show graphql-cop >/dev/null 2>&1 || /opt/venv/bin/pip install --no-cache-dir graphql-cop

# massdns (puredns dependency)
if [ ! -x /opt/localbin/massdns ]; then
  rm -rf /tmp/massdns && git clone --depth 1 https://github.com/blechschmidt/massdns.git /tmp/massdns
  make -C /tmp/massdns && cp /tmp/massdns/bin/massdns /opt/localbin/
fi

# puredns
[ -x /opt/localbin/puredns ] || GOBIN=/opt/localbin go install github.com/d3mondev/puredns/v2@latest

# kiterunner (kr binary + small routes wordlist)
if [ ! -x /opt/localbin/kr ]; then
  curl -sL https://github.com/assetnote/kiterunner/releases/download/v1.0.2/kiterunner_1.0.2_linux_amd64.tar.gz \
    | tar xz -C /opt/localbin kr
fi
[ -f /opt/localbin/routes-small.kite ] || curl -sL https://wordlists-cdn.assetnote.io/data/kiterunner/routes-small.kite.tar.gz \
  | tar xz -C /opt/localbin

# resolvers for puredns
[ -f /resolvers/resolvers.txt ] || curl -sL https://raw.githubusercontent.com/trickest/resolvers/main/resolvers.txt -o /resolvers/resolvers.txt

echo "[postrun] gap-fill complete"
```

- [ ] **Step 5: Add the kali service to compose (entrypoint overridden)**

```yaml
# docker-compose.yml — under services:
  kali:
    image: redamon-kali-sandbox:latest
    entrypoint: ["bash", "-lc", "/opt/postrun.sh && /opt/venv/bin/python /opt/mcp_server.py"]
    ports: ["8000:8000"]
    volumes:
      - ./kali/mcp_server.py:/opt/mcp_server.py:ro
      - ./kali/postrun.sh:/opt/postrun.sh:ro
      - kali-tools:/opt/localbin
      - resolvers:/resolvers
      - work:/work
    networks: [polymerhus-net]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_kali_mcp.py -v`
Expected: PASS. (First run compiles massdns + fetches kr — up to a few minutes; subsequent runs reuse the `kali-tools` volume.)

- [ ] **Step 7: Commit**

```bash
git add kali/ docker-compose.yml tests/test_kali_mcp.py
git commit -m "feat: kali service (image reuse) + post-run gap-fill + fastmcp execute_command"
```

---

## Task 5: Agent service (`FROM redamon-agent`) + FastAPI health skeleton

**Files:**
- Create: `agent/__init__.py`, `agent/Dockerfile`, `agent/app/__init__.py`, `agent/app/config.py`, `agent/app/clients/__init__.py`, `agent/app/clients/pg.py`, `agent/app/clients/neo4j_client.py`, `agent/app/clients/kali_mcp.py`, `agent/app/main.py`
- Modify: `docker-compose.yml` (add `agent`)
- Test: `tests/test_agent_health.py`

**Interfaces:**
- Consumes: `redamon-agent:latest` (provides langgraph, `langchain-mcp-adapters`, fastapi/uvicorn, neo4j, `langgraph-checkpoint-postgres`, psycopg); the schemas from Tasks 2–4; the MCP tool from Task 4.
- Produces: `agent` exposing `GET /health` → `{"status": str, "checks": {"postgres": bool, "neo4j": bool, "kali_mcp": bool}}`; `agent.app.clients.pg.ensure_checkpoint_tables()` (async); `agent.app.clients.neo4j_client.ensure_schema()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_health.py
import subprocess, httpx, psycopg
from tests.conftest import wait_for

DSN = "postgresql://polymerhus:polymerhus@localhost:5432/polymerhus"

def _health():
    r = httpx.get("http://localhost:8080/health", timeout=3)
    r.raise_for_status()
    return r.json()

def test_agent_health_all_backends_ok():
    subprocess.run(["docker", "compose", "up", "-d",
                    "postgres", "neo4j", "kali", "agent"], check=True)
    body = wait_for(lambda: _health() if _health()["status"] == "ok" else None, timeout=420)
    assert body["checks"] == {"postgres": True, "neo4j": True, "kali_mcp": True}
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.checkpoints')")
        assert cur.fetchone()[0] == "checkpoints"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_health.py -v`
Expected: FAIL — no `agent` service.

- [ ] **Step 3: Create the config module + package markers**

```bash
touch agent/__init__.py agent/app/__init__.py agent/app/clients/__init__.py
```

```python
# agent/app/config.py
import os

class Config:
    NEO4J_URI = os.environ["NEO4J_URI"]
    NEO4J_USER = os.environ["NEO4J_USER"]
    NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
    POSTGRES_DSN = os.environ["POSTGRES_DSN"]
    KALI_MCP_URL = os.environ["KALI_MCP_URL"]
    PROJECT_ID = os.environ.get("PROJECT_ID", "default")

config = Config()
```

- [ ] **Step 4: Create the Postgres client (check + async checkpoint setup)**

```python
# agent/app/clients/pg.py
import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from agent.app.config import config

def check() -> bool:
    with psycopg.connect(config.POSTGRES_DSN, connect_timeout=3) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        return cur.fetchone()[0] == 1

async def ensure_checkpoint_tables() -> None:
    """Create LangGraph checkpoint tables (idempotent)."""
    async with AsyncPostgresSaver.from_conn_string(config.POSTGRES_DSN) as saver:
        await saver.setup()
```

- [ ] **Step 5: Create the Neo4j client (driver + schema init + MERGE helper)**

```python
# agent/app/clients/neo4j_client.py
from neo4j import GraphDatabase
from agent.app.config import config
from db.neo4j.init_schema import init_schema

_driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))

def check() -> bool:
    _driver.verify_connectivity()
    return True

def ensure_schema() -> None:
    with _driver.session() as s:
        init_schema(s)

def merge(cypher: str, params: dict) -> None:
    """Parameterized MERGE helper (the only Layer-0 write path)."""
    with _driver.session() as s:
        s.run(cypher, **params)
```

- [ ] **Step 6: Create the Kali MCP client (langchain-mcp-adapters)**

```python
# agent/app/clients/kali_mcp.py
from langchain_mcp_adapters.client import MultiServerMCPClient
from agent.app.config import config

async def check() -> bool:
    client = MultiServerMCPClient(
        {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}}
    )
    tools = await client.get_tools()
    exec_tool = next(t for t in tools if t.name == "execute_command")
    result = await exec_tool.ainvoke({"command": "echo ok", "session_id": "health"})
    return "ok" in str(result)
```

- [ ] **Step 7: Create the FastAPI app**

```python
# agent/app/main.py
from fastapi import FastAPI
from agent.app.clients import pg, neo4j_client, kali_mcp

app = FastAPI(title="polymerhus-agent")

@app.on_event("startup")
async def _startup():
    await pg.ensure_checkpoint_tables()
    neo4j_client.ensure_schema()

@app.get("/health")
async def health():
    checks = {"postgres": False, "neo4j": False, "kali_mcp": False}
    try:
        checks["postgres"] = pg.check()
    except Exception:  # noqa: BLE001
        pass
    try:
        checks["neo4j"] = neo4j_client.check()
    except Exception:  # noqa: BLE001
        pass
    try:
        checks["kali_mcp"] = await kali_mcp.check()
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks}
```

- [ ] **Step 8: Create the Dockerfile (reuse the agent base image)**

```dockerfile
# agent/Dockerfile
FROM redamon-agent:latest
WORKDIR /srv
# Our code overlays the base; /app stays importable for inherited packages
# (knowledge_base, graph_db) used by later iterations.
COPY agent/ /srv/agent/
COPY db/ /srv/db/
ENV PYTHONPATH="/srv:/app"
EXPOSE 8080
CMD ["uvicorn", "agent.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 9: Add the agent service to compose**

```yaml
# docker-compose.yml — under services:
  agent:
    build: { context: ., dockerfile: agent/Dockerfile }
    image: polymerhus-agent:latest
    env_file: [.env]
    ports: ["8080:8080"]
    depends_on:
      postgres: { condition: service_healthy }
      neo4j: { condition: service_healthy }
      kali: { condition: service_started }
    networks: [polymerhus-net]
```

- [ ] **Step 10: Create `.env` and run the test**

Run: `cp .env.example .env && python -m pytest tests/test_agent_health.py -v`
Expected: PASS — `status: ok`, all three checks `True`, `checkpoints` table present.

- [ ] **Step 11: Commit**

```bash
git add agent/ docker-compose.yml tests/test_agent_health.py
git commit -m "feat: agent service (FROM redamon-agent) + FastAPI /health + clients + checkpoint setup"
```

---

## Task 6: Dev overlay (live reload)

**Files:**
- Create: `docker-compose.dev.yml`

**Interfaces:**
- Consumes: services from Tasks 1–5.
- Produces: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up` with agent hot-reload and live-mounted source.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compose_config.py — append
def test_dev_overlay_config_is_valid():
    import subprocess
    r = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "config"],
        capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    assert "--reload" in r.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_compose_config.py::test_dev_overlay_config_is_valid -v`
Expected: FAIL — no `docker-compose.dev.yml`.

- [ ] **Step 3: Create the dev overlay**

```yaml
# docker-compose.dev.yml
# Usage: docker compose -f docker-compose.yml -f docker-compose.dev.yml up
# agent  : live source + uvicorn --reload (edits apply instantly)
# kali   : mcp_server.py/postrun.sh already bind-mounted in base — `docker restart kali` to reload
services:
  agent:
    volumes:
      - ./agent:/srv/agent
      - ./db:/srv/db
    command: ["uvicorn", "agent.app.main:app", "--host", "0.0.0.0", "--port", "8080",
              "--reload", "--reload-dir", "/srv"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_compose_config.py::test_dev_overlay_config_is_valid -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.dev.yml tests/test_compose_config.py
git commit -m "feat: dev overlay — agent hot-reload + live-mounted source"
```

---

## Task 7: Full-stack smoke test + run docs

**Files:**
- Create: `tests/test_stack_smoke.py`, `README.md`

**Interfaces:**
- Consumes: everything from Tasks 1–6.

- [ ] **Step 1: Write the end-to-end smoke test**

```python
# tests/test_stack_smoke.py
import asyncio, subprocess, httpx, psycopg
from neo4j import GraphDatabase
from fastmcp import Client
from tests.conftest import wait_for

def test_full_stack_comes_up_and_connects():
    subprocess.run(["docker", "compose", "up", "-d", "--build"], check=True)
    body = wait_for(lambda: httpx.get("http://localhost:8080/health", timeout=3).json(), timeout=600)
    assert body["status"] == "ok"

    async def _roundtrip():
        async with Client("http://localhost:8000/mcp") as c:
            await c.call_tool("execute_command",
                              {"command": "echo persisted > note.txt", "session_id": "smoke-e2e"})
            r = await c.call_tool("execute_command",
                                  {"command": "cat note.txt", "session_id": "smoke-e2e"})
            return r.data
    assert asyncio.run(_roundtrip())["stdout"].strip() == "persisted"

    d = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "polymerhus"))
    with d.session() as s:
        names = {r["name"] for r in s.run("SHOW CONSTRAINTS YIELD name")}
    assert "endpoint_unique" in names
    d.close()

    with psycopg.connect("postgresql://polymerhus:polymerhus@localhost:5432/polymerhus") as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.doc_chunks')")
        assert cur.fetchone()[0] == "doc_chunks"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `docker compose down -v && python -m pytest tests/test_stack_smoke.py -v`
Expected: PASS after a full up cycle.

- [ ] **Step 3: Write the run docs**

```markdown
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
    pip install -r requirements-dev.txt
    python -m pytest tests/ -v

## Reload during dev
- agent: automatic (`uvicorn --reload`).
- kali MCP server / gap-fill: `docker restart kali`.
- schemas: neo4j re-applied by the agent on reload; postgres `init.sql` re-runs only on `down -v`.

## Schemas
- Neo4j Layer-0: `db/neo4j/schema.py` (applied by the agent at startup).
- Postgres app + `doc_chunks`: `db/postgres/init.sql` (first DB init).
- LangGraph checkpoints: `AsyncPostgresSaver.setup()` at agent startup.
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_stack_smoke.py README.md
git commit -m "test: full-stack smoke + operator run docs"
```

---

## Self-Review

**Spec coverage (`recon-mvp-design §11` + `documentation-ingestion-design §4` + this thread's decisions):**
- Four-service topology + volumes → Tasks 1–5. ✓ (ZAP withdrawn by operator; not added.)
- Kali image reuse + post-run gap-fill (massdns/puredns/whois/graphql-cop/kiterunner; arjun already present) + fastmcp `execute_command` + per-session workdir → Task 4. ✓
- Agent `FROM redamon-agent` (inherits langgraph/langchain-mcp-adapters/models), AsyncPostgresSaver, embedded-graph-in-FastAPI pattern → Task 5 + Global Constraints. ✓
- Neo4j 5.26 adapted constraints (no `user_id`/CVE, `+Observation`) → Task 3. ✓
- pgvector app schema + `doc_chunks` + HNSW + checkpoint tables → Tasks 2, 5. ✓
- Env matrix incl. `STEEL_*` (declared, deferred) + `EMBED_*` (local, pre-baked) → Task 1. ✓
- Dev live-reload config → Task 6. ✓

**Deliberately out of scope (later iterations, not gaps):** recon pods/orchestrator, ingestion pipeline + Steel crawling agent, per-tool command templates/parsers, auth-context plumbing, REST endpoints beyond `/health`.

**Placeholder scan:** none — every step carries concrete content or an exact command.

**Type consistency:** `execute_command` → `{stdout, stderr, returncode, duration_ms}` produced in Task 4, consumed with those keys in Tasks 4/5/7; `check()`/`ensure_schema()`/`ensure_checkpoint_tables()` defined in Task 5 and called only there; `init_schema(session)` defined in Task 3, imported by Task 5's neo4j client. Consistent.

**Notes / risks for the implementer:**
- Building `agent/Dockerfile` **requires `redamon-agent:latest` locally**; `kali` service **requires `redamon-kali-sandbox:latest`**. Neither is pulled.
- The agent base installs deps at pinned versions (langgraph resolved from `>=0.2.0`; `langgraph-checkpoint-postgres>=2.0.0`). We **inherit and target those** — if `AsyncPostgresSaver.from_conn_string`/`get_tools` differ from the snippets, adapt to the installed version rather than force-upgrading the 16 GB base.
- First `kali` up compiles massdns + fetches `kr`/resolvers into the `kali-tools`/`resolvers` volumes; later ups reuse them. Recreating with `down -v` triggers a recompile.
- `init.sql` runs only on an empty `pg-data` volume.
- fastmcp is installed into the Kali venv by `postrun.sh` (kept out of the image so the image stays pull-only).
