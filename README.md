# polymerhus — platform stack

Autonomous vulnerability-discovery harness. Iteration 1 (recon MVP) substrate:
four containers the recon pipeline and documentation-ingestion subsystem run on.

## Prerequisites
Redamon's two base images must exist locally (reused, not rebuilt):
`redamon-agent:latest`, `redamon-kali-sandbox:latest` (`docker images` to check).

## Run
    cp .env.example .env
    docker compose up -d --build                # prod-ish
    # dev (agent hot-reload + live source):
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

Services: agent `:8080/health` · kali fastmcp `:8000/mcp` · neo4j `:7474`/`:7687` (neo4j/polymerhus) · postgres `:5432`.

## Verify
    python -m pytest tests/ -v

`GET /health` returns `{"status":"ok","checks":{"postgres":true,"neo4j":true,"kali_mcp":true}}` when healthy.

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
