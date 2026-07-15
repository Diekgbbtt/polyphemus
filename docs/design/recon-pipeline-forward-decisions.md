# Recon Pipeline - Forward Design Decisions

Decisions taken during Phase 2 (recon pipeline) that deliberately shape or defer work for later phases.
Recorded here so a later phase inherits the rationale rather than re-deriving it.
Companion to `recon-pipeline-design.md`, the authoritative, code-grounded consolidated design (supersedes `recon-mvp-design.md`, rev 5).
Where this doc and the live code disagree, the code wins; where this doc and `recon-pipeline-design.md` disagree on a still-open deferral, this doc is authoritative for the deferral's rationale and status.
Refreshed 2026-07-07 against the real-target e2e validation (memory `recon-e2e-validation`) and the live codebase; every D1-D4 entry below was re-verified, not just carried forward.

## D1 - Scope expansion beyond rev-5 §7 (VERIFIED, built)

Rev 5 §7 excluded `nuclei` and did not list `kiterunner`, `paramspider`, `steel`, `graphql_scan`, `subdomain_takeover` in the job set.
Operator decision (2026-07-03): **all six are in scope for Phase 2.**

**Status as of the real-target e2e validation (memory `recon-e2e-validation`): five of the six shipped.**
`kiterunner`, `paramspider`, `graphql-cop`, `subdomain_takeover`, and `steel_crawl` are all live `JobSpec` entries in `agent/recon/jobs.py::JOBS` (verified `path:line`: `jobs.py:121-128` kiterunner, `jobs.py:91-98` paramspider, `jobs.py:137-144` graphql-cop, `jobs.py:56-66` subdomain_takeover, `jobs.py:145-153` steel_crawl), each with a working parser under `agent/recon/parsers/`.
`nuclei` alone was **not** ported - see D2's correction below; it exists nowhere in `agent/` (no `JobSpec`, no parser, no pod wiring - verified by search).

Install status in the reused `redamon-kali-sandbox` image (unchanged from the original decision, not re-verified by this stream - out of scope for a docs-only pass):

| Tool | Present | Source of truth |
|---|---|---|
| nuclei | yes (`/root/go/bin/nuclei`, `nuclei-templates/` present) | base image |
| kiterunner (`kr`) | gap-filled at runtime | `kali/postrun.sh` |
| paramspider | yes (`/opt/venv/bin/paramspider`) | base image |
| graphql-cop | yes (`/usr/local/bin/graphql-cop`) | base image |
| steel engine | **no** | see D3 |

Note the distinction: the *binary* being present in the Kali image (this table) is orthogonal to whether the *agent-side* job/parser/pod wiring exists.
`nuclei`'s binary is installed but nothing in `agent/` invokes it - D2 below is the accurate current status.

## D2 - nuclei stays fully deferred; the re-entrant interface it motivated is also unbuilt (CORRECTED)

**Correction against the original text of this decision.** The original D2 stated "nuclei is ported and made runnable by a recon pod, but is deliberately excluded from the default phase DAG."
This is stale: **nuclei was never ported.**
There is no `nuclei` entry in `agent/recon/jobs.py::JOBS`, no `nuclei_parser.py` under `agent/recon/parsers/`, and no on-demand invocation path anywhere in `agent/` - verified by repository-wide search, zero matches.
The rationale for keeping it out of the default DAG still holds (template selection is a knowledge-base-phase concern, deferred), but the phrase "ported and made runnable" overstated what actually shipped in Phase 2.
Both the nuclei pod itself and the re-entrant on-demand entry point it would use remain **fully deferred, unbuilt work** for a later phase.

nuclei's target shape, unchanged from the original decision: the first **optional, on-demand recon tool**, invoked only when:
- the **pipeline orchestrator** evaluates that a specific discovered component warrants deeper inspection with specific nuclei templates; or
- a **later-phase agent** (analysis / threat-model) needs more detail on a specific component and **queries the recon orchestrator back** for it.

This still motivates the forward architectural seam recorded here: a **re-entrant, targeted recon interface** on the pipeline orchestrator - a way to request focused recon on a specific graph component outside the linear phase plan, returning the resulting assets/observations.
**Status: this interface does not exist in code today.** `agent/recon/pipeline.py` has no re-entrant entry point, no `request_targeted_recon` function, and no module named `agent/recon/targeted.py`.
The addendum below records the shape a later phase should build it to (fixed by the context-memory L3 design, itself unbuilt - see `recon-pipeline-design.md` §9.5), so nuclei's eventual on-demand pod and the L3 extension engine can share one interface rather than two.

### D2 addendum - the shape a later phase should build the interface to (still unbuilt, status corrected)

The context-scaffolding L3 scaffold (`context-scaffolding-three-levels.md` §4; end-to-end trace in `context-memory-end-to-end.md` §5) was designed as the **first intended caller** of this re-entrant interface, and it fixed a proposed shape.
**Correction: none of the following has been built.** `agent/recon/synthesis.py` and `agent/recon/targeted.py` do not exist; `run_pipeline`'s last statement is unconditionally `registry.set_run_status(run_id, "complete")` (`agent/recon/pipeline.py:171`) with no synthesis/extension step before it.
The shape below is preserved as the design a later phase should build to, not a status report of work done:
- **Signature.** `request_targeted_recon(run_id, component, tool, template_set) -> list[PodExport]` - builds a synthetic single-pod `JobSpec` around `{component, tool, template_set}` and reuses the existing pod machinery (no new subgraph). This is the "on-demand entry point" this decision reserved, now given a type.
- **Two origins on one seam.** L3's post-core synthesis would call it with `origin="l3_synthesis"` (deterministic finding-triggered candidates, LLM-ranked under a request cap); a future **analyser -> probing-request** (the L2-A2 deferred grounding path) would call the *same* interface with `origin="analyser_probe"`. Building it once for L3 satisfies both.
- **Fail-open (A3).** The interface would be best-effort like the rest of the pipeline: a targeted probe that cannot succeed returns a `failed` `PodExport` and the caller (L3's single-pass, capped extension loop) records it and moves on - never re-queues or blocks the run's terminal `complete`.
- **Cap.** L3 would enforce a hard `EXTENSION_REQUEST_CAP` on the number of D2 calls per run, so the interface cannot be driven into an unbounded scan loop.

See `recon-pipeline-design.md` §9.5 for the full designed-not-built L3 writeup, and §12 below for this deferral's current open-status entry.

## D3 - Agentic crawl engine: external Steel.dev (operator decision 2026-07-04) - phrasing corrected against the live client

`steel_helpers.merge_steel_into_by_base_url` is only a **merge adapter** over a crawl manifest (`{endpoints:[...], js_urls:[...]}`).
The manifest is produced by an agentic ReAct loop (`crawl_agentic.py`, vendored verbatim from the `redamon-agent` base image, now living at `agent/recon/crawl/crawl_agentic.py`) driving **Steel.dev tools** against a Steel browser service.

**Decision (operator, 2026-07-04): use external Steel.dev**, driving the crawl loop + `steel_*` tools, rather than a self-hosted Playwright engine.
This *supersedes* the earlier recommended default (self-hosted Playwright reusing the kali image's `/opt/mcp_servers/playwright_server.py`), which was flagged for operator veto - the operator vetoed it in favour of Steel.dev.

**Correction to this decision's original implications text.** The original text said "the agent needs a **Steel MCP client** + config (`STEEL_API_KEY`, **Steel MCP endpoint**)."
This is stale and was never the shape that shipped: the built `steel_client.py` is **not** an MCP client reaching a remote host.
The seven `steel_*` tools are provided by an **in-process** tool provider that opens a steel.dev cloud-browser session and drives it with Playwright connected over CDP (`wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<id>`) - see `agent/recon/crawl/steel_client.py:1-14` (module docstring, explicit "NOT reached over a remote MCP HTTP host").
The only credential is `STEEL_API_KEY` (`agent/recon/config.py:10`); there is **no** `STEEL_MCP_URL` or equivalent endpoint setting anywhere in the codebase.
`steel_configured()` checks only the API key (`steel_client.py:71-77`).

Remaining implications, verified live: the agentic-crawl job is `configurator_mode="agent"` (the ReAct loop IS the configurator, `agent/recon/jobs.py:145-153`) - built.
`steel_parser.py` ports the manifest into `AssetDelta`s like the rest of the fleet - built (`agent/recon/parsers/steel_parser.py`, wired at `crawl_pod.py:230`).
Authenticated crawl uses `steel_await_auth` (human-in-the-loop viewer login) - built, with a known timing limitation (viewer URL only surfaces after the blocking crawl completes, see `recon-pipeline-design.md` §7.5).
Unit tests inject `client_factory`/`tools` (like the pod mocks `exec_fn`) - built (`tests/recon/` mocks the Steel client per `steel_client.py`'s injection seam).

**NOW BUILT (verified 2026-07-08, commit `5d2ec2d`) - this paragraph previously described the provider as unbuilt; that is stale.** The in-process Steel tool provider is ported and live.
`steel_client._default_client_factory()` (`steel_client.py:69-99`) now returns a real `agent/recon/crawl/steel_provider.py::SteelCrawlProvider` (573-line provider: opens a steel.dev cloud session via the Steel SDK and drives it with Playwright over CDP, exposing all seven `steel_*` tools as LangChain `StructuredTool`s).
It raises `SteelProviderUnavailable` **only** when `playwright`/`steel-sdk` are not importable in the build (the `redamon-agent` base image provides both), in which case the crawl pod still degrades gracefully to a `reduced_crawl_coverage` Observation.
So a real crawl pod only degrades to an empty manifest when the deps are absent OR `STEEL_API_KEY` is unset - when the provider and key are present it performs a real cloud-browser crawl.
See D6 for the merged commit trail and the auth-viewer-timing fix.

## D4 - Parser porting reality (supersedes rev-5 "porting LOW") (VERIFIED, built)

The deterministic parse layer lived in `redamon-recon:/app/recon` (not in the `redamon-agent` base image) and was coupled to DinD execution + a shared cross-tool `by_base_url` accumulator.
The graph-write layer (`redamon-agent:/app/graph_db/mixins/recon/*`) wrote straight to Neo4j keyed on `user_id`.
Neither matched the design's `AssetDelta`.
Phase-2 approach: **vendor (copy) each per-tool parse function into the repo, strip execution + docker, drop `user_id`, and re-express each tool's individual contribution to `by_base_url` as `AssetDelta`s** consumed by one generic curator - preserving each parser's rigid determinism and tool-specific exception handling.
Recon ports **per-tool, per-pod** (relying on `MERGE` idempotency for cross-tool convergence), not an in-memory cross-tool accumulator.

**Verified as built and validated:** `agent/recon/parsers/` holds 16 per-tool parser modules plus `steel_parser.py` (17 total), each exposing the `stdout -> list[AssetDelta]` contract resolved by `get_parser(tool)` (`agent/recon/parsers/__init__.py:38`); `curator.curate` is the single generic MERGE consumer (`agent/recon/curator.py:122-168`), confirming the per-tool/per-pod approach shipped exactly as decided.
No further correction needed against this decision.

## D5 - Context-memory L1/L2/L3 build (new deferral, added 2026-07-07)

The three-level context-memory scaffold - cross-phase operational-failure memory (L1, `recon_signals`), grounded per-target completeness verdicts (L2, `CoverageVerdict`), and post-DAG macro synthesis + finding-triggered extension (L3, `MacroDigest` + the D2 re-entrant interface) - is fully designed (`recon-pipeline-design.md` §9, folding in the retired `context-scaffolding-three-levels.md` and `context-memory-end-to-end.md`) and **entirely unbuilt**.
Verified by repository-wide search: zero occurrences of `PodSignal`, `CoverageVerdict`, `MacroDigest`, `recon_signals`, `synthesize_macro_observations`, `plan_finding_triggered_extensions`, `request_targeted_recon`, `build_job_context`, `build_asset_context`, or `JobState.job_context` anywhere under `agent/`.

**Why deferred.** The MVP shipped and validated the core phase-DAG (D1/D4) and the agentic-crawl exception (D3) first; the context-memory scaffold is additive reasoning layered on top of a graph that is already sound (memory `recon-e2e-validation`: 8 live tool families, 12 primitive labels persisted, adversarial Observations anchored correctly).
It was designed opportunistically during Phase 2 (operator answers A1-A5, 2026-07-06/07) but never scheduled for implementation in this iteration.

**What a later phase inherits.**
- **Build order, fixed by the design:** L2 -> L3 -> L1.
  L2 is lowest-risk (refocuses the already-real `asset_context`/`build_asset_context` retrieval idea, closes the live anchor-allowlist bug described in `recon-pipeline-design.md` §4.1/§7.4, needs no new store).
  L3 is second (consumes L2's `coverage_gap` Observations, targets the D2 re-entrant interface this doc's D2 already reserves, needs a new root reasoning step but no new store).
  L1 is last (needs a new Postgres table `recon_signals` AND enables a new LLM call in `job_agent.preprocess` - the most net-new machinery, and the design (`context-scaffolding-three-levels.md` §7 RESOLVED update) already flags it as the smallest surviving risk after A1/A4 collapsed two of its three original blockers).
- **The live gap L2 would need to close first.** The pod `gate` (`agent/recon/pod.py:151-164`) branches only on `returncode == 0` - an HTTP 200 WAF block-page is indistinguishable from success at the gate today, so any future L1 detector work has to live in the triager's judgement, not the gate.
- **The unpopulated `asset_context` field is the concrete integration point.** `PodState.asset_context`/`JobState.asset_context` already exist and are threaded end to end (`agent/recon/types.py:59`, `agent/recon/job_agent.py:33,60,93,119-120,183`) but are always `""` - populating them via `build_asset_context` is L2's first concrete task, not a new field to add.
- **Seven operator-validation items remain open** (V1-V7 in the retired `context-memory-end-to-end.md` §9, preserved there for the full text): LLM-preprocess cost/latency gating on `job_context != ''`, the `recon_signals` writer placement (pipeline-flush vs. triager-direct-write), whether L3 reuses the pod/job machinery vs. a dedicated extension subgraph, the `triage_fn`/`preprocess_fn` contract-widening confirmation, the L2-minimal-now tension (free LLM judgement vs. a structural/checklist coverage baseline), `recon_signals`' run-scoped-vs-cross-run durability, and the `EXTENSION_REQUEST_CAP` default (proposed 5) + initial `EXTENSION_RULES` seed set.
  None of these were resolved by code; they are still open questions for whoever picks up L1/L2/L3.

## D6 - Steel full-port + authenticated crawl (DONE, merged - verified 2026-07-08)

This was in-flight concurrent work on `agent/recon/crawl/**`; **it has now landed on `feat/recon-pipeline`** and this section is updated from "IN PROGRESS" to reflect the merged state (verified: all three commits below are ancestors of HEAD).
Merged commit trail:
- `3fbb284` feat(recon): Steel MCP client + crawl config + crawler LLM role.
- `6b0df4e` fix(recon): correct Steel client architecture (in-process Playwright-proxy-to-steel.dev, drop `STEEL_MCP_URL`) + document interactive-auth limitation.
- `5d2ec2d` feat(crawl): port real Steel provider (Playwright-over-CDP) + early auth `viewer_url` + gated e2e (+1037 lines / 7 files) - this is D6 itself.

**Both scope items are built:**
- **In-process Steel provider - BUILT.** `steel_client._default_client_factory()` returns a real `SteelCrawlProvider` (see D3, now refreshed); `SteelProviderUnavailable` is raised only when `playwright`/`steel-sdk` are absent.
- **Auth-crawl hardening + viewer-URL-timing fix - BUILT.** The §7.5 defect (viewer URL surfaced only after the blocking crawl, too late to log in) is fixed by an early-surfacing callback: `crawl_agent.run_crawl_authenticated(..., on_awaiting_auth=...)` precreates the Steel session and fires the hook BEFORE the blocking crawl; `crawl_pod.py` wires it to write `viewer_url` mid-flight to the `recon_jobs` row that `GET /recon/{run_id}` reads, so the operator can log in within the session window.

Tests shipped with the port: `tests/recon/crawl/test_crawl_auth.py`, `test_steel_client.py`, and a gated live e2e `test_steel_crawl_real_e2e.py` (skips unless `STEEL_API_KEY` set AND Neo4j reachable; interactive-auth portion further gated on `STEEL_MANUAL_AUTH_E2E=1`).

**Remaining (not code, human/serialized):** (1) provision a funded steel.dev `STEEL_API_KEY` in the deployment `.env` (currently empty in `.env.example`) - without it, live crawl degrades gracefully to `reduced_crawl_coverage`; (2) run the gated live happy-path + interactive-auth E2E on the main tree (satisfies the D18 authenticated-testing requirement). **One deferred code follow-up, explicitly NOT part of D6:** non-interactive cookie-injection into the Steel session from `extra.auth_context.cookies` (today only the human-in-the-loop viewer flow is supported); track separately.
`recon-pipeline-design.md` §7.5 still presents the viewer-URL-timing gap as a live limitation and should get the same follow-up refresh.

## D7 - Header capture scope: not a prior forward decision, closing the loop

Checked against this doc's own history and the design docs it superseded: **no prior forward-decision entry constrained `Header` capture scope.**
The live behavior - `httpx` invoked with `-irh` (include-response-headers) and every response header persisted as a `Header{name, baseurl}` node with a `HAS_HEADER` edge from `BaseURL` (`agent/recon/parsers/httpx_parser.py:71-84`, `agent/recon/jobs.py:78` command template) - was a design choice made and shipped directly (commit `b783773`, per memory `recon-e2e-validation`), not a walk-back of an earlier narrower decision.
Recorded here only to close out the brief's question, not because there is an open deferral: **all headers are captured today; there is no pending forward-decision item for header scope.**

## D8 - Deterministic re-anchor repair for triager anchor errors (deferred, not built)

Observation anchors are deliberately restricted to five broad assets (`agent/recon/curator.py::ANCHOR_ALLOWLIST = {Domain, Subdomain, BaseURL, IP, Service}`); the triager (`skills/recon/triager/writing-observations`) is instructed to re-anchor a finding UP to the broad asset that owns the narrow element (Endpoint/Header/Technology/Parameter/Port), naming the narrow element in `evidence`.
When the triager fails to re-anchor, `build_observation_cypher` correctly raises and `curate` skips+logs the observation, so it is silently lost.
This is a live, measured failure, not hypothetical: in the 2026-07-08 multi-target validation (memory `recon-e2e-validation`), ~36% of one target's observations arrived anchored on narrow nodes (Endpoint 16, Port 4, Header 2 of 61) - a direct consequence of the fact that the skill is **not wired into the triager prompt today** (`default_triage_fn` in `agent/recon/pod.py` uses a terse inline prompt; nothing under `agent/` loads the skill).

**Operator decision (2026-07-08): a failed re-anchor-UP is recoverable DETERMINISTICALLY in the parse/curator layer** - not by widening the allowlist (rejected: fragments the host-level observation graph, masks mis-anchoring) and **not by a hybrid broad-anchor + narrow `locus` reference (rejected: risks blowing up the graph** with a per-narrow-node observation edge/property explosion).

The repair shape (to build later): when an observation arrives anchored on a narrow node whose type is a real primitive but outside `ANCHOR_ALLOWLIST`, **detect it, traverse the graph from that narrow node to its closest higher-level broad hop** (Endpoint/Header/Technology -> owning `BaseURL`; `Parameter` -> owning `BaseURL`; `Port` -> owning `IP`/`Service`), **and rewrite the MERGE to anchor on that broad node** rather than dropping it; the narrow node's identity stays in `evidence`.
This is a systematic, non-LLM safety net that runs on the deterministic curator path.

**Status: not built.** `build_observation_cypher` today raises `ValueError` on a disallowed anchor and `curate` skips it (`agent/recon/curator.py:80-119,153-166`); there is no traversal-based re-anchor. The PRIMARY fix stays triager-side (wire + harden the writing-observations skill so anchoring is correct at generation time); this D8 repair is the belt-and-suspenders layer for the residual cases the LLM still gets wrong after the skill is in place.

## D9 - Certificate capture is NOT needed (operator decision 2026-07-08, closed)

The 2026-07-08 validation flagged that no `Certificate` nodes are emitted despite HTTPS on every host (`recon-e2e-validation`). **Operator decision: Certificate elements are not needed** - the recon graph does not require TLS-certificate primitives as first-class nodes for its attack-surface purpose.
This closes that finding as **won't-fix**, not a deferred gap: `Certificate` remains a legal Layer-0 label (`curator.ALLOWED_LABELS`) so nothing breaks if a parser ever emits one, but there is no work item to make `httpx` (or any tool) produce them, and their absence is expected, not a defect.

## D10 - amass is low-value and stays deferred (documented, not scheduled)

`amass` (`agent/recon/jobs.py:24-30`) is broken against the installed **amass v4.2.0**: its `enum` subcommand removed the `-json` streaming flag the command template and `parse_amass` expect, so the job degrades on every target (verified live, both unibas and magnific/houseofhr runs show `amass degraded` in `recon_jobs`).
**Operator decision: low value, deferred - do not prioritize.** `subfinder` already covers passive subdomain enumeration well (verified: 41k subdomains on unibas.ch in isolation), so amass's failure does not reduce coverage on any observed target; it is a redundant second source. Fixing it later means a v4.2.0 command rework (`amass enum -dir <d>` populates a graph DB; JSON comes from a separate `amass db` export) plus adapting `parse_amass` to the v4 output shape - recorded so a later pass does not re-derive this, but explicitly not scheduled.

## D11 - apex domain must be HTTP-probed / BaseURL phase must include the apex URL (NEW work item, verified gap)

**Verified live (houseofhr run `cbfc76ec`, 2026-07-08):** the seed apex's own web origin is never characterized. `http://houseofhr.com`, `https://houseofhr.com`, and `https://www.houseofhr.com` exist as BaseURL **stubs** (`status_code` NULL, no title/headers/technology), while every ENRICHED BaseURL is a *subdomain* (mycv-*, opcosquare-*). Root cause is a data-contract gap: `httpx` (phase 3, the BaseURL-enriching probe) `consumes="Subdomain"` (`jobs.py:75-81`), and the apex `houseofhr.com` is modeled as a `Domain` node, **not** a `Subdomain` - it is never in httpx's input set. The apex BaseURL stubs are created later by the Domain-consuming phase-4 tools (gau/katana), which is why they exist but are unenriched.

Downstream contract check: the phase-4 jobs that `consumes="BaseURL"` (katana/ffuf/kiterunner) read ALL project BaseURLs including the apex stub, so they *do* run against the apex URL - but against an unenriched origin (no tech/header context), reducing their effectiveness on the primary host.

**Work item (to build): the BaseURL-producing/enriching phase must include the URL formed from the apex domain.** Cleanest options: (a) seed the apex as a `Subdomain` (name == apex) so httpx probes it like any host, or (b) widen httpx to also consume the `Domain` apex. Either makes the primary target's live surface (status/title/security headers/technology) first-class. Verify after the fix that the apex BaseURL is ENRICHED and that phase-4 consumers pick up the enriched node.

## D12 - phase-execution observability: execution persisted, per-job data lineage is not (NEW work item)

**What IS persisted (verified):** `recon_runs` (per run: status, current_phase, heartbeat) + `recon_jobs` (per run x phase x job: `status` in success/degraded/skipped, and `stats = {pods, success, failed}`). This is the authoritative artifact proving which phases/jobs executed - e.g. houseofhr run `cbfc76ec` shows all 6 phases ran (phase 0 subfinder/whois success, amass degraded; phase 1 dnsx/puredns/subdomain_takeover 8/8; phase 2 naabu 7/8; phase 3 httpx 8/8; phase 4 ffuf/katana/kiterunner/jsluice/graphql-cop 7/7, gau/paramspider 1/1, steel_crawl 7/7 failed [expected, D3-steel]; phase 5 arjun 4/8). Queryable directly; also exposed at `GET /projects/{id}/recon/{run_id}` (`per_job`).

**What is NOT persisted:** per-job **data lineage** - the exact assets each job *consumed* and *produced*. `stats` records pod counts, not asset counts; produced assets are only inferable in aggregate from Neo4j label totals + each `JobSpec.consumes/produces`, and cannot be attributed to a specific job (many jobs produce the same label). **Work item (to build): persist per-job produced-asset (and ideally consumed-asset) counts** on the `recon_jobs` row (or a companion table), and/or a run-summary endpoint, so "all phases executed with the data they consumed/produced" is verifiable from persisted state rather than reconstructed.

## D13 - frontend graph nodes must render their object data (DONE, operator-verified 2026-07-08)

The force-graph (`frontend/src/graph/GraphCanvas.tsx`) previously rendered every node as a bare colored dot; the node's data (`properties`, and for an `Observation` its natural-language comment) was fetched (`GET /projects/{id}/graph` returns `node.properties`) but never shown. **Built (commit `3494662`):** each node now surfaces its object data in a small styled box on hover (`nodeTooltip` / `nodeLabel`) - an `Observation` shows its NL comment (evidence/rationale/macro_kind), every attack-surface element shows its object attributes; content is HTML-escaped since it originates from scanned third-party targets. Hover (not permanent labels) was chosen because at graph scale (houseofhr 6656 nodes) an always-on box per node is unreadable; a click-to-pin detail panel is the natural follow-up if persistent inspection is wanted. **Operator-verified 2026-07-08: renders correctly, closed.**

## D14 - seed-domain scope semantics: exact-apex vs wildcard (NEW work item, verified gap)

**Verified live:** the pipeline has **no scope concept**. `pipeline.py:42` seeds the root asset as `[{"name": settings.get("target_domain")}]` - a bare domain string with no exact-vs-wildcard distinction. The only `scope` token in the codebase is `auth_context.scope` (`routes.py:49-64`), an unrelated auth field. Consequently subfinder/amass (`consumes="Domain"`) always fan out to discover subdomains regardless of whether the operator meant "this exact host" or "the whole zone".

**Desired semantics (operator, 2026-07-08):**
- If the submitted target is a **complete/exact domain** (e.g. `app.example.com`), that host **is** the scope: no further subdomain discovery should run - the discovery phase (subfinder/amass, and the puredns/dnsx expansion that follows) should be suppressed, and recon proceeds on the single seeded host.
- If the target carries a **wildcard placeholder** (e.g. `*.example.com`), the whole zone is in scope: subdomain discovery runs as today.

**Explicit carve-out:** this scope gate does **not** apply to `subdomain_takeover`. Using an out-of-scope asset as a *parameter* to a takeover check is valid (the finding is about a dangling reference the in-scope target points at), so takeover scanning stays enabled regardless of the exact/wildcard decision.

**Work item (to build):** introduce a scope descriptor on the target (parse the `*.` placeholder at settings/seed time into `{apex, mode: exact|wildcard}`), and gate the discovery phase on `mode == wildcard`. In `exact` mode, seed the single host directly into the post-discovery input set (it must still reach httpx/naabu/etc.) rather than dropping it because discovery was skipped. Keep `subdomain_takeover` outside the gate.

**BUILT (Stream 1, branch `worktree-agent-aebb63213aaa093b3`, commit `fb47b41`, jointly with D11).** New `agent/recon/scope.py::parse_scope(target) -> {apex, seed_host, mode}`; `DISCOVERY_JOBS = {subfinder, amass, puredns, dnsx}` suppressed in exact mode; the seed host is injected into every `consumes="Subdomain"` job's input population so httpx/naabu/takeover reach it. 288 recon tests pass. Awaiting the two operator resolutions below before integration onto `feat/recon-pipeline`.

**Q1 RESOLVED (operator, 2026-07-08): keep the inversion, add a loud note.** The bare-domain-means-exact-host rule inverts the historical implicit-wildcard default. The operator is the sole user, so there is no third-party surprise risk, and the evolution of the seeding decision is legible from the project history itself (older projects were run pre-D14 as implicit wildcard; newer ones carry the explicit scope). **Add a loud note:** when `mode == exact` suppresses discovery, record it in the run (a phase-0 note e.g. `scope=exact; subdomain discovery suppressed`) so a small run is self-explaining rather than silently empty. Do NOT flip the default back to wildcard.

**Q2 RESOLVED (operator, 2026-07-08): confine gau/paramspider to the exact host in exact mode.** Verified defect in the branch: `seed_assets` returns `{"name": scope["apex"]}` (the registrable apex), and `gau`/`paramspider` (`consumes="Domain"`, NOT in `DISCOVERY_JOBS`) therefore harvest the whole `example.com` zone for an exact `app.example.com` target - a scope leak past the four gated discovery jobs. **Fix:** in exact mode seed the `Domain` node as `seed_host`, not the registrable apex -
```
return [{"name": scope["seed_host"] if scope["mode"] == "exact" else scope["apex"]}]
```
The only Domain-consumers that need the registrable parent (subfinder/amass) are already suppressed in exact mode, so this confines gau/paramspider to the in-scope host without harming discovery. See D14b for the whois tradeoff this exposes.

## D14b - whois in exact-subdomain mode consumes the wrong Domain granularity (NEW forward decision, deferred)

The D14/Q2 fix (seed `Domain = seed_host` in exact mode) exposes a second-order issue: `whois` also `consumes="Domain"`, so in exact mode `whois app.example.com` runs against the subdomain host rather than the registrable parent. Most whois servers only answer for registrable domains, so a subdomain query typically returns the parent's record or nothing - it degrades gracefully (best-effort pod, no crash), and registration data of a subdomain is rarely the point of an exact-host scan, so the Q2 fix accepts this.

**Deferred forward decision:** if whois should always hit the registrable parent regardless of scope mode, whois must consume the apex *specifically* (a per-job scope override, e.g. whois reads `scope.apex` while gau/paramspider read `scope.seed_host`), rather than sharing one `Domain` seed granularity with the passive harvesters. That is a larger change to the seed/consume model than the one-line Q2 fix and is **not scheduled** - recorded so a later pass does not re-derive it. Until then, whois in exact-subdomain mode is expected to be low-signal, not a defect.

## D15 - endpoint noise filtering: path-based, precision-traded-for-recall on user-controllable assets (NEW work item)

**Problem (operator, houseofhr as reference):** the attack surface is polluted by endpoints that are strictly presentational - static assets and pure HTML render artifacts (`.css`, `.jpg`/`.jpeg`, `/assets/`, `/styles/`, fonts). These should be removed. **But** blanket extension filtering (`katana -ef png,jpg,gif,css,woff,woff2,ttf`, which we currently replicate at `jobs.py:104`) also discards **user-controllable images** - images referenced via a user-supplied `src` attribute or user-uploaded media - which are legitimate attack surface (SSRF/stored-XSS/path traversal vectors) and must be retained.

**Why extension filtering can't express this:** the risky-vs-noise distinction is not in the file extension - a `.jpg` under `/assets/` is noise, a `.jpg` under `/upload/` or served from a user-controlled path is surface. Extension filtering is high-precision/low-recall on exactly the assets we care about keeping.

**Direction (operator):** filter on **URL path** rather than extension. Path-based rules (drop `/assets/`, `/static/`, `/styles/`, fingerprinted-bundle paths; keep `/upload/`, `/media/`, user-content paths, and any path with a user-supplied parameter) trade precision for **recall on user-controllable media** - the correct trade here, since a false-negative (keeping a truly-static asset) is cheap noise while a false-positive (dropping a user-controllable image) loses real surface. **Work item (to build):** (a) remove/relax the blanket `-ef` extension filter so user-controllable images survive collection, (b) add a post-collection path-based noise classifier (drop static-render paths, preserve user-content/parameterized paths), applied as a curator/parser-side filter so the rule is centralized and testable rather than embedded per-tool. Note this interacts with D16 (profiling): a path filter is a coarse first cut; content-type profiling refines it.

## D16 - two-stage endpoint discovery + profiling drives downstream routing (NEW work item, may split a phase)

**Current shape:** phase 4 discovers endpoints (katana crawl, ffuf brute, gau passive) and phase 5 (arjun) plus phase-4 kiterunner/paramspider consume them - but **without any webapp-vs-restapi classification**. Every BaseURL/Endpoint is treated identically; api-specific tools (kiterunner, api-mode ffuf) fire against presentational endpoints and param tools fire indiscriminately.

**Desired shape (operator):**
1. **Discover** endpoints - crawled by katana, or brute-forced/passively harvested by ffuf/gau.
2. **Profile** each endpoint as **webapp** (HTML UI) or **restapi** (backend-exposing, e.g. JSON). Classification signals: content-type (`application/json` => api), and more generally the httpx-observable response shape. This profiling can also **prune gau noise**: many passively-harvested URLs are dead (404) and can be dropped by an httpx liveness+profile pass before they reach expensive consumers.
3. **Route by profile:**
   - **restapi** endpoints -> ffuf (configured for **API** discovery, distinct from content-discovery mode) + kiterunner.
   - **parameters** -> paramspider + arjun run on **both** classes.

**Feasibility (verified):** the profiling signal is **already collected** - the httpx parser captures `content_type` today (`httpx_parser.py:29,64`). What is missing is (a) a profiling step that persists a webapp/restapi label per endpoint (httpx is the natural home; it could also do the gau-liveness prune), and (b) a router that keys downstream `consumes` on that label rather than on the bare `Endpoint`/`BaseURL` type.

**Architectural consequence:** this likely **decomposes the current single discovery phase into two** - *discover* then *profile* - with the profile becoming a first-class asset attribute that the phase-5 (and api-specific phase-4) tools consume. This touches the phase DAG (`jobs.py` PHASES + JobSpec.consumes), so it is a structural change, not a tweak; sequence it after D14 (scope) since scope determines the endpoint population being profiled.

**BUILT (minimal, operator-directed 2026-07-11, commit `7c9b995`).** Chose the reuse-first path over a phase split: httpx already runs at phase 3 (before the phase-4 crawlers) and already carries `content_type`, so NO new job/phase was added. `noise_filter.classify_profile(content_type, url) -> "webapp"|"restapi"` (JSON-family content-type, or an api-indicating hostname label -> restapi) is set as a `profile` prop on every httpx BaseURL and its root Endpoint. `kiterunner` is gated to `consumes_where=AssetSelector(field="profile", op="equals", values=["restapi"])` (reusing the D17 selector), so it fires only at the API surface. **Deferred (not built):** the discover->profile split for crawler-minted Endpoints (katana/ffuf endpoints carry no profile yet - only httpx-probed BaseURLs do); an api-mode ffuf variant; the gau-liveness prune (gau withdrawn, D19). Revisit if API-surface coverage needs the crawled-endpoint population profiled too.

### D16.1 - dedicated `graphql_api` profile + graphql-cop gating (BUILT minimal 2026-07-14; enhancement deferred)

**Problem found (live run f845fd03, 2026-07-13):** `graphql-cop` carried no `consumes_where`, so it fired at ALL 54 BaseURLs (part of the phase-4 concurrency explosion) rather than only the GraphQL surface. Unlike `kiterunner`, it was ungated. There was also no profile to gate it on - D16 profiling only produced `webapp`/`restapi`.

**BUILT (operator-directed):** `classify_profile` now returns a third profile `graphql_api`, derived from a **path heuristic** on the httpx-discovered URL (matches a known GraphQL endpoint path - `/graphql`, `/api/graphql`, `/v1/graphql`, `/query`, `/graphql/console`, `/playground`; slash/case/query-tolerant; false-match-guarded so `/graphql-docs`, `/mygraphql` stay `webapp`). It takes precedence over the restapi/webapp rules and requires **no new network I/O** (reuses the URL httpx already has). `graphql-cop` is regated `consumes_where=profile == "graphql_api"`. Accepted tradeoff: detection miss -> graphql-cop does not fire there.

**ENHANCEMENT (deferred, operator-approved as a future work item):** the path heuristic only catches GraphQL served at a conventional path. A GraphQL API mounted under a **non-obvious path on a generic API host** (e.g. `api.example.com/internal/gw`) classifies as `restapi`, not `graphql_api`, so graphql-cop will not fire there. Closing that gap needs **active GraphQL detection during profiling** - most robustly an **introspection `__schema` probe** (POST a minimal introspection query, e.g. `{__schema{queryType{name}}}`, or a `{__typename}` probe, and classify `graphql_api` on a GraphQL-shaped response), and/or a lightweight content-signal check (an `application/graphql-response+json` content-type, or a GraphQL error envelope on a malformed GET). This introduces **new active HTTP I/O into the profiling stage** (currently pure/no-network), so it is a deliberate structural change: it wants a bounded, rate-limited probe pass (respecting scope + WAF-steering), ideally reusing the httpx pod rather than a fresh fetch, and it must not probe out-of-scope hosts. Sequence it only if a real run shows GraphQL endpoints slipping through under generic API hosts; the path heuristic is the accepted floor until then. Note graphql-cop itself is the deep GraphQL auditor, so this profiling probe only needs to be a cheap **pre-filter** that decides whether graphql-cop runs, not a full GraphQL characterisation.

## D17 - jsluice JS-analysis is not doing what its parser documents (NEW work item, verified defect)

**The operator asked to see precisely how JS files are discovered, identified, and processed, and specifically whether jsluice (1) attempts to discover each bundle's source `.map` file and (2) processes every discovered JS file. Both answers are NO, and the live evidence shows why.**

**What the job actually runs** (`jobs.py:129-136`): `curl -s {target} | jsluice urls -j -R {baseurl}`, with `consumes="BaseURL"`. So for each BaseURL the pod `curl`s the **origin root page** (typically HTML) and pipes *that* into `jsluice urls`. It does **not**: enumerate the site's JS bundles first, fetch each `.js`, run jsluice per bundle, attempt `.map` sourcemap discovery, or ever invoke `jsluice secrets` mode.

**What the parser *documents* it should do** (`parsers/jsluice_parser.py:4-6`): "jsluice is run **in two modes** (`urls` + `secrets`) **against JS files discovered by the crawl phase**." The parser is even built to ingest interleaved `urls` and `secrets` lines and to emit `Secret` nodes. **The job command and the parser contract have diverged** - the parser can handle secrets and per-bundle input the job never produces.

**Live evidence (all runs):**
- **0 `Secret` nodes** in Neo4j, ever - `jsluice secrets` mode never executes.
- **5** jsluice-sourced `Endpoint` nodes total across all runs - i.e. `jsluice urls` over the HTML root yields almost nothing, because the real endpoints live inside the JS bundles it never opens.
- **1507 `.js` endpoints** exist in the graph (discovered by **katana**, which crawls JS), but jsluice `consumes="BaseURL"`, not these `.js` `Endpoint`s, so **not one discovered bundle was fed to jsluice**.
- **0 `.map` files** discovered anywhere - no sourcemap-discovery logic exists in the pipeline.
- Per-run execution is confirmed in `recon_jobs` (e.g. run `cbfc76ec` jsluice success, `stats.pods=7` == BaseURL count, **not** JS-file count), so jsluice ran **once per BaseURL origin**, not **once per JS bundle**. Langfuse traces (job_agent wires `get_langfuse_callbacks`, `job_agent.py:198`) carry the per-pod command+stdout for the same runs.

**Work item (to build): make jsluice actually analyze JS.** (a) Change the jsluice input to the discovered **JS-bundle endpoints** (the `.js` `Endpoint`s katana already produces) rather than the BaseURL root. (b) Run **both** modes per bundle (`jsluice urls` **and** `jsluice secrets`) so the `Secret` path the parser already supports is exercised. (c) Add **sourcemap (`.map`) discovery**. This is a data-contract change (jsluice `consumes` shifts from BaseURL to a JS-Endpoint selector) and pairs naturally with D16's profiling step.

### D17 grey points RESOLVED (operator, 2026-07-08), grounded in the live graph

**Q5 - bundle selection mechanism: path-suffix predicate, NOT content-type.** Decisive datum: `content_type` is **NULL on all 1507 `.js` `Endpoint`s** (they were minted by katana crawl, not by an httpx profile pass), so the selector cannot key on content-type and D17 does **not** depend on D16's profiling. `read_assets` is label-only. **Decision:** add an optional `consumes_where` predicate to `JobSpec` + a filtered `read_assets`; jsluice selects `Endpoint.path ENDS WITH '.js' OR '.mjs'`. Reusable seam, pure, testable - not a jsluice special-case read.

**Q6 - pod-budget vs volume: BATCH bundles per pod (operator decision).** Live distribution (houseofhr project `099a1df2`): 1315 `.js` endpoints but only **653 distinct paths** (~50% are dupes); **1314 of 1315 first-party**; two tenant subdomains (`mycv-ctrlf-uat`, `mycv-timepartner-uat`) carry **519 each** - the same SPA bundle set duplicated. `MAX_PODS = 20`, so even after dedup (653) the naive one-pod-per-bundle is ~33x over budget. **Decision: batch N bundles per pod** (one pod runs a shell loop over a batch of bundle URLs, fetching + `jsluice`-ing each), keeping the pod budget intact and scaling past any fixed cap. Apply the cheap reductions first so batches are lean: (1) dedup by path, (2) dedup identical bundles across hosts (by basename/content-hash), (3) same-origin/first-party filter to drop third-party CDN bundles (e.g. `assets.allegrostatic.com` 175, `googletagmanager`, `doubleclick` - out of scope, no value). Batching bends the current one-input-asset-per-pod model, so it is the larger structural piece of D17.

**Q7 - sourcemap identification/filtering/extraction: replicate the operator's `secret_scanner.py` logic (do NOT use that script).** The operator's reference implementation (GitHub `Diekgbbtt/GroundPenetratingRadar/secret_scanner.py`) is the spec for behavior to reproduce with jsluice (and/or a small helper), not a dependency to vendor. Replicate:
- **Identification (both paths):** (i) extract the sourcemap comment `//[#@]\s*sourceMappingURL=(.+?\.map)` from the fetched bundle; (ii) if absent, **fallback-probe** `<bundle_url>.map`; (iii) a URL already ending `.map` is treated as a direct sourcemap. Dedup processed `.map` URLs (a `_processed_sourcemaps` set) so the same map is never re-analyzed.
- **Filtering:** a noise filter excluding `\.(css|scss|png|jpg|jpeg|gif|svg|map)$`, any `/webpack/` internals, and `/node_modules/` paths **unless** they also contain `/internal/`; plus content-hash dedup of source bodies (md5) so identical sources across bundles are scanned once. (This dovetails with the D15 noise filter and the Q6 cross-host dedup.)
- **Extraction:** parse the sourcemap JSON `sources[]` + `sourcesContent[]`, index-mapping each source path to its embedded content (`source_type='embedded'`); when `sourcesContent[i]` is null, fetch the source; then run secret regexes over each recovered source string. Sanitize source paths before any persistence (strip `webpack://<host>/`, strip `^[a-z]+://`, strip leading `./`, and neutralize `..` traversal). jsluice `secrets` mode covers the regex-scan step; the `.map` fetch/parse/`sourcesContent`-walk + sanitize is the wrapper logic to add around it. Endpoints recovered from the original sources feed the `urls` path as usual.

## D18 - authenticated recon: structural auth-capability typing + coverage gaps + testing (NEW work item, partially built)

**What ALREADY exists (verified, do not rebuild):** the "attribute that specifies whether a tool can execute with an authenticated context" is `JobSpec.use_auth: bool` (`types.py:43`), and the orchestrator **already detects it structurally and provides the context when the project carries it**: `pipeline.py:141` gates `extra["auth_context"] = settings["auth_context"]` on `job.use_auth and settings.get("auth_context")`; `job_agent.py:55-56` strips the auth channel from non-`use_auth` jobs; `fill_template` injects the tool-appropriate cookie flag via `{auth_header}`; and the project settings channel is validated end-to-end (`routes.py:46-64`, `_validate_auth_context` for `cookies` + `scope`). Jobs currently typed `use_auth=True`: **httpx, katana, ffuf, arjun, steel_crawl**. So katana crawling and ffuf/arjun discovery already run authenticated when the project supplies `auth_context`.

**paramspider stays unauthenticated (operator-confirmed, 2026-07-08):** paramspider is a **passive** harvester (web-archive/CommonCrawl sources); it never makes requests to the live target, so a session cookie has nothing to authenticate against. It stays `use_auth=False` by design. Active authenticated parameter discovery is arjun's role (already `use_auth=True`). No change to paramspider.

**The actual gap:**
- **The typing is binary, not "which have an authenticated *version*".** The operator's phrasing ("detect structurally which have an authenticated version of the execution") is satisfied today by the `use_auth` boolean + cookie injection - but if a tool needs a *materially different invocation* under auth (e.g. a different wordlist, an extra login-aware flag, or a distinct command_template) rather than just an added header, that is not yet expressible. If that is the intent, `use_auth: bool` should become an optional authenticated command variant (e.g. `auth_command_template`) that the configurator selects when context is present.

**Testing requirement (operator, explicit): the authenticated actions must be tested afterward.** Once the typing is settled, add tests that exercise the authenticated path end-to-end - not just that `{auth_header}` renders, but that with a real `auth_context` the auth-typed tools (httpx/katana/ffuf/arjun/steel) reach and record **authenticated-only surface** they miss unauthenticated (e.g. behind-login endpoints/parameters). This needs a target with an auth-gated area; gate the live portion on reachability the same way the existing frontend-bff live suite does (commit `d8bd8af`).

## D19 - gau withdrawn from the pipeline (temporary, bring-forward, 2026-07-09)

**Operator decision:** gau produced overwhelming passive-archive noise - in run `8816cc2d` its pod merged **866** low-value assets (dead/duplicate archive URLs) versus katana's live crawl, polluting the attack surface for little unique signal.
gau is **removed from the pipeline now**: its `JobSpec` and phase-4 `PHASES` entry are withdrawn so the orchestrator no longer schedules it.
The pure `parse_gau` parser (`agent/recon/parsers/passive_url_parser.py`) is **kept dormant** - not deleted - so a future re-introduction is cheap.

**Bring-forward:** re-evaluate gau behind a noise filter before re-wiring it. A viable path is to feed gau output through the D15 curator-gate filter (drop static/noise, D-www dedup, out-of-scope drop) AND an httpx-liveness prune (D16) so only live, in-scope, non-presentational archive URLs survive.
Only re-add the `JobSpec`/`PHASES` entry once that filtering is in place; until then gau stays out.

**Verification (contract):** `POST /projects/{id}/recon` with `jobs` including `gau` now returns 400 (unknown job) and never launches; the baseline (no-jobs) pipeline still launches without it (`tests/test_rest_api.py::test_post_recon_with_removed_gau_job_returns_error`, `..._baseline_pipeline_still_launches_without_gau`, `tests/recon/test_jobs.py::test_gau_is_not_a_scheduled_job`).
The live-container check of the same requires the agent image to run this code (dev bind-mount or rebuild).

## D20 - BaseURL must link to its source Subdomain (built, strong constraint, 2026-07-09)

**Verified defect (project `64d2ab81`):** all 24 BaseURLs had **zero incoming edges** - httpx minted them orphaned, diverging from the intended `Domain -> Subdomain -> BaseURL` chain.
Root cause: `httpx_parser` built the BaseURL delta with no edge to the host it was probed from.

**Built:** `httpx_parser` now emits `BaseURL -[:BELONGS_TO]-> Subdomain{name: <httpx input>}` (httpx's `input` is exactly the probed Subdomain, so it matches an existing node), mirroring `subdomain_parser`'s `Subdomain -[:BELONGS_TO]-> Domain`.
Strong constraint enforced by `tests/recon/test_httpx_parser.py::test_every_baseurl_belongs_to_its_source_subdomain` - a BaseURL delta without a `BELONGS_TO -> Subdomain` edge fails the suite.

## D21 - www.<host> deduplication (built, 2026-07-09)

`www.<host>` is conventionally the same web content as `<host>`, but the graph showed both as distinct Subdomains/BaseURLs.
**Built:** the curator gate (`noise_filter.filter_deltas`) unconditionally drops any `Subdomain` named `www.*` (which cascades - httpx never probes it, so no `www.` BaseURL is minted) and any `www.` BaseURL / anchored child as a belt; `parse_scope` strips a leading `www.` from the seed so seeding `www.x` or `*.www.x` resolves to the same scope as `x`. Applies in both exact and wildcard modes.

## D22 - recon-job & recon-pipeline agent skills for STEERING DECISIONS (NEW work item, bring-forward, 2026-07-10)

The LLM-driven steering built on 2026-07-10 reasons over the WAF signals surfaced by `read_steering_signals`, gated + fail-open (no signal means no LLM call and today's behavior exactly).
Per the agent responsibility taxonomy, each steering decision lives WITH its owning agent (refactor 2026-07-11, dissolving the earlier cross-cutting `steering_agent.py`): macro cross-job routing (`decide_routing`) in the recon-orchestrator agent `agent/recon/orchestrator_agent.py`, per-asset run/skip/throttle (`decide_pod_selection`) in the recon-job agent `agent/recon/job_agent.py`.
The shared, decision-free domain reasoning (`STEERING_PRIMITIVES`) plus thin helpers live in `agent/recon/steering.py`; each agent frames those primitives in its OWN inline system prompt (`ORCHESTRATOR_STEERING` / `JOB_STEERING`).
Those inline per-agent prompts are the operator-approved TEMPORARY home for the thought process; the proper home is dedicated per-agent skills, single-sourced and loaded at runtime the way the triager loads `skills/recon/triager/writing-observations/SKILL.md`.

**Bring-forward (to build):** (a) author `skills/recon/job-agent/steering/SKILL.md` and `skills/recon/pipeline-agent/steering/SKILL.md` capturing the STEERING DECISIONS domain primitives (WAF/IP-egress routing, throttle-as-prevention, and future signal types beyond WAF).
(b) Load each at runtime in its owning agent module (`orchestrator_agent.py` / `job_agent.py`), replacing the inline `ORCHESTRATOR_STEERING` / `JOB_STEERING` constants, mirroring `_load_triager_skill`.
(c) Split the shared `job_orchestrator` model role (both agents pass it to `steering.resolve_model` today) into distinct orchestrator/job roles once the skills diverge.
Until then the inline per-agent prompts are the single source, each owned by its agent.

**Scope note (operator, 2026-07-11):** a steering-only skill is almost certainly too narrow - steering is just ONE facet of recon orchestration.
The recon-orchestrator agent's skill should be a GENERAL recon-orchestration skill (macro pipeline management: phase planning, WAF/signal-driven routing/steering, and finding-triggered deep+narrow extensions, i.e. the L3 responsibility), with steering as a section rather than the whole skill.
Likewise the recon-job agent's skill should be its general per-job configuration skill (L1 cross-job failure-mode learning), with per-asset steering as one section.
So (a) above should author `skills/recon/pipeline-agent/SKILL.md` and `skills/recon/job-agent/SKILL.md` as general per-agent skills, folding STEERING DECISIONS in as a subsection, not standalone `steering/` skills.

## D23 - autonomous credentialed login for agentic crawl + MFA/SSO gap (NEW work item, in design, 2026-07-11)

Operator direction (2026-07-11): add a project setting capturing authentication credentials (draft: email, password, and the login base URL) so the agentic crawl can autonomously navigate to the sign-in portal and log in, instead of relying on hand-harvested session cookies or a human completing the login in the Steel viewer inside a short window.

**Threat-model note (operator):** this runs in an authorized penetration-testing context where the operator OWNS the credentials and authorizes their use against the target. Storing/handling the operator's own credentials to reach the operator's own authorized target is therefore NOT the third-party-secret-exposure risk it would be otherwise; the earlier "plaintext creds are a reusable master secret" objection does not bind here. Captchas are expected to be handled by Steel itself.

**KNOWN UNSOLVED GAP - MFA / SSO / OAuth (deferred, OUT OF SCOPE for the first build).** Autonomous form login cannot, on its own, complete:
- MFA / 2FA challenges (TOTP, SMS, push, hardware key) - a second out-of-band factor.
- SSO / OAuth / OIDC redirects to a third-party IdP (the login leaves the target origin; the IdP may itself enforce MFA and is out of crawl scope).
There is NO solution designed yet. **Operator decision (D23-5, 2026-07-11): for the first build, MFA/SSO is a BLOCKING state, not a degrade-to-interactive handoff.** When autonomous login cannot complete, the crawl pod simply blocks and times out to the existing `reduced_crawl_coverage` degrade (best-effort, no crash) - the elaborate degrade-to-`steel_await_auth`/Discord handoff is deliberately NOT built now. A real MFA/SSO story (operator-supplied TOTP seed, pause-and-resume handoff, headful IdP step) is the follow-up work item, tracked here.

**Design RESOLVED (operator, 2026-07-11) - the first build:**
- **D23-1 login mechanism = the LLM ReAct crawl loop** (`crawl_agentic.py` driving `steel_*` tools), NOT a deterministic Playwright routine. Highest reuse, consistent with "the crawler agent drives the browser"; credential-in-trace exposure is accepted under the threat model above.
- **D23-2 auth split by CONSUMER, not precedence:** `auth_context.credentials` drive the AGENTIC (steel) crawl login; `auth_context.cookies` remain the request-based tools' `-H Cookie` header (httpx/katana/ffuf/arjun). They do not compete.
- **D23-3 selector discovery = heuristic default + operator override** (`input[type=password]` + nearest identifier input + submit; explicit selectors in settings override).
- **D23-4 login_url = any origin, success asserted target-scoped:** the login navigation bypasses the crawl scope guard, but success requires an IN-SCOPE (target) session cookie, so a dedicated `login.*`/`accounts.*` works while a true third-party IdP naturally fails to the blocking state.
- **D23-6 success detection HARDENED:** baseline cookies before login, require a NEW session-like cookie that appears strictly AFTER the login attempt AND a navigation off the login path - not the weak start-baseline detector, since there is no human to catch a false-authenticated crawl.
- **D23-7 host-gated:** only pods whose target host matches the credentials' domain (login_url origin or an explicit `credentials.domain`) attempt login; other hosts crawl anonymous - credentials belong to one app, never scattered across every BaseURL (lockout/mis-auth hazard).

**Pre-existing bug flagged by the design pass (verify + fix separately, not part of D23):** `extra["scope"]` is never set by the pipeline (only `scope_domain`, pipeline.py ~294), so the crawl node falls back to `scope = [target-URL]` (crawl_pod.py ~182) and `_registrable_in_scope` compares a bare host against a full `https://...` string, which never matches. Independent of D23 but load-bearing for its cross-origin reasoning.

## D24 - per-component logging (orchestrator / job / pod) supersedes shared-row status surfacing (NEW work item, bring-forward, 2026-07-13)

Today the recon substrate has no per-component log streams: the only per-run/per-job observability is the `recon_jobs` registry row (status + a `stats` JSONB) plus the fail-open Langfuse trace.
This forces a layering compromise (C2, operator-accepted): the Steel `viewer_url` is the POD's to surface, but with no pod log the pod writes it mid-flight into the shared `recon_jobs` row (`crawl_pod.default_status_sink`) while the pipeline is blocked on `await run_job`, and the pipeline then re-asserts it on the terminal write so the full-stats overwrite does not clobber it - a two-writer coordination on one row.

**Bring-forward (to build):** give the recon-pipeline orchestrator, each recon-job agent, and each pod their OWN log stream (structured, per `(run_id[, phase, job, pod])`).
Then component-owned facts surface from the owning component's log rather than being written into a shared registry row: the `viewer_url` (and any other mid-flight pod signal) surfaces from the POD's log - its rightful owner - so the pod no longer reaches into `recon_jobs`, the pipeline's re-assert hack retires, and "the pipeline is the sole `recon_jobs` writer" holds cleanly (resolving C2 by removing the shared write, not by relocating it).
This also generalizes the D12 per-job lineage and the D-command per-pod command capture into first-class per-component logs.

## D25 - client-side webapp knowledge base + semantic model (NEW work item, substantial bring-forward, 2026-07-13)

**Goal.** Extend recon to collect a broad CLIENT-SIDE knowledge base for a webapp, so a later ANALYSER phase can build a *semantic model* of the client-side application - what it is, how it behaves, what it trusts, and which assumptions it makes - BEFORE any vulnerability reasoning.
The analyser's method is the operator-authored draft skill `skills/systems-analysis/[DRAFT]webapp-clientside-semantic-model.md` (2026-07-13): an 8-stage pipeline (structural -> behavioral -> data-flow -> trust-boundary -> domain-model -> external-integration -> assumption-extraction -> architectural-risk) producing a natural-language semantic model that is the foundation for all subsequent security analysis.
This decision covers the RECON side (collecting the artifacts that skill assumes as inputs); the analyser/skill itself is a downstream consumer.

**This EXTENDS, it does not replace, the current extraction.** The existing source-artifact collectors stay as-is: httpx (BaseURL/Endpoint/Header/Technology/Certificate), katana crawl (Endpoints/Parameters), and jsluice (D17: `jsluice urls`/`secrets` over the `.js`/`.mjs` bundles + sourcemap recovery). D25 adds the *runtime / browser-observable* artifacts on top of those, and enriches the ones that already exist.

**Collection matrix (draft, 6 categories).** Most items require interfacing with a live browser and reading signals from it - which the Steel-managed browser (D3) does over CDP - so the natural collector is the agentic crawl pod, not the request-based tools.

| Draft category | Item | Existing coverage | New collection (Steel/CDP) |
|---|---|---|---|
| 1. Source artifacts | HTML, JS bundles, source maps, recovered sources | httpx (HTML/root), katana (bundles), jsluice D17 (bundles + `.map` recovery) | rendered HTML per route (post-JS), tie recovered sources to the semantic model |
| 2. Runtime page state | rendered DOM, shadow DOM, custom elements | none (only network-captured URLs today) | `page.content()` / CDP DOM snapshot per crawled route; shadow-root + custom-element enumeration via `steel_eval` |
| 3. Execution traces | user-interaction traces, DOM mutations, JS execution timeline | none | MutationObserver script injected via `steel_eval`; CDP tracing / Performance timeline; the crawl ReAct loop's own interaction sequence |
| 4. Network observations | requests, response metadata, dynamic resource loading, WebSockets/EventSource | PARTIAL - `steel_provider` already captures `page.on("request")` (`self.requests`, used to build the endpoint manifest) | response metadata (status/headers/content-type), dynamic (XHR/fetch/import) loads, WS/SSE via CDP Network domain |
| 5. Browser persistence | cookies, localStorage, sessionStorage, IndexedDB, Cache Storage | PARTIAL - auth cookies are injected/detected (D18/D23), not inventoried as surface | read all four stores per origin via `steel_eval` + CDP Storage domain (keys/shapes, not necessarily values) |
| 6. Environment fingerprint | framework, bundler, build metadata, browser APIs used, service/web workers | PARTIAL - httpx Technology fingerprint (server-observable) | client-side framework/bundler markers from the runtime, `navigator`/API usage, registered Service/Web Workers via CDP |

**Architectural placement.**
- Collector: the Steel agentic crawl pod (`crawl_pod`/`crawl_agentic`/`steel_provider`) is where a live browser already exists per crawled route, so per-route runtime capture (DOM, storage, workers, execution traces) rides the crawl the operator is already running - ideally after authenticated login (D23), since the interesting client-side surface is post-login.
- New asset/observation types: the captured artifacts become new graph nodes/props (e.g. a `ClientArtifact`/`RuntimeState` family, or props on the existing BaseURL/Endpoint), curated through the single curator gate. The exact schema is an open question below.
- Consumer: the analyser phase (the same L3-ish re-entrant/synthesis seam sketched in D2-addendum and `recon-pipeline-design.md` §9.5) loads the collected artifacts + the draft skill and emits the semantic model as the deliverable.

**Relationship to existing decisions.** Builds on D3 (external Steel.dev browser), D16 (webapp/restapi profile - only `webapp`-profiled BaseURLs need this deep client-side capture), D17 (jsluice source-artifact analysis - unchanged, feeds category 1), D18/D23 (authenticated crawl - the capture should run post-login), and the D2/L3 analyser seam (the consumer). It does NOT touch the request-based tools.

**Open design questions (to resolve before building).**
1. Capture volume vs. graph: a full DOM/trace per route is large - store raw artifacts where (blob/object store vs. Neo4j props vs. Postgres), and put only a distilled summary in the graph? The current graph holds compact assets/observations, not blobs.
2. Which routes get the deep capture - every crawled route, or only `webapp`-profiled + post-auth + novel-looking ones (cost control, mirrors the MAX_PODS/MAX_JOB_ASSETS budgeting ethos)?
3. Trigger model: is this a new phase, a richer crawl mode of the existing steel_crawl job, or a finding-triggered L3 extension (D2)?
4. Values vs. shapes for storage/persistence (category 5): capturing localStorage/IndexedDB *values* may capture secrets/PII - default to keys+shapes, opt-in for values (a scope/consent concern like the auth secrets).
5. Determinism: execution traces (category 3) are inherently non-deterministic per crawl run - how are they normalized so the semantic model is stable across runs?

**Status:** DRAFT, deliberately deferred, substantial (a new collection subsystem + schema + the analyser consumer). The item list and the skill are drafts and will be refined; recorded here so the later phase inherits the intent (a browser-collected client-side knowledge base feeding a semantic-model analyser) rather than re-deriving it.

## D26 - ffuf promoted to a REST-API fuzzing role (distinct from its content-discovery role) (NEW work item, DRAFT/deferred, 2026-07-14)

**Operator request (captured faithfully, in full).**
Promote `ffuf` to a REST-API **testing/fuzzing** tool as well, beside its existing role in the crawling / content-discovery phase.
In the API-testing role it should fuzz across five dimensions:
- **URL path** - again, but **narrower and deeper** than the phase-4 content-discovery sweep (targeted extensions of a known API surface, not a broad wordlist against a root).
- **HTTP method** - vary the verb against a fixed endpoint.
- **URL parameters** - requires feeding in **endpoints and parameters coupled together** (a real data dependency, see the coupling note below).
- **HTTP headers** - `Content-Type`, `Origin`, `Referer`, `X-Forwarded-For`, `Accept`, `Accept-Encoding`, and more.
- **Attribute values of the request body** - fuzz the values inside a structured (e.g. JSON) request body.

The explicit intent: this testing should **probe for weird failures** and **surface insights as triager Observations**; moreover the **payloads must be adapted specifically to the current knowledge of the attack surface**, and for each kind of fuzzing the payload **list should be declared beforehand** (a per-dimension payload set selected from graph state before the ffuf run).

**This is a DISTINCT role from ffuf's current phase-4 job.**
Today `ffuf` runs one content-discovery job (`jobs.py:107-117`): `ffuf -u {target}/FUZZ -w .../Web-Content/common.txt -mc 200,403 ... consumes="BaseURL"` - a single path-position brute at the origin root, producing `Endpoint`s.
D26 is a **second, separate job (or job family)** that belongs in a **later API-testing phase**, not in phase-4 discovery: it consumes a *characterised* API surface (profiled endpoints + discovered parameters) rather than bare BaseURLs, and its output is Observations, not merely new Endpoints.
This cross-refs D16/D16.1 (the `webapp`/`restapi`/`graphql_api` profiles - D26 fuzzing should be gated to `restapi` endpoints, reusing the `consumes_where` profile selector) and the WS2 phase-restructuring direction (D16's "decompose discovery into discover -> profile", extended here with a downstream **test** stage that consumes the profiled surface).

### The five fuzzing dimensions (elaboration - my elaboration below, marked as such)

For each dimension: *what it targets*, *example payloads / wordlists*, and *how the payload set adapts to current attack-surface knowledge in the graph*. The adaptation is the load-bearing part: ffuf's `FUZZ` keyword is filled from a **declared payload list built from graph state before the run** ("list beforehand per fuzzing kind"), not from a static generic wordlist.

| Dimension | Targets | Example payloads / wordlists | Attack-surface adaptation (source in graph) |
| --- | --- | --- | --- |
| **URL path** (narrow+deep) | Deeper path segments under a *known* API base (`/api/v1/FUZZ`, `/api/v1/users/FUZZ`), versioned siblings (`/v2/`, `/internal/`), verb-shaped resources | API-flavoured lists (seclists `api/`, `common-api-endpoints`), resource-name mutations derived from observed nouns | Seed from the endpoints already discovered on that host (katana/ffuf/jsluice `Endpoint`s + jsluice-recovered route names); mutate observed path tokens rather than brute a generic tree. Gate to `restapi`-profiled BaseURLs (D16). |
| **HTTP method** | Verb-tampering / method-override differences on a fixed endpoint | `GET,POST,PUT,PATCH,DELETE,HEAD,OPTIONS,TRACE`, plus override headers (`X-HTTP-Method-Override`) | Enumerate methods only against endpoints already known to exist; prefer methods hinted by the endpoint's observed behaviour (e.g. a `/users/{id}` resource -> try `PUT`/`DELETE`). **See destructive-method grey point Q3.** |
| **URL parameters** | Hidden/undeclared params, param-value handling, injection-shaped values | Param **names** (arjun/paramspider wordlists) and param **values** (fuzz-vector lists: SQLi/XSS/SSTI/traversal probes) | **Names**: seed from `Parameter` nodes arjun/paramspider already produced for that endpoint; **values**: adapt vector class to the endpoint's tech (httpx `Technology`) - e.g. SSTI vectors where a template engine is fingerprinted. Requires the Endpoint+Parameter coupling below. |
| **HTTP headers** | Header-driven ACL/routing/cache/content-negotiation behaviour | `Content-Type` (json vs form vs xml), `Origin` (reflected-CORS probes), `Referer`, `X-Forwarded-For`/`X-Real-IP`/`X-Original-URL`/`X-Rewrite-URL` (ACL/routing bypass), `Accept`/`Accept-Encoding` (content-negotiation) | Adapt candidate `Content-Type` values to the endpoint's observed content-type (D16 profile); adapt trust-header probes (`X-Forwarded-For` etc.) to hosts where an upstream proxy/WAF is fingerprinted (httpx `Technology`/`Header`); pull real internal hostnames/paths from the graph for `X-Original-URL`. |
| **Request body attribute values** | Value handling inside a structured body (type confusion, injection, mass-assignment-shaped keys) | Per-attribute fuzz vectors (type swaps: string<->int<->array<->object; injection vectors; boundary values), extra/unexpected keys | Seed the body **schema** (attribute names + types) from parameters/bodies already observed for that endpoint (arjun/paramspider/katana `Parameter`s, jsluice-recovered request shapes); fuzz one attribute at a time holding the rest valid. Requires the coupling below. |

**"Declare the payload list beforehand per fuzzing kind" (my reading).**
Before the ffuf run, a selection step reads graph state (the host's `Endpoint`/`Parameter`/`Technology`/`Header`/`profile` assets) and materialises **one explicit payload set per dimension** - a declared wordlist/vector file (or generated list) that ffuf's `FUZZ` keyword is bound to.
This is the mechanism by which "payloads adapt to the current knowledge of the attack surface": the list is a function of the graph at fuzz-time, not a fixed asset baked into the job template.
Architecturally this mirrors the D16 profiling seam (a pre-step that reads assets and shapes the downstream tool) and the L1 `job_orchestrator` preprocess seam (`build_job_context` reading graph/registry state before fan-out).

### Weird failures to probe, each becoming a triager Observation (elaboration)

The point of the fuzzing is not the raw responses but the **adversarial insight** the triager derives from anomalies - an Observation is an attack-surface insight, NOT a restatement of the raw HTTP response (memory `observations-vs-attack-surface-primitives`). Concrete failure classes to probe and the Observation each yields:
- **5xx / crash on malformed input** - a 500 on a type-swapped param or malformed body signals unhandled input -> Observation "endpoint E crashes on non-string `id` (type confusion, likely reaches a backend query unsanitised)".
- **Reflected input** - a payload echoed in the response -> reflected-XSS / SSTI signal Observation (with the reflection context, not just "200 with my string in it").
- **Auth/ACL bypass via trust headers** - a resource that 403s directly but 200s with `X-Forwarded-For`/`X-Original-URL`/`X-Rewrite-URL`/`Origin` set -> "ACL enforced at proxy only; `X-Original-URL` bypasses it".
- **HTTP method / verb tampering** - differing responses across `GET`/`POST`/`PUT`/`PATCH`/`DELETE` on one endpoint (e.g. `PUT` allowed where the UI only issues `GET`) -> "write verb reachable without UI affordance".
- **CORS misconfiguration** - `Origin` reflected into `Access-Control-Allow-Origin` with credentials -> "reflected-origin CORS with credentials on E".
- **Cache poisoning via unkeyed headers** - a header that changes the response but is not in the cache key -> "unkeyed `X-Forwarded-Host` influences cached response".
- **Content-type confusion** - endpoint accepts `application/json` and `application/x-www-form-urlencoded` interchangeably, or parses one as the other -> "content-type confusion on E (form body parsed where JSON expected)".
- **Parameter pollution** - duplicate/array params handled inconsistently (first vs last vs merged) -> "HPP: last-wins param merging on E".

Each of these is written by the pod triager as an `Observation` anchored on the endpoint (via the existing curator/writing-observations path), so D26 depends on nothing new in the observation-writing machinery - only on the fuzzing job producing the anomalous responses for the triager to reason over.

### Coupling requirement (real data dependency)

Parameter fuzzing and body fuzzing **cannot run on bare BaseURLs** - they need **Endpoint + Parameter pairs fed together**: the specific endpoint AND the parameter names/body attributes that belong to it.
This is a genuine data dependency on **arjun / paramspider** (`Parameter` producers) and on katana/jsluice-recovered request shapes: the fuzz job must consume a *joined* view (Endpoint with its attached Parameters), not the two asset types independently.
Concretely this needs either a graph read that returns `(Endpoint)-[:HAS_PARAM]->(Parameter)` groupings, or a `consumes_where` join extension, so a pod is handed one endpoint plus its parameter set as a coherent unit.
This makes D26 sequence strictly **after** the param-discovery phase (phase 5 arjun / phase-4 paramspider), reinforcing its placement in a later API-testing phase.

### Interactions

- **D16 / D16.1 profiles**: fuzz jobs gate to `restapi` (and possibly `graphql_api`) profiled endpoints via the existing `consumes_where` profile selector - do not fuzz presentational `webapp` endpoints.
- **WS2 phase restructuring**: this adds a **test** stage downstream of D16's discover -> profile split (discover -> profile -> **test**), a first-class API-testing phase in the DAG (`PHASES` in `jobs.py`), consuming the profiled+parameter-joined surface.
- **WAF-steering rate throttling**: aggressive multi-dimensional fuzzing is exactly what trips WAF/rate-limit defences; the fuzz jobs must honour the same `{rate_flags}` throttling ffuf already carries and the WAF-steering / `recon_signals` rate-limit awareness (`context-memory-end-to-end.md`) - a host already flagged `rate_limit`/`waf` should throttle harder or be deprioritised by the L1 `job_orchestrator` preprocess, not hammered across five dimensions.
- **D18/D23 authenticated context**: ffuf is already `use_auth=True`; the API-fuzzing jobs inherit the cookie/header auth channel so they test the **authenticated** API surface (the interesting one).

### Open grey points (unresolved - carried for operator decision, full options in the review return)

1. Job granularity: one mega-job fuzzing all five dimensions, or one job per dimension (path / method / params / headers / body)?
2. Payload adaptation mechanism: static curated per-dimension lists selected by graph query, LLM-generated-from-attack-surface lists, or both (curated floor + LLM enrichment)?
3. **Destructive-method safety**: fuzzing HTTP methods can issue `PUT`/`PATCH`/`DELETE` against a live target - real state mutation / data loss risk. Gate to safe-by-default (read-only verbs) with destructive verbs opt-in and scoped? This is the sharpest risk in the spec.
4. Coupling data path: extend `consumes_where` with an Endpoint->Parameter join, a dedicated joined-read helper, or a pre-step that materialises `(endpoint, params)` units?
5. Observation volume / dedup: multi-dimensional fuzzing can generate a flood of near-identical anomalies - how are Observations deduped/rate-limited so the graph is not swamped?

**Status:** DRAFT, deliberately deferred, documentation only (no code written). A later API-testing phase inherits the intent (ffuf as an attack-surface-adapted REST-API fuzzer whose anomalies become triager Observations), the coupling and profile-gating constraints, and the open grey points above - rather than re-deriving them.

## D27 - pipeline bidirectionality: feeding crawl-discovered hosts back upstream (NEW work item, substantial bring-forward, 2026-07-14)

**The gap (operator-surfaced).**
The recon pipeline is a strictly one-way phase DAG: discovery -> resolution -> port scan -> httpx -> crawl -> jsluice -> (api enumeration / testing).
But the crawl and JS-analysis stages (katana, steel_crawl, jsluice) routinely discover **new hosts / subdomains** that were never seen by phase-0 subdomain discovery - referenced in links, JS bundles, CORS/redirect targets, API base URLs, etc.
Today those newly-discovered hosts are recorded as graph assets (Subdomain / ExternalDomain / BaseURL) but there is **no backward edge**: they never re-enter the upstream phases, so an in-scope host first seen during the crawl is **never resolved, never port-scanned, never httpx-profiled, never itself crawled or API-tested**.
The pipeline therefore under-covers exactly the surface that deep crawling is best at finding.

**Open question the operator raised (must be answered by the design).**
How are subdomains/hosts discovered *throughout* reconnaissance currently handled - are they silently discarded, or automatically treated as out-of-scope?
This needs an explicit audit: for each producer that can mint a new host (jsluice URLs, katana `new_links`, steel frontier, httpx redirects, whois/dns related-domains), determine what happens to a host that is in-scope but was not in the phase-0 seed set.

**Why this is hard (the bidirectionality/re-entrancy problem).**
Turning the DAG into a **convergent feedback loop** introduces real complexity:
- **Scope gating of discovered hosts:** a crawl-discovered host must be classified in-scope vs out-of-scope before it is allowed to re-enter (reuse `agent/recon/scope.py`); out-of-scope hosts are recorded as `ExternalDomain` (attack-relevant context) but NOT re-scanned; in-scope hosts re-enter.
- **Re-entry point:** an in-scope new host should re-enter at resolution (dnsx/puredns) -> naabu -> httpx -> crawl -> api-testing, i.e. a mini-rerun of the DAG rooted at that host.
- **Termination / convergence:** the loop must provably terminate - a global visited-set keyed by host (and by asset identity) so a host is processed at most once, plus a max-depth / max-iteration / max-new-hosts budget to bound a pathological fan-out (e.g. a target that references thousands of hosts).
- **Cycle guard:** A links B links A must not loop.
- **Concurrency + the run lifecycle:** re-entrant work extends a run's lifetime and interacts with the heartbeat/reaper (see [[recon-run-oom-failure-mode]]) and the sequential-phase model - re-entry likely runs as bounded additional waves rather than unbounded recursion.
- **Cost:** each re-entering host multiplies scan volume; the budget must be operator-tunable.

**Direction (not yet built).**
Model it as a **bounded work-queue / fixpoint** rather than literal DAG recursion: a "newly-discovered in-scope host" queue drained in waves after the crawl/JS phases, each wave running the resolution->httpx->crawl sub-pipeline for its hosts, feeding any further new hosts back into the queue, until the queue is empty or a wave/host budget is hit.
Relates to D14 (scope semantics decide in-scope vs external), D16/D16.1 (re-profiling discovered BaseURLs already generalises "assets minted downstream get processed like first-class ones"), and the paramspider exact-mode gap that surfaced this (a Domain-consumer starved because the seed materialised only as a Subdomain).

**Status:** DRAFT, deferred, documentation only. First actionable sub-task before any build: the audit of what currently happens to crawl/JS-discovered hosts (discarded vs recorded vs scoped), since that determines how much of the loop is greenfield.
