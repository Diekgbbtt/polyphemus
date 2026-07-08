# Recon Pipeline - Forward Design Decisions

Decisions taken during Phase 2 (recon pipeline) that deliberately shape or defer work for later phases.
Recorded here so a later phase inherits the rationale rather than re-deriving it.
Companion to `recon-pipeline-design.md`, the authoritative, code-grounded consolidated design (supersedes `recon-mvp-design.md`, rev 5).
Where this doc and the live code disagree, the code wins; where this doc and `recon-pipeline-design.md` disagree on a still-open deferral, this doc is authoritative for the deferral's rationale and status.
Refreshed 2026-07-07 against the real-target e2e validation (memory `recon-e2e-validation`) and the live codebase; every D1-D4 entry below was re-verified, not just carried forward.

## D1 - Scope expansion beyond rev-5 §7 (VERIFIED, built)

Rev 5 §7 excluded `nuclei` and did not list `kiterunner`, `paramspider`, `steel`, `graphql_scan`, `subdomain_takeover` in the job set.
Operator decision (2026-07-03): **all six are in scope for Phase 2 and must be ported from Redamon.**

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

Redamon's `steel_helpers.merge_steel_into_by_base_url` is only a **merge adapter** over a crawl manifest (`{endpoints:[...], js_urls:[...]}`).
The manifest is produced by an agentic ReAct loop (`crawl_agentic.py`, vendored verbatim from the `redamon-agent` base image, now living at `agent/recon/crawl/crawl_agentic.py`) driving **Steel.dev tools** against a Steel browser service.

**Decision (operator, 2026-07-04): use external Steel.dev**, driving Redamon's crawl loop + `steel_*` tools verbatim, rather than a self-hosted Playwright engine.
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

**What is still genuinely unbuilt, distinct from the MCP-endpoint phrasing fix above:** the **in-process Steel MCP tool provider itself**.
`steel_client._default_client_factory()` unconditionally raises `SteelProviderUnavailable` (`steel_client.py:80-96`) - Redamon's concrete `steel_*` server (the module that actually opens the CDP session and exposes the seven tools) "is NOT vendored in any `redamon-*` image available in this environment" (module docstring, `steel_client.py:15-23`).
This means every real (non-test) crawl pod invocation today degrades to an empty manifest via the `SteelProviderUnavailable` path (`recon-pipeline-design.md` §7.3) - the crawl job runs, fails gracefully, and emits a `reduced_crawl_coverage` Observation, but never actually crawls anything.
Porting Redamon's steel server so `_default_client_factory()` returns a working provider is the concrete remaining Phase-2 gap, separate from and smaller than the "full port" a later phase's authenticated-crawl work may also cover (see §12).

## D4 - Parser porting reality (supersedes rev-5 "porting LOW") (VERIFIED, built)

The deterministic parse layer lived in `redamon-recon:/app/recon` (not in the `redamon-agent` base image) and was coupled to Redamon's DinD execution + a shared cross-tool `by_base_url` accumulator.
The graph-write layer (`redamon-agent:/app/graph_db/mixins/recon/*`) wrote straight to Neo4j keyed on `user_id`.
Neither matched the design's `AssetDelta`.
Phase-2 approach: **vendor (copy) each per-tool parse function into the repo, strip execution + docker, drop `user_id`, and re-express each tool's individual contribution to `by_base_url` as `AssetDelta`s** consumed by one generic curator - preserving each parser's rigid determinism and tool-specific exception handling.
Recon ports **per-tool, per-pod** (relying on `MERGE` idempotency for cross-tool convergence), not Redamon's in-memory cross-tool accumulator.

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

## D6 - Steel full-port + authenticated crawl (IN PROGRESS, not deferred - concurrent stream)

Unlike D5, this is not a deliberately-deferred decision - it is **active, concurrent work** on `agent/recon/crawl/**` by another stream in this same tree (confirmed via sibling worktrees at the time of this refresh: commits `3fbb284` "feat(recon): Steel MCP client + crawl config + crawler LLM role" and `6b0df4e` "fix(recon): correct Steel client architecture (in-process Playwright-proxy-to-steel.dev, drop STEEL_MCP_URL) + document interactive-auth limitation" are present on sibling branches ahead of what has landed on `feat/recon-pipeline` as of this doc).
Recorded here only so this doc's D2/D3 status doesn't go stale the moment that work merges.

**What D3 already documents as unbuilt and this stream is targeting:** the concrete in-process Steel MCP tool provider behind `steel_client._default_client_factory()` (`agent/recon/crawl/steel_client.py:80-96`), which today unconditionally raises `SteelProviderUnavailable`, meaning every real crawl pod invocation currently degrades to an empty manifest (see D3's closing paragraph and `recon-pipeline-design.md` §7.3).
Also in scope for that work per its commit history: authenticated crawl hardening (`crawl_pod.py`'s `steel_await_auth` MVP path and its documented viewer-URL-timing limitation, `recon-pipeline-design.md` §7.5).

**Action for whoever reads this doc next:** before relying on any Steel-related status claim in `recon-pipeline-design.md` §6/§7.3/§7.5 or in D3 above, check whether the concurrent stream's commits have landed on `feat/recon-pipeline` - if they have, `SteelProviderUnavailable` may no longer be the live path and both documents need a follow-up refresh.
This stream (Stream 1, docs-only) explicitly did not touch `agent/recon/crawl/**` or verify the sibling worktrees' code correctness - only their existence and target scope, to avoid this doc misrepresenting concurrent work as either "shipped" or "deferred" when it is actually "in flight."

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

## D15 - endpoint noise filtering: path-based, precision-traded-for-recall on user-controllable assets (NEW work item)

**Problem (operator, houseofhr as reference):** the attack surface is polluted by endpoints that are strictly presentational - static assets and pure HTML render artifacts (`.css`, `.jpg`/`.jpeg`, `/assets/`, `/styles/`, fonts). These should be removed. **But** blanket extension filtering (Redamon's `katana -ef png,jpg,gif,css,woff,woff2,ttf`, which we currently replicate at `jobs.py:104`) also discards **user-controllable images** - images referenced via a user-supplied `src` attribute or user-uploaded media - which are legitimate attack surface (SSRF/stored-XSS/path traversal vectors) and must be retained.

**Why extension filtering can't express this:** the risky-vs-noise distinction is not in the file extension - a `.jpg` under `/assets/` is noise, a `.jpg` under `/upload/` or served from a user-controlled path is surface. Extension filtering is high-precision/low-recall on exactly the assets we care about keeping.

**Direction (operator):** filter on **URL path** rather than extension. Path-based rules (drop `/assets/`, `/static/`, `/styles/`, fingerprinted-bundle paths; keep `/upload/`, `/media/`, user-content paths, and any path with a user-supplied parameter) trade precision for **recall on user-controllable media** - the correct trade here, since a false-negative (keeping a truly-static asset) is cheap noise while a false-positive (dropping a user-controllable image) loses real surface. **Work item (to build):** (a) remove/relax the blanket `-ef` extension filter so user-controllable images survive collection, (b) add a post-collection path-based noise classifier (drop static-render paths, preserve user-content/parameterized paths), applied as a curator/parser-side filter so the rule is centralized and testable rather than embedded per-tool. Note this interacts with D16 (profiling): a path filter is a coarse first cut; content-type profiling refines it.

## D16 - two-stage endpoint discovery + profiling drives downstream routing (NEW work item, may split a phase)

**Current shape:** phase 4 discovers endpoints (katana crawl, ffuf brute, gau passive) and phase 5 (arjun) plus phase-4 kiterunner/paramspider consume them - but **without any webapp-vs-webapi classification**. Every BaseURL/Endpoint is treated identically; api-specific tools (kiterunner, api-mode ffuf) fire against presentational endpoints and param tools fire indiscriminately.

**Desired shape (operator):**
1. **Discover** endpoints - crawled by katana, or brute-forced/passively harvested by ffuf/gau.
2. **Profile** each endpoint as **webapp** (HTML UI) or **webapi** (backend-exposing, e.g. JSON). Classification signals: content-type (`application/json` => api), and more generally the httpx-observable response shape. This profiling can also **prune gau noise**: many passively-harvested URLs are dead (404) and can be dropped by an httpx liveness+profile pass before they reach expensive consumers.
3. **Route by profile:**
   - **webapi** endpoints -> ffuf (configured for **API** discovery, distinct from content-discovery mode) + kiterunner.
   - **parameters** -> paramspider + arjun run on **both** classes.

**Feasibility (verified):** the profiling signal is **already collected** - the httpx parser captures `content_type` today (`httpx_parser.py:29,64`). What is missing is (a) a profiling step that persists a webapp/webapi label per endpoint (httpx is the natural home; it could also do the gau-liveness prune), and (b) a router that keys downstream `consumes` on that label rather than on the bare `Endpoint`/`BaseURL` type.

**Architectural consequence:** this likely **decomposes the current single discovery phase into two** - *discover* then *profile* - with the profile becoming a first-class asset attribute that the phase-5 (and api-specific phase-4) tools consume. This touches the phase DAG (`jobs.py` PHASES + JobSpec.consumes), so it is a structural change, not a tweak; sequence it after D14 (scope) since scope determines the endpoint population being profiled.

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

**Work item (to build): make jsluice actually analyze JS.** (a) Change the jsluice input to the discovered **JS-bundle endpoints** (the `.js` `Endpoint`s katana already produces) rather than the BaseURL root - one jsluice pod per bundle, fetching that bundle. (b) Run **both** modes per bundle (`jsluice urls` **and** `jsluice secrets`) so the `Secret` path the parser already supports is exercised. (c) Add **sourcemap (`.map`) discovery**: for each bundle, probe the conventional `<bundle>.map` (and honour `//# sourceMappingURL=` when present) and analyze the recovered original sources - sourcemaps frequently expose full source, endpoints, and secrets a minified bundle hides. This is a data-contract change (jsluice `consumes` shifts from BaseURL to a JS-Endpoint selector) and pairs naturally with D16's profiling step.

## D18 - authenticated recon: structural auth-capability typing + coverage gaps + testing (NEW work item, partially built)

**What ALREADY exists (verified, do not rebuild):** the "attribute that specifies whether a tool can execute with an authenticated context" is `JobSpec.use_auth: bool` (`types.py:43`), and the orchestrator **already detects it structurally and provides the context when the project carries it**: `pipeline.py:141` gates `extra["auth_context"] = settings["auth_context"]` on `job.use_auth and settings.get("auth_context")`; `job_agent.py:55-56` strips the auth channel from non-`use_auth` jobs; `fill_template` injects the tool-appropriate cookie flag via `{auth_header}`; and the project settings channel is validated end-to-end (`routes.py:46-64`, `_validate_auth_context` for `cookies` + `scope`). Jobs currently typed `use_auth=True`: **httpx, katana, ffuf, arjun, steel_crawl**. So katana crawling and ffuf/arjun discovery already run authenticated when the project supplies `auth_context`.

**paramspider stays unauthenticated (operator-confirmed, 2026-07-08):** paramspider is a **passive** harvester (web-archive/CommonCrawl sources); it never makes requests to the live target, so a session cookie has nothing to authenticate against. It stays `use_auth=False` by design. Active authenticated parameter discovery is arjun's role (already `use_auth=True`). No change to paramspider.

**The actual gap:**
- **The typing is binary, not "which have an authenticated *version*".** The operator's phrasing ("detect structurally which have an authenticated version of the execution") is satisfied today by the `use_auth` boolean + cookie injection - but if a tool needs a *materially different invocation* under auth (e.g. a different wordlist, an extra login-aware flag, or a distinct command_template) rather than just an added header, that is not yet expressible. If that is the intent, `use_auth: bool` should become an optional authenticated command variant (e.g. `auth_command_template`) that the configurator selects when context is present.

**Testing requirement (operator, explicit): the authenticated actions must be tested afterward.** Once the typing is settled, add tests that exercise the authenticated path end-to-end - not just that `{auth_header}` renders, but that with a real `auth_context` the auth-typed tools (httpx/katana/ffuf/arjun/steel) reach and record **authenticated-only surface** they miss unauthenticated (e.g. behind-login endpoints/parameters). This needs a target with an auth-gated area; gate the live portion on reachability the same way the existing frontend-bff live suite does (commit `d8bd8af`).
