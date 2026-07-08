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
