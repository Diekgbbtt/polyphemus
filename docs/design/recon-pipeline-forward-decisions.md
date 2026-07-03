# Recon Pipeline - Forward Design Decisions

Decisions taken during Phase 2 (recon pipeline) that deliberately shape or defer work for later phases.
Recorded here so a later phase inherits the rationale rather than re-deriving it.
Companion to `recon-mvp-design.md` (rev 5). Where this doc and rev 5 disagree, this doc is the newer authority (operator-confirmed 2026-07-03).

## D1 - Scope expansion beyond rev-5 §7

Rev 5 §7 excluded `nuclei` and did not list `kiterunner`, `paramspider`, `steel`, `graphql_scan`, `subdomain_takeover` in the job set.
Operator decision (2026-07-03): **all six are in scope for Phase 2 and must be ported from Redamon.**
Install status in the reused `redamon-kali-sandbox` image (verified):

| Tool | Present | Source of truth |
|---|---|---|
| nuclei | yes (`/root/go/bin/nuclei`, `nuclei-templates/` present) | base image |
| kiterunner (`kr`) | gap-filled at runtime | `kali/postrun.sh` |
| paramspider | yes (`/opt/venv/bin/paramspider`) | base image |
| graphql-cop | yes (`/usr/local/bin/graphql-cop`) | base image |
| steel engine | **no** | see D3 |

## D2 - nuclei is on-demand, not in the default pipeline

nuclei is ported and made runnable by a recon pod, but is **deliberately excluded from the default phase DAG.**
Template selection is a knowledge-base-phase concern (deferred); until it exists, nuclei has no principled way to pick templates during an unattended run.

nuclei therefore becomes the first **optional, on-demand recon tool**, invoked only when:
- the **pipeline orchestrator** evaluates that a specific discovered component warrants deeper inspection with specific nuclei templates; or
- a **later-phase agent** (analysis / threat-model) needs more detail on a specific component and **queries the recon orchestrator back** for it.

This introduces a forward architectural seam to build now and lean on later: a **re-entrant, targeted recon interface** on the pipeline orchestrator - a way to request focused recon on a specific graph component outside the linear phase plan, returning the resulting assets/observations.
Phase 2 builds the nuclei pod + this on-demand entry point (with template selection stubbed to an explicit caller-supplied template/tag set); the knowledge-base phase later fills in automatic template selection.

## D3 - Agentic crawl engine: self-hosted browser, not external Steel.dev

Redamon's `steel_helpers.merge_steel_into_by_base_url` is only a **merge adapter** over a crawl manifest (`{endpoints:[...], js_urls:[...]}`).
The manifest is produced by an agentic ReAct loop (`crawl_agentic.py`) driving **Steel.dev MCP tools** (`steel_crawl_start/navigate/frontier/finish/eval/click/await_auth`) against an external Steel browser service - infra the 4-service topology does not include.
The reused kali image instead ships a local **Playwright** MCP server (`/opt/mcp_servers/playwright_server.py`).

Decision: **the Phase-2 agentic crawl reuses a self-hosted Playwright-based browser engine, exposing the same crawl-tool surface and emitting the same manifest contract**, rather than depending on the external Steel.dev service.
Rationale: keeps the stack self-contained (no external SaaS dependency, no credentials/egress), preserves the `steel_helpers` manifest contract verbatim (so the merge/parse code ports unchanged), and reuses browser automation already present in the image.
The `steel_*` **tool names and the ReAct crawl skill are preserved** as the interface; only the engine behind them changes.
Authenticated crawl (`steel_await_auth` + human-in-the-loop viewer login) is preserved as the auth path for `use_auth` crawl jobs.
This is the one architecture fork flagged for operator veto; absent objection it is the Phase-4 (agentic-crawl sub-plan) baseline.

## D4 - Parser porting reality (supersedes rev-5 "porting LOW")

The deterministic parse layer lives in `redamon-recon:/app/recon` (not in our `redamon-agent` base image) and is coupled to Redamon's DinD execution + a shared cross-tool `by_base_url` accumulator.
The graph-write layer (`redamon-agent:/app/graph_db/mixins/recon/*`) writes straight to Neo4j keyed on `user_id`.
Neither matches the design's `AssetDelta`.
Phase-2 approach: **vendor (copy) each per-tool parse function into the repo, strip execution + docker, drop `user_id`, and re-express each tool's individual contribution to `by_base_url` as `AssetDelta`s** consumed by one generic curator - preserving each parser's rigid determinism and tool-specific exception handling.
We port **per-tool, per-pod** (relying on `MERGE` idempotency for cross-tool convergence), not Redamon's in-memory cross-tool accumulator.
