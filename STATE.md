# Loop State — polymerhus L1-MVP

Last run: 2026-08-07 (**#94 - Session agents: stateful proposers + typed session addresses + the actor runtime, on `feat/hunting-94-session-agents`. See the amendment directly below.** Before: #29 - Bootstrapper finished for API delivery, post-MVP curation + L1 remediation, FR-STREAM (NM-7), the exhaustive soupmarket.shop e2e, and L1-MVP COMPLETE.)

## AMENDMENT 2026-08-07 - #94: session agents (semi-stateful, resumable) (branch `feat/hunting-94-session-agents`)

Ratified design: `docs/design/llm-role-architecture-agent-prompt.md` §0/§0.1 (the three-axis agent model); the reasoned-ontology home of the session concept is `domain-model.md` §3.7.

**What was built.**
1. **The role record** - `Role(role_id, model_key, agent_mode, thinking)` in `app/llm/providers.py`; `analyser` split per cognitive job (`assigner`, `mechanism_typist`, `data_modeller`, `bootstrapper`, `anatomy`, `curation`, `sweep`, `anti_cluttering`), all sharing `LLM_MODEL_ANALYSER`; hunting roles in `HUNTING_ROLES` validated at the HUNTING bootstrap, never app boot (operator ruling 2026-08-06). `validate_llm_config(roles)` parameterised.
2. **The session path** - `app/llm/session.py`: `run_session_turn` / `arun_session_turn` on `langchain.agents.create_agent` (tool_calling, `ToolStrategy` structured output, checkpointer-backed memory), plus the UBIQUITOUS `stateful_turn` every stateful agent calls. `app/llm/checkpoints.py`: the process-wide POOLED `PostgresSaver` (fail-open to shared `InMemorySaver`), opened/closed from `app/main.py`.
3. **Collision-free addressing** - `app/llm/session_address.py`: the typed `SessionAddress` Protocol + frozen dataclasses `AnalysisSession` / `PodSession` / `HuntSession` + `SessionContext`; one private `_compose` single-sources the escape/hash. The recon discriminator resolution stays in recon (`pod.py::pod_session`); app/llm never imports recon.
4. **Stateful migration** - analysis proposers (assigner/mechanism_typist/data_modeller) run `stateful_turn` on per-run threads; the recon triager runs per-concurrent-pod (PodSession via a ContextVar, leaving the 25+ injected `triage_fn` contracts untouched); the hunting hunter's author/judge/re-entry turns resume ONE per-hunt thread (`attack/hunting/llm.py::hunt_session`).
5. **Async-native parent runtime** - `app/llm/actor.py` (`AgentInbox`, `run_session_agent`, the post-call-hook delivery scaffold `inbox_post_hook` / `build_inbox_middleware`); `hunt_orchestrator.arun_orchestration` (the first async parent seam, `asyncio.to_thread` over the single-sourced O1-O10 canon). The concurrent-independent-hunts loop + cross-unit memory read are the explicit `#85`-gated follow-up.
6. **Thinking baseline** - `Role.thinking: ThinkingLevel` (hunter `high`; analysis proposers + triager + recon-orchestrator `medium`; rest `off`), applied as `reasoning_effort` on both invocation paths. The capability-adaptive adjustment is `#99`'s.

**Verification:** 1283 passed / 37 skipped (host, docker-down by design; the 5 docker-stack tests fail identically on base dev). E2e deliberately NOT run - the operator is addressing #98/#99 in another session before e2e.

**Deferred / deliberately NOT built:** no touch to StateGraph checkpoints / session / actor constructs (operator steer); compaction of the now-growing stateful context is `#98/#99` (the `middleware` seam is exposed; a long stateful run before compaction lands is a live, flagged risk); the `store` seam (`#85`) and the capability-adaptive inference-method config (`#99`) are seams only; the #73 escalating-timeout retry is NOT ported onto the session path (client per-turn retry only) - flagged robustness follow-up.

**Operator actions:** the prod base image must carry `langchain>=1.0` (pinned in `requirements-dev.txt` for host/CI test resolution; `create_agent` needs it).



## AMENDMENT 2026-07-27 - #29: Bootstrapper finished for API delivery (branch `feat/bootstrapper-service-contract`, commit 8638d3b)

Operator-driven, grilled in-session. Three tickets opened: **#29** (this work), **#30** (per-agent analysis skills roster), **#31** (B-Q2 ratification of the 4 inert prompt-prior service linchpins).

**Framing correction the operator supplied, which reframes #26's deferrals.**
The Bootstrapper is a **pre-analysis PHASE**, not a supervised analyser proposer, so #26's deferred "supervisor schedule wiring" is **moot** for this agent - its delivery seam is the **app API**, which a future frontend calls to ingest the operator's knowledge and trigger the projection.
The re-write of the attack-surface-analysis system is **gradual**: legacy superseded paths retire progressively as replacements land.

**What was actually missing** (the core two-call reasoning was built and live-verified; these were the gaps):
1. No production caller at all - `BootstrapExport.blocked` was unreachable dead code.
2. `run_bootstrap`, the ONLY settings-aware entry point, still delegated to the superseded `bootstrap_from_kb`: the example-polluted, fail-OPEN single-call path. Wiring an API route to the obvious entry point would have got the OLD agent.
3. The entire observability leg was unimplemented (no Langfuse call existed anywhere in `bootstrap.py`), and the assertion catalogue had no observability predicate - which is why 17/17 was green with the whole leg absent.
4. `run_id` unpromoted (`prov_job` was the literal `bootstrap:bootstrap`; `prov_model` always None).
5. Out-of-vocabulary System kinds silently swallowed by the sole-writer typo-guard.
6. `bounded_retry` had NO test anywhere - the #26 slice dropped the retry guard the old path had.

**`service_contract` (the operator's request).**
A brief functional profile of what a business function does and owns, in the application's own domain nouns and action verbs; the PRIMARY evidence the cross-layer Assigner consumes, matching endpoint path nouns against it.
Ratified content rule: domain nouns and verbs YES, paths/URLs/parameter names NO - the operator KB states none, so any path is the model's guess, and once persisted it is indistinguishable from evidence.
Ratified placement: composed in **call 2**, so the breadth-sensitive reasoning prompt is untouched (a prompt push once collapsed breadth 25/16/20 -> 13, commit 760e93d).
Motivating evidence: `eval-daytona` produced `byoc`, `agent-tool`, `human-access`, `declarative-builder` - opaque slugs an Assigner cannot route on.

**Skill seam (found during grilling).**
`default_reason_fn` built its system prompt from inline Python constants: the reasoned path had silently DROPPED the skill seam the superseded elicitation used, so the operator could not tune the reasoning without a code change.
Now two layers: a base prompt in code (identity + output-field contract - a structural contract with `ServiceShell` and the props allowlist) plus `skills/analysis/bootstrapper/SKILL.md` (the five stages, service-contract craft, critical withholding), with a constrained fallback for a missing mount.
The legacy `analysis/analyser` skill is wrong-shaped for the decomposed proposers and is **#30**.

**Defect caught by smoke-testing the real client, not by a test:** `propagate_attributes` sets trace ATTRIBUTES but creates no span, so every `update_current_span` / `score_current_span` was silently skipped - the same class of no-op as the `langfuse_trace_name` key the #18 recipe replaced. Fixed by also opening `start_as_current_observation`; verified exporting cleanly against the real Langfuse project.

**Corrected in my own earlier analysis (recorded because it was stated to the operator):** I claimed the 3-target eval left no reproducible artifact. It did - `eval-daytona` 26 / `eval-magnific` 25 / `eval-moodique` 18 are still queryable in Neo4j and confirm the post-fix behaviour in persisted state. That retraction is what made the **E5 breadth-regression guard** possible: it now compares against OBSERVED prior graphs rather than a number in a commit message, and fails loudly if those baselines are wiped rather than passing vacuously.

**Deliberately NOT done:** the 4 inert prompt-prior service linchpins (`account-management`, `sign-out`, `notifications`, `admin-console`) are untouched - they need operator ratification, not code (**#31**).

**Environment note (pre-existing, not this change):** `tests/test_postgres_schema.py` fails with "the database system is in recovery mode" - the known postgres crash-loop on this 3.8GiB host. `test_agent_health` / `test_stack_smoke` need the full stack up. No schema or `pg` code was touched.

## AMENDMENT 2026-07-22 - FR-JOURNEY WITHDRAWN; arjun rate cap replaces `--stable`

Two operator decisions taken after the plan closed. Everything below this block is the record of what was built and stays as written; this block is what is now TRUE.

**1. Journey grouping is WITHDRAWN and removed from the codebase.**
It was built and verifier-APPROVED (FR-JOURNEY, AST-JRNY-01) - it is retired, not failed. The reason is the AMV-15 altitude defect: in 2 of 3 FR-CURE2E runs the LLM coined journeys that grouped a single service each, which is a restatement of the service, not a grouping - and the whole adversarial rationale depends on multi-member groups. Removed in full with no shim: `CurationBatch.journeys`, `CurationReport.journeys_written`, `curation._write_journeys` + its stage (curation is now 6 stages: read -> propose -> reconcile -> anatomy -> re-home -> sweep), `l1_read.services_in_journey`, `tests/recon/test_l1_journey.py`, and the journey text in the curation/analyser skills and the model catalogue. AST-JRNY-01 and AST-CUR-02 are annotated SUPERSEDED in the plan rather than deleted. AMV-15 is folded into **AMV-11**, which is now the single durable record (removal rationale + altitude contract + ordered-promotion path).

**2. arjun uses `--rate-limit 5`, not `--stable`.**
`--stable` was proposed for the non-determinism (58 params one run, 5 the next) and REJECTED by the operator. It was the wrong fix and would have been worse than the defect: it forces threads=1 AND injects a random 3-10s delay before EVERY request, i.e. 13-43 min for the ~260 requests one URL takes - roughly 10x over `EXEC_TIMEOUT_S=300`, so every arjun pod would have timed out and the job would have yielded nothing. Measured on a local Juice Shop (`/api/Products`, 2 runs per rung): request count ~260/URL, wall-clock exactly linear in the cap - unlimited 4s, `20` 13s, `10` 26s, `5` 52s, `2` 132s - with the identical 10 parameters recovered at every rung. 5 rps gives ~6x headroom under the exec timeout while cutting the per-process burst ~13x from the unlimited default's measured ~65 rps (and, since arjun is unbatched at `MAX_PODS=20`, the aggregate against one host from ~1300 rps to ~100 rps). Caveat recorded honestly: the local target does not rate-limit, so this measured the COST of the cap, not that it fixes the flip - the causal claim still rests on the FR-CURE2E forensics. The adaptive ladder that would actually track a target's real budget is **AMV-17**.

## AMENDMENT 2026-07-22 (b) - test framework repaired; the suite is now FULLY GREEN

**Reference: `docs/design/testing-strategy.md` (tiers, discipline, how to run each). Binding rules are in `loop-constraints.md`.**

The long-standing `test_pipeline_e2e_httpx_to_arjun_prop_dependent_target` failure is FIXED, and the diagnosis previously recorded for it (in this file and in the curation plan's header) was WRONG. Correcting it here because it misled for months:

- **Recorded cause (wrong):** a hermeticity defect - the test reaches live Neo4j via `read_steering_signals`, fails open, leaves arjun unexecuted.
- **Actual cause:** the arjun template gained a `printf '{}' > … && arjun …` prefix in `77dc0c2` (the contaminated-stdout fix), while the test still dispatched and filtered on `command.startswith("arjun")`. The filter went VACUOUSLY EMPTY and the test reported `no arjun command was executed` while arjun was wired correctly all along. Same failure family as the FR-CURE2E dedup defect: a check that quietly stops checking and reports the absence of its own coverage as a product failure.
- The hermeticity leak was REAL but a separate, second bug, and fixing it alone did not make the test pass.

**What the investigation found and fixed** (all verified, see the strategy doc for the reasoning):
1. `tests/conftest.py` aimed its "safe dummy" at `bolt://localhost:7687` with password `test`. Compose PUBLISHES Bolt to the host, so the dummy hit the REAL database with wrong credentials; Neo4j's 3-strikes lockout then returned `AuthenticationRateLimit`, which reads like throttling but is wrong-password lockout. Dummies are now un-resolvable `*.invalid` hosts.
2. A unit-tier guard now RAISES on any live Neo4j access, including via the raw `_driver` (the helper-level patch alone missed `read_steering_signals`, which is how the leak hid).
3. `neo4j_live()` gated through the broken config path, returning `False` against a healthy database - so live tests skipped under a plausible "live neo4j not reachable" message. One live test in `tests/recon/test_graph_read.py` had **never executed once**; moved to `tests/integration/test_graph_read_live.py`.
4. The hardcoded `bolt://localhost:7687` + `("neo4j","polymerhus")` constant is gone from **14 files**, replaced by env-driven `tests/conftest.py::neo4j_target()` - the single source of truth, so the same file works in-network and from the host.
5. `docker-compose.dev.yml` gains a `tests` service (`profiles: [test]`) reusing the agent image, so the live tiers run INSIDE the compose network against the same service DNS the agent uses.

**Green baseline 2026-07-22:** host `tests/` = **892 passed, 37 skipped, 0 failed** (no known-failure carve-out remains); in-network `tests/integration` = **41 passed, 0 skipped** (was 32 passed / 8 skipped from the host, and those 8 skips were bogus).

**Open, flagged not fixed:** the test container is Python 3.11 vs the host venv's 3.13 (in-network-only CI would drop 3.13 coverage); and `tests/e2e/test_stack_smoke.py` runs `docker compose up -d --build`, rebuilding the stack as a side effect of a plain test run.

## Post-recon curation + L1 remediation (2026-07-19) - MVP fence DOWN, 6/7 areas APPROVED

Plan: `docs/design/post-recon-curation-and-l1-remediation-plan.md`. Model authority: `docs/design/l1-domain-model-catalogue.md`.
The operator took the MVP fence DOWN (recorded in `loop-constraints.md`), putting destructive reconciliation, `NM-1` and `NM-4` in scope for post-MVP defect remediation.

**Verifier-APPROVED and committed (2026-07-19):**

| FR area | What landed | Ledger |
|---|---|---|
| FR-INVENTORY | `l1_inventory.py::read_l1_inventory`; an un-truncated EXISTING L1 IDENTITIES block at the TOP of both analyser prompts + bootstrap elicitation. Kills synonym-slug drift at write time (the old reuse hint was toothless: identities were buried in a 400-capped slice the data pass dropped entirely). | AST-INV-01/02 |
| FR-MERGE | `l1_curator` merge / delete / relabel: idempotent, provenance-stamped, edges re-pointed never orphaned, fail-open per op, `:L1*`-only writes. | AST-MERGE-01..04 |
| FR-JOURNEY | `journeys: list[str]` on `L1Service` + `services_in_journey`; identity ⊥ membership preserved. Ordered promotion registered as AMV-11, not pre-built. | AST-JRNY-01 |
| FR-TYPESEP a+b | Prompt/skill rule (mechanism facts are System edges, never Service props) + the structural re-homing backstop in curation. | AST-TYPE-01/02 |
| FR-CURATE | `curation.py::run_curation` + `curation_types.py` + `skills/analysis/curation/SKILL.md`: propose → reconcile → journeys → anatomy → sweep → report, fail-open per stage. Driver-invoked, deliberately NOT wired into `run_pipeline` (operator decision, protects the 3.8GiB host). | AST-CUR-01..03 |
| FR-MODELFIX | The mechanism-as-System correction: ONE `WebPresentation` System carrying `rendering_model` + `navigation_model` as INDEPENDENT props via `EXPOSED_VIA`; `RENDERED_BY` and both `RenderingSystem_*` kinds deleted; `api_paradigm`/`auth_methods` re-homed off the Service. | AST-MODEL-01..04 |

**Why FR-MODELFIX exists:** review of FR-CURATE caught the re-homing inferring rendering from navigation (SPA -> CSR), violating `L1D-31a` (the dimensions are independent). Auditing the principle across the model found the identical conflation for `api_paradigm` and `auth_methods`. Only `business_function`, `exposure`, `journeys` and NL handles remain Service props.

**Green baseline at handoff:** 827 unit tests pass; 46 are this plan's tests (incl. 4 live-Neo4j integration, 0 skips); 4 frontend colour tests pass.

**One PRE-EXISTING failure, NOT curation fallout:** `tests/recon/test_pipeline_e2e.py::test_pipeline_e2e_httpx_to_arjun_prop_dependent_target` ("no arjun command was executed"). Reproduced byte-identically at `ce5e351` (the commit before this work) with `.env` present, so it predates the plan. It is separately a **hermeticity defect**: a `tests/recon/` unit-tier test reaches live Neo4j through `read_steering_signals`, which fails open and leaves arjun unexecuted, making it environment-sensitive. Quarantine-and-escalate rather than mask (see `Waiting on human`).

**Ledger drift found and corrected this run:** `STATE.md` and `loop-run-log.md` had never been updated past FR-STREAM, and every step checkbox in the plan doc sat unchecked while the per-area assertion ledgers all read green. All of it was also UNCOMMITTED. Fixed: checkboxes flipped for the six built areas, ledgers updated, work committed in nine commits. A stale FR-CURE2E assertion naming `RENDERED_BY` (deleted by FR-MODELFIX) was corrected to `EXPOSED_VIA` a `WebPresentation`.

**NOT verifier-gated (flagged, not hidden):** the `jsluice_scan.py` fix (restore the `-j` stdin flag lost in the D17 rewrite; stop TLS verification voiding every https bundle fetch) landed as an ad-hoc fix outside the plan's FR areas. Its regression tests pass, but it has had **no independent verifier pass** and no assertion-ledger entry.

## FR-CURE2E (2026-07-19/20) - RUN, 2 blocking defects found + fixed, verifier PENDING

Bootstrap-first e2e vs the DOMAIN `soupmarket.shop`, operator KB supplied by the operator (a juice marketplace described in business terms; the system stays BLIND to the by-design identity).
Three cells, sequential: A `soupcure_pro_batch` (v4-pro/batch, 1690s), B `soupcure_pro_stream` (v4-pro/streaming, 3486s), C `soupcure_flash_batch` (v4-flash/batch, 1000s). All three collected an IDENTICAL 182-endpoint L0 surface, so model/mode differences are attributable, not confounded by what recon found.

**TWO BLOCKING DEFECTS the e2e caught that unit + integration tiers could not:**
1. **Curation could not deduplicate AT ALL.** `run_curation` read its index-cards ONCE at stage 1; stage 3 merged a duplicate away, then stage 5 iterated that stale list and `commit_anatomy` MERGEd the Service back by slug. It silently undid its own dedup, reported `merged=1` truthfully-but-misleadingly, and never converged (every future run repeats forever). `reconcile` is correct in ISOLATION - which is exactly why the 4 live-Neo4j integration tests pass and never saw it. Fixed at root cause (re-read context after any destructive op); guard `test_curation_does_not_resurrect_a_merged_away_service`. Commit `10a4465`.
2. **Bootstrap had no LLM retry.** One truncated provider response zeroed the ENTIRE skeleton (`services=0`), and everything downstream ran against an empty L1 - presenting as "the weaker model cannot elicit". The analyser was hardened against this exact transient in July; bootstrap has identical exposure and was missed. Commits `423c5eb` + `c1643be` (the second closes a fail-open violation MY OWN first fix introduced: the retry returns None on exhaustion, which reached `batch.systems` and raised out of a function contracted never to crash).

**Why they were nearly missed - A and B passed A1/A2 VACUOUSLY.** Both reported `merged=0, rehomed=0`: not because reconciliation worked, but because upstream prevention (FR-INVENTORY, FR-TYPESEP-a) meant no duplicate was ever written (`mech_props_pre_curation`=0). A green assertion on a clean graph says nothing about the destructive path. This is the `stale_pool=0 is a NEGATIVE signal` lesson again, and it motivated an ADVERSARIAL dirty-graph probe (plant 2 synonym Services + 1 with stranded mechanism props, run the REAL curation): **4/4 PASS post-fix** (3 services -> 2; all 4 endpoints keep an inbound AGGREGATES so nothing orphaned; `svc_mech_props` 1 -> 0; second pass `merged=0`, was `merged=1` forever).

**Assertions:** A1 PASS, A2 PASS, A3 PASS (run A; see the journey caveat below), A4 PASS, NFR PASS, A5-controlled PASS, ADV-1..4 PASS. A5-observational FAIL with the divergence EXPLAINED (see plan §7).

**A6 (independent verifier): APPROVED 2026-07-20 - FR-CURE2E CLOSES.**
The verifier REJECTED the first submission (code sound, documentation overstated) on two counts, both correct and both fixed in `883bc92`: (1) the streaming precision table was no longer re-derivable because `a5_controlled.py` writes into run B's project and added +8 assignments AFTER the table was measured, while the text claimed every graph was still re-queryable; (2) the A3 journey claim was unqualified but holds only for run A (run B coins sentence-shaped slugs grouping one service each, run C bare phrases with no grouping) - registered as AMV-15. It then caught an arithmetic transposition in my own correction (`176 - 21 = 147` should be `168 - 21 = 147`), fixed here.
It re-derived every load-bearing number with its own Cypher and ran a counter-factual I had not: the adversarial probe against REVERTED code, reproducing the entire before-fix column including the wrongly-passing ADV-4. It confirmed all three regression guards FAIL on revert, the arjun failure pre-exists at `ce5e351`, 830 unit + 44 integration/e2e pass, and the sole-writer/denylist are clean.

**Findings the operator should act on:**
- **`LLM_MODEL_ANALYSER` is currently `deepseek/deepseek-v4-flash`, which CANNOT assign.** On the identical 182-endpoint surface: pro wrote 90 AGGREGATES (0% noise), flash wrote **0** (100% stale). Flash elicits fine (16 services) and models data fine (17 DataItems) but returns a valid, parseable, EMPTY assignment batch - 0 retry warnings, so a capability ceiling, not a provider blip. The healthy A/B results came from pro, selected per-process for the experiment. **The current .env would produce an L1 graph with zero attack-surface assignments.**
- **Streaming's extra coverage is mostly noise (NM-7's deferral question, finally MEASURED).** Batch 90 assigned / 90 business / **0% noise** / 50.5% stale vs streaming 147 assigned / 99 business / **19.7% strict, 32.7% inclusive noise** / 20.3% stale. Of streaming's 57 extra assignments, 9 are business and **48 are noise** (`/chunk-*.js`, `/ethers.js`, `/juice-shop/build/lib/*`), concentrated in `admin` (29) and `challenges` (17). Its lower stale pool was BOUGHT with over-assignment. NOTE (verifier-flagged): the run-B row is a PRE-A5-controlled snapshot and is no longer re-derivable - `a5_controlled.py` wrote +8 assignments into that project afterwards; re-measuring today gives 155/107/18.7%/31.0% (74% junk). Reconcilable exactly (168 - 21 non-Endpoint = 147 pre-A5; 176 - 21 = 155 now). The conclusion holds under either. Plus 2.6x recon wall-clock (927s -> 2421s). Mechanism is sound and provably idempotent, but streaming is NOT the quality lever it was hoped to be; batch stays the right default.
- **Host memory: the TARGET is the hog.** `eloquent_hugle` (Juice Shop) holds **1.788GiB of 3.827GiB** (47%), leaving ~0.9GiB for the whole stack. This plausibly explains all of tonight's infra failures (2 postgres recovery events, the target's own exit(133), 2 agent-container recreations). The OOM note in memory blames the agent; the dominant consumer is actually the target app. Raising the Docker allocation (or hosting the target outside the VM) would likely remove the instability.
- `business_function_slug` is stable WITHIN a project but not ACROSS runs (Jaccard 0.407 between two identical-pipeline runs; the "disjoint" sets are the same functions under different slugs) -> **AMV-12**. Plural-blind dedup normaliser (`seller-payouts` vs `seller-payout`) -> **AMV-13**. A recon job returning NOTHING is indistinguishable from one that worked (a dead target produced `success` on every job and `complete` in 39.7s with 1 endpoint, which would have been written up as a model finding) -> **AMV-14**.

**Journeys are authored at BOOTSTRAP, not curation** - a divergence from the plan's design statement, recorded rather than smoothed over. A3 holds **for run A only** (verifier-flagged): in `soupcure_pro_batch` the groups are genuine (`shopper-checkout -> [cart, checkout, delivery, orders]`), but in run B most journey slugs are full ENGLISH SENTENCES grouping a single service each, and in run C every journey is a bare phrase with no high-level grouping. `services_in_journey` agrees with stored membership in all three, but "returns sensible groups" is true only of A. Registered as **AMV-15**.

Evidence: live graphs `soupcure_pro_batch` / `soupcure_pro_stream` / `soupcure_flash_batch` / `soupcure_adversarial` are all still in Neo4j. CAVEAT (verifier-flagged): run B's PRECISION figures are NOT re-queryable - `a5_controlled.py` wrote into that project after they were measured (see the plan §7 note). Everything else re-derives. drivers + assertion scripts in the session scratchpad. Run C was NOT traced in Langfuse (run host-side; the host venv lacks the `langchain` meta-package the Langfuse callback needs, and mutating the operator's venv was not warranted).

**NEXT: the independent verifier (A6), then FR-CURE2E closes.**

Prior next-step (now superseded): FR-CURE2E (plan §7) - the only open area. Not started; no `e2e_curation.py` driver exists. Needs bootstrap-first seeding (per the operator-KB rule), recon in BOTH batch and streaming modes, `run_curation`, then the six live assertions (dedup / no mechanism props on Services / journey coherence / sweep / streaming-vs-batch convergence / independent verifier).

---

# Earlier run history (newest first)

Prior run: 2026-07-17 (**exhaustive soupmarket.shop e2e** — see below. Before: **L1-MVP COMPLETE** — all 15 FR areas done + independently verifier-APPROVED. Phase 4 closed: FR-SKILLIF, FR-SPINE, FR-AUTH, FR-AUTHZSKILL, then FR-NFR (the §15 walkthrough) as the closing aggregate proof — which caught + fixed 2 real sole-writer defects (role-edge collapse, missing node provenance). Before that: FR-PODSTREAM + the bootstrap-first soupmarket e2e.)

## FR-STREAM (NM-7 streaming analyser) - operator-pulled into scope, verifier-APPROVED (2026-07-18)

The operator observed (correctly - confirmed via code + Langfuse traces, NOT a hallucination) that the L1 attack surface was only ever built as a post-recon batch, never progressively during recon. This was BY DESIGN (L1D-23 defaults to batch; NM-7 streaming was explicitly deferred), not a bug - surfaced as a design decision rather than silently "fixed". The operator chose **Full streaming (NM-7)**, pulling it into scope.

**Built** (maker/checker, assertions authored first): `agent/recon/analysis/streaming.py::stream_analyser_step` (fail-open, stable `stream-<run_id>` id, auto-delivers observations) + a per-job hook in `agent/recon/pipeline.py` gated on `settings.recon.streaming_analysis`, run synchronously between sequential jobs (no concurrent consumer -> OOM-safe). **Batch stays the DEFAULT** (L1D-23 two-way door preserved). FR-STREAM ledger AST-STREAM-01..06 in `L1-MVP-plan.md`.

**Verified (independent verifier APPROVED):** unit 26 passed/0 skips (genuine: flag-off=>0 calls, flag-on=>1 call/producing job, fail-open, stable id); code contract confirmed (double-gate, fail-open at both layers, no persistent consumer, batch default, terminal flow intact); clean live artifact `soupstream_faf091e0` = 100% `analyser:stream-` provenance, 0 duplicate identities; scale growth `[0,77,142,143,143]` (progressive integration during recon) with idempotent convergence (services 19->19, new=[]). L1D-23's "push/pull identical writes" prediction confirmed live.

**Findings (out-of-scope-for-FR-STREAM, documented):** (1) infra flakiness on the constrained host (an exec-kill that the detached process survived; transient neo4j ServiceUnavailable blips absorbed fail-open; a hang under memory pressure) - none are streaming defects. (2) HIGH analyser run-to-run assignment variance on the SAME target (143 vs 11 aggregates) - swings between over- and under-assignment; folded into AMV-9 (the analyser confidence/quality policy) as the real lever. Streaming did NOT reduce the static-asset over-assignment noise (that's L0-crawl + confidence policy, AMV-8/AMV-9), so the original deferral's "measured noise-reduction win" is still not established.

## Exhaustive recon + attack-surface-analysis e2e (2026-07-17, project `soup_9b876a3c`)

Full production flow vs the DOMAIN `soupmarket.shop` (OWASP Juice Shop behind nginx; system blind to the local/vuln-by-design identity). Bootstrap → recon [httpx,katana,jsluice,httpx_reprofile,arjun] → analyser enrichment → sweep/index-card → interface-B → the 3 anatomy skills. `LLM_MODEL_ANALYSER=deepseek/deepseek-v4-pro`.

**The formal bar is MET + un-cheated** (independent verifier ran it all itself): **172** code-level ASA assertions pass (0 skips) + **50 live-graph** FR/NFR assertions across all 15 FR areas — FR-ELICIT 7/7, FR-{PODSTREAM,ANALYSER,ENRICH,TEMPLATE,SWEEP,INDEXCARD,RECONREQ,NFR} 26/26, FR-{SPINE,AUTH,AUTHZSKILL} 17/17. Verified live: 18 well-named DataItems, 9 CONSUMES all with adversarial Tier-1 trust assumptions, 37 typed system-edges, AGGREGATES all `analyser:`-provenance with the full L1D-25 envelope, sole-writer + `__singleton__` + no-`:SystemAspect` (MVP fence) all hold; FR-SPINE two independent SPA/CSR slots; FR-AUTHZSKILL real guest(401)/shopper(200) pyramid → `AUTHORIZED_BY{shopper}`/`AUTHENTICATED_BY{jwt}`, guest→no edge.

**Verifier REJECTED my first certification** — correctly — then **APPROVED after I corrected it** (maker/checker held; not self-approved). My first "anomaly (B)" narrative was materially false (claimed "3 noise endpoints, web-frontend only, business services unpolluted"). Truth (independently reconfirmed by me + the verifier): **58/182 (31%) assigned Endpoints are noise across 5 services** — web-frontend 23, file-server 18 (mostly `node_modules` source), web3-wallet 13 (incl. `soljson` compiler blobs + `ethers.js`), ctf-challenges 3, recycling 1. (58 is a conservative floor; an inclusive static-asset+source classifier counts ~70/182 ≈ 38% — classifier-boundary, same direction.) `stale_pool=0` here vs **79** on the prior weaker-model run: **a stronger model over-assigns → worse discipline** without a confidence policy; empty stale pool is a NEGATIVE signal here.
- Anomaly (A) (`endpoint_template` collapsed 0 ids) IS a true non-defect: 0 concrete numeric/uuid path segments exist in a blind SPA crawl — nothing to collapse (verifier-confirmed).
- Root cause is two-layer, both OUTSIDE the MVP fence: L0 crawl/parse noise (katana crawling `node_modules`/ftp, bundles/chunks/soljson as endpoints, jsluice concat fragments) = **AMV-8**; L1 lacks an assignment-confidence/stale policy (**L1OP-5**, explicitly deferred) = **AMV-9**. No in-scope FR/NFR assertion fails (assignment faithfulness is L1OP-5). Both AMVs registered with live evidence in `after-mvp-work-items.md`.
- Correction re-verified by the same checker (maker/checker preserved; not self-approved).

## L1-MVP COMPLETE (2026-07-17)

All 15 FR areas built + verified by a separate adversarial verifier each: FR-LCUR, FR-RECONREQ, FR-ANALYSER, FR-ELICIT, FR-ENRICH, FR-PODSTREAM, FR-TEMPLATE, FR-SWEEP, FR-INDEXCARD (Phase 1-3); FR-SKILLIF, FR-SPINE, FR-AUTH, FR-AUTHZSKILL, FR-NFR (Phase 4 + cross-cutting). The §15 walkthrough (FR-NFR) proves every in-scope primitive fires end-to-end through the real writers on live neo4j with all invariants holding. Remaining work is all explicitly deferred (NM-n / L1OP engines / Stage-3 / the AMV-1..7 after-MVP registry). Commits on feat/attack-surface-analysis.

## FR-PODSTREAM (2026-07-17) — analyser delivery/completeness, verifier-APPROVED

The last open Phase-3 area. Goal (L1D-22/23, batch-default): the analyser `f(L0-slice+observations)` PULLS a complete, non-duplicating input. **Gap closed**: triager Observations were only incidentally visible (buried in the slice), the dedicated `observations` input was always empty post-recon, and adding a channel would double-deliver. **Fix** (pull-side only; NO streaming — NM-7 stays deferred; NO auto-trigger in run_pipeline — the caller still triggers analysis):
- `agent/recon/analysis/delivery.py` — `collect_observations(project_id)` id-deduped + `deliver_observations` fail-open wrapper.
- `default_read_fn` excludes Observation nodes (+ dangling edges) from the analyser slice.
- `run_analyser` auto-delivers observations when `observations is None`; honours an explicit list as-is.
Assertions AST-PODSTREAM-01..05 green (7 unit + 1 integration on live neo4j). Independent verifier ran all tests itself (32 unit, 1 integration confirmed not-skipped, 94 regression), live spot-check obs=13/obs_in_slice=False, MVP fence held. Fixed the one regression it flagged: 4 analyser unit tests were silently touching live neo4j via auto-delivery — now pass `observations=[]` to stay hermetic (suite 1.80s→0.28s).

## Bootstrap-first e2e (2026-07-17) — operator-KB-seeded, the realistic flow

Ran the operator-KB-seeded flow the 2026-07-17 correction demanded (project `soupbf_14ec2e3e`): operator_kb (NL "open soup market" description) -> `bootstrap_from_kb` -> recon [httpx, katana, jsluice, httpx_reprofile, arjun] over the DOMAIN soupmarket.shop -> `run_analyser` to ENRICH the seeded skeleton.

- **Phase 1 (FR-ELICIT) GREEN**: bootstrap seeded 19 business Services + 5 Systems (2 linchpin auth + RESTApi/IdentificationSystem/RenderingSystem_SSR_UI, all canonical vocab), 0 AGGREGATES, 0 L0 refs, all `__singleton__` + bootstrap provenance.
- **Phase 2**: recon produced a rich surface (Endpoint x183, Header x13, Parameter x5; jsluice recovered 543 raw assets this run, vs 0 before).
- **Phase 3 (enrichment)**: analyser FAITHFULLY enriched the seeded skeleton — 10/19 seeded Services assigned by their EXACT slug (sign-in got 21 auth endpoints /login /register /rest/user/login /2fa/enter …; product-introspection 8; orders 7). The 8 "new" Services (web3-wallet, photo-wall, memories, recycling, gamification, admin, file-server, chatbot) are GENUINE discoveries of surface the operator KB never described, NOT duplication drift. **Correction**: the phase-3 script's crude enrichment_ratio<0.70 threshold mislabels legitimate discovery as "drift"; faithfulness = reuse-of-seeded-slug (confirmed) + no duplicate identities (confirmed), not ratio.

### Defect found + fix (DataItems=0) — RESOLVED, live-GREEN
- **Defect**: FR-ENRICH produced **0 DataItems / 0 flows** (prior from-scratch run made 10). Root-caused with an `include_raw` probe: `finish_reason=tool_calls` (NOT a token cutoff) with 150 aggregates + 90 system_edges, 0 data_items — the single "do everything" LLM call systematically **deprioritises data modelling under assignment load** (task interference). Reproduced on 2 independent calls.
- **Fix 1 — two-pass split** (`agent/recon/analysis/pod.py`): `default_analyse_fn` → `_two_pass_analyse(invoke_fn, …)`: pass 1 = services/systems/aggregates/system_edges, pass 2 = a DEDICATED data-modelling call, merged (pass-2 contributes ONLY the 4 data lists). Pass-2 input is an IDENTITY-ONLY surface digest (`_compact_l0_for_data`) — the full-node dump ballooned the prompt to ~123k chars and pass-2 timed out.
- **Fix 2 — bounded retry** (`_invoke_with_retry`, attempts=3): OpenRouter/deepseek intermittently returns truncated JSON (`JSONDecodeError`) on the large assignment response, or a None structured result; a single None was zeroing the WHOLE analyser. Retry recovers it. Fail-open after 3.
- **Fix 3 — positive, example-led data prompt** (the key fix for the weaker model): the operator switched the analyser to a **less reasoning-capable model** (2026-07-17); it returned `args={'services':[],…}` — anchoring on the OLD prompt's NEGATIVE framing ("leave the other lists EMPTY") and emitting zero data_items. Reframed the data prompt as a POSITIVE recipe with a concrete WORKED EXAMPLE, a "you MUST return ≥1 data_item" directive, a valid controlled `kind` in the example, and a "copy service_slug VERBATIM" rule (stops orphan services). Aligns with writing-skills "match the form to the failure": a shaping failure needs a recipe, not a prohibition.
- **Live re-test GREEN** (`e2e_bf_phase3b.py`, reset analyser writes / keep seeded skeleton + L0 / re-run): **17 DataItems, 26 SURFACES_AT, 34 data_flows, 17 data_relationships**, all faithful + well-named, with genuinely adversarial Tier-1 trust assumptions ("checkout must not trust client-side basket state"; "tracking lookup must enforce only the order owner can query" = IDOR; "web3 sandbox must not allow cross-user wallet access"). ALL 8 FR/NFR assertions PASS; **no duplicate services (0 dups)** — the copy-verbatim rule prevented orphan-service drift. 92 aggregates, enrichment_ratio 0.70, 10/19 seeded services enriched, 5 legit new discoveries (admin-panel, ctf-platform, photo-wall, recycling, web3-sandbox).
- **Unit tests GREEN**: 25 analyser-pod (two-pass + retry + compact-prompt + positive-recipe guards) + 87 L1 unit tests total.
- **Infra note**: Docker Desktop's VM faulted mid-run (I/O errors on the constrained host after heavy LLM+exec load); `docker compose up` without the dev overlay dropped the `./agent` bind mount (ran the stale baked image) — must restart with `-f docker-compose.yml -f docker-compose.dev.yml`. neo4j/postgres volumes survived; the seeded skeleton + L0 surface persisted intact.
- **L0 recon-parser noise (separate subsystem, flag not fix)**: the stale pool holds junk "endpoints" — `/'+_(i[8])+'`, `/{{href}}`, `/Zone.js`, `/chunk-*.js` — jsluice/katana surfacing JS fragments + Angular bundles as endpoints. Recon-layer, not L1; candidate AMV.

## Post-verification changes to already-APPROVED areas (re-verification offered)

The live full-pipeline e2e (after the operator fixed LLM_MODEL_ANALYSER) caught 3 real defects that the mocked verifier suites could not, all fixed + regression-guarded:
1. **Vocabulary miss** (FR-ANALYSER/FR-ELICIT): LLM proposed non-canonical SystemKinds ('Authentication'), silently dropped. Fix: `l1_curator.vocabulary_prompt()` injected into analyser + bootstrap prompts. Guard: `test_vocabulary_prompt_lists_controlled_values`.
2. **Enrichment not wired** (FR-ANALYSER): default analyser graph wrote only core deltas, not FR-ENRICH. Fix: unified curate contract `curate_fn(batch, project_id, provenance)` + `default_curate_with_enrichment_fn` as default; 5 analyser tests updated to new signature.
3. **L0-label mislabel** (FR-ANALYSER): LLM put a URL in `AGGREGATES.l0.label`; safe-label guard dropped the assignment. Fix: `_L0_REFERENCE_GUIDE` (label=node type + per-label identity keys) in the analyser prompt. Guard: `test_l0_reference_guide_teaches_label_is_node_type`.
These are net-additive (prompt content + a curate-contract refactor); all 129 mocked tests green. A combined re-verification of FR-ANALYSER + FR-ELICIT + FR-ENRICH on the changed surface is available on request.

This is the FR-area backlog + assertion-ledger status + what is waiting on a human.
The full plan and the FR-LCUR ledger live in `docs/design/L1-MVP-plan.md`.
The binding guardrails live in `loop-constraints.md`.

## High Priority (loop is acting or waiting on human)

- [x] Phase-0 plan approved by human (2026-07-16). Caveats applied: `LLM_MODEL_ANALYSER` in scope (FR-ANALYSER adds the `analyser` role); NL solution architecture via `settings.recon.operator_kb`, wider target-system doc ingestion deferred.
- [x] AGGREGATES cross-layer ref encoding (one-way door) — first implemented as option B (reified ref node), then **rolled back to option A (native `(:L1Service)-[:AGGREGATES {envelope}]->(:L0)` edge)** after operator's critical review invalidated option B's rationale (shared-L0 chaining is unsound; see `docs/design/L1-MVP-plan.md` §5 note). Re-implemented + re-verified.
- [x] **FR-LCUR DONE — verifier-APPROVED (2026-07-16), then B→A refactor re-run green.** 10/10 assertions green; 27 tests (unit + integration) + L0 regression clean. Independent verifier ran the suite itself, grep-confirmed the sole-writer, fired a live violating-CREATE to confirm enforcement. Its 3 non-blocking follow-ups all addressed. B→A refactor adds `test_aggregates_missing_l0_target_is_noop` (proves l1_curator never creates L0 nodes) and re-verification is pending on the changed surface.
  Minor decision taken with judgment (two-way): `SystemKind` keyed per-project `(id, project_id)` for tenant uniformity; noted in `l1_curator.py`.
- [ ] Human comprehension-debt review of the FR-LCUR diff is available whenever wanted; not blocking — proceeding to FR-RECONREQ after the option-A re-verification.
- [ ] **OPERATOR ACTION (before next app restart) — set `LLM_MODEL_ANALYSER` in `.env`.** FR-ANALYSER added `analyser` to `ROLES`, so `validate_llm_config` now requires `LLM_MODEL_ANALYSER=openrouter:<stronger-model>` (+ its provider key) at boot; without it the agent will fail-fast on startup. Operator chose a dedicated role + stronger model (2026-07-16). Tests mock the LLM so the test suite is unaffected; only a real app boot needs the env var.
- [x] **Analyser meta-reasoning skill wired (2026-07-16):** `skills/analysis/analyser/SKILL.md` synthesises `overthink` + `critical-thinking-logical-reasoning` for the analyser's task; loaded via `_load_analyser_skill` (graceful degrade). Domain-specific service-dissection meta-reasoning skill documented as after-MVP item AMV-1 in `docs/design/after-mvp-work-items.md`.
- [x] **Live e2e PASSED (2026-07-16):** `request_targeted_recon` (interface B) run host-side vs `app.onlineorders.com` (DVWA-style PHP app) for httpx (13 assets/4 obs) + katana (12 assets/4 obs) — full chain kali-exec→parse→LLM-triage→curator→neo4j, correct project scoping, registry row persisted. **Caught + fixed a real bug**: `request_targeted_recon` didn't propagate `project_id` into the pod (`extra["project_id"]`), orphaning L0 nodes under run_id; fixed + regression-guarded (`test_targeted.py`). FR-RECONREQ suite 12/12 green after fix.
- [ ] Note: the targeted.py fix is a post-verification change to the (already-APPROVED) FR-RECONREQ area — minimal (1 line + guard test), live-validated by the e2e. Re-verification available on request; see AMV-3 for the off-scope-ingestion follow-up.

## Waiting on human

- [ ] **Flaky/non-hermetic test — quarantine decision needed (2026-07-19).** `tests/recon/test_pipeline_e2e.py::test_pipeline_e2e_httpx_to_arjun_prop_dependent_target` fails in the unit tier because it reaches live Neo4j via `read_steering_signals`. Pre-existing (reproduces at `ce5e351`), so it blocks nothing, but per the no-flake-masking rule it should be fixed properly (inject a fake `read_steering_signals` so the tier is hermetic) rather than retried or weakened. Wants an operator call on whether to fix now or defer as an AMV.
- [ ] **Un-gated fix awaiting a verifier pass (2026-07-19).** The `jsluice_scan.py` fix (commit `58ae4b6`) landed outside the plan's FR areas with no assertion ledger and no independent verifier. Offer: fold it into the FR-CURE2E verifier pass, or gate it separately.
- [ ] **FR-CURE2E is the next area and needs a live target + budget.** It re-runs the full pipeline plus curation against `soupmarket.shop`, in both batch and streaming modes. Prior runs on this host hit memory pressure and Docker VM faults, so confirm the operator wants it started before it burns the budget.
- (resolved 2026-07-16) `LLM_MODEL_ANALYSER` model ID fixed by operator. Live bootstrap smoke now works (9 services elicited + 2 linchpin systems, no L0 refs). Live analyser reasoning unblocked.
- [ ] **Next e2e must be operator-KB-seeded (bootstrap-first), not from bare surface** (operator correction 2026-07-17). The soupmarket e2e ran the analyser over the bare L0 surface (no operator_kb, no bootstrap) so it elicited services from scratch — unrealistic. Operator will provide a NL "open soup market" solution description before the next e2e; then: set settings.recon.operator_kb -> bootstrap_from_kb -> recon -> run_analyser (assert it enriches the seeded skeleton). See memory [[e2e-operator-kb-seeding]]. Current from-scratch results accepted as sufficiently accurate for now.

## Operator decisions (2026-07-16, resuming the loop)

- [x] `LLM_MODEL_ANALYSER` set in `.env` (operator). Analyser role boot-gate satisfied; live-LLM analyser work unblocked.
- [x] **FR-ELICIT operator_kb = free-text NL** for now. A pre-defined template + typed-service-contract framework is a later enhancement → captured as after-MVP item AMV-4.
- [x] **FR-ENRICH DataItem = implement flexible identity + vocabulary NOW** (operator overrode the deferred-partial path; `L1OP-1`/`L1OP-2` pulled into MVP scope). Design: semantic `item_key` identity with `identity ⊥ membership`; DataRelationship vocabulary as an extensible catalogue (SystemKind pattern) carrying predicate + NL rationale.

## FR-area backlog (bounded goals; one worktree each; verifier-gated)

Status ∈ {backlog | in-progress | verifier-review | done | blocked}.
Order follows the staged build order; do not start a second area until the first is verifier-APPROVED.

| FR area | Phase | Status | Assertions green / total | Notes |
|---|---|---|---|---|
| FR-LCUR | 1 | **DONE (verifier-APPROVED, option-A re-verified)** | 10 / 10 | l1_schema, l1_types, l1_curator (native-edge AGGREGATES, option A), l1_read. 27 tests green; L0 regression + denylist clean; no option-B artifacts remain in code. |
| FR-RECONREQ | 2 | **DONE (verifier-APPROVED)** | 4 / 4 | targeted.py (AnalyserReconRequest + request_targeted_recon), pg ensure/record/get, recon_jobs ALTER (init.sql + runtime ensure), main.py startup. 12 tests green; verifier ran integration on live DB, denylist clean. |
| FR-ANALYSER | 3 | **DONE (verifier-APPROVED)** | 5 / 5 | analyser role; pod.py (read→analyse→curate subgraph, fail-open); analyser_types.py (proposals + L1DeltaBatch, provenance injection). 10 tests green; verifier ran integration on live neo4j. NEEDS operator .env: LLM_MODEL_ANALYSER before app restart. |
| FR-ELICIT | 3 | **DONE (verifier-APPROVED)** | — | bootstrap.py: operator_kb (free-text) → Service skeleton + linchpin auth Systems, no L0 refs, idempotent, fail-open. 10 tests green; live fail-open confirmed. |
| FR-ENRICH | 3 | **DONE (verifier-APPROVED)** | — | DataItem flexible identity (project_id,item_key) + extensible DataRelationship vocabulary + PRODUCES/CONSUMES(assumption)/SURFACES_AT/system-edges. 20 tests green. Operator pulled L1OP-1/L1OP-2 into MVP. |
| FR-PODSTREAM | 3 | **DONE (verifier-APPROVED)** | 5 / 5 | delivery.py (collect_observations id-deduped + deliver_observations fail-open); default_read_fn excludes Observation nodes from the analyser slice (no double-delivery); run_analyser auto-delivers observations when caller passes none. 7 unit + 1 integration (live neo4j) green; verifier ran all itself, live spot-check obs=13/obs_in_slice=False, MVP fence held (pull-only, no streaming). Fixed a hermeticity regression it flagged (4 analyser unit tests now pass observations=[]). |
| FR-TEMPLATE | 3 | **DONE (verifier-APPROVED)** | — | endpoint_template(path) collapses numeric/uuid segments to {id}, written on the AGGREGATES edge at assignment (L1D-32/door D5). 10 unit + 1 integration green. |
| FR-SWEEP | 3 | **DONE (verifier-APPROVED)** | — | sweep.stale_pool/stale_pool_count (no-inbound-AGGREGATES derived query) + missing_system_kinds over the SystemKind registry (L1D-24). 6 unit + 2 integration green; live-confirmed on soupmarket. |
| FR-INDEXCARD | 3 | **DONE (verifier-APPROVED)** | — | index_cards token-light projection (edge-degree by family, not member set) + dfs_down one typed hop (L1D-27/DD-4). 6 unit + 3 integration green; DD-4 proven (10k members <500B). |
| FR-SKILLIF | 4 | **DONE (verifier-APPROVED)** | 5 / 5 | agent/recon/skills.py::skill_for(name, fallback) — one loader (load skills/<name>/SKILL.md, strip frontmatter, cache, degrade to fallback); _load_triager_skill + _load_analyser_skill retro-pointed at it (L1D-31/door D4). 9 unit + 25 analyser + 36 regression green; verifier confirmed byte-for-byte frontmatter parity, no removed-global refs, MVP fence held (no anatomy triple smuggled in). |
| FR-SPINE | 4 | **DONE (verifier-APPROVED)** | 6 / 6 | agent/recon/analysis/anatomy.py — the anatomy-skill triple contract (SpineClassification/AnatomyResult) + the webpage-profile skill: navigation_model ⟂ rendering_model as INDEPENDENT slots, L1D-31a fingerprint-insufficiency enforced STRUCTURALLY (fingerprint-only -> Low + forced probe, verifier proved High+fp->Low in code), triple lands (classification->Service spine props via l1_curator, evidence->Observation, probe->interface-B origin=anatomy_skill). SKILL.md at skills/analysis/anatomy/webpage-profile. Config-gated on STEEL_API_KEY (probe emitted regardless; live CDP capture deferred). 10 unit green; verifier confirmed structural cap unbypassable, sole-writer + MVP fence held. Addressed 3 non-blocking notes: cap fp-only to Low (not just below High); added ReconScope.note carrying probe reason + triggering slots. |
| FR-AUTH | 4 | **DONE (verifier-APPROVED)** | 6 / 6 | agent/recon/auth.py::select_auth_context — role/realm-tagged auth_context (roles.<role> + default_role + per-set realm) with a per-request selector; used at the pipeline use_auth injection so `roles` never leaks. Validation recurses into each role (same per-set rules); structural keys reserved in BOTH the API validator and the pod header serialiser (realm/default_role are strings — would leak if either set were incomplete). 11 unit + 1 live-pg integration (jsonb_deep_merge preserves sibling roles) green; verifier live-confirmed only Cookie+Authorization headers emitted, 85-test regression clean, backward-compat holds. L1OP-6 pyramid schema stays deferred to FR-AUTHZSKILL. |
| FR-AUTHZSKILL | 4 | **DONE (verifier-APPROVED)** | 6 / 6 | authorization-pyramid anatomy skill (agent/recon/analysis/anatomy.py: plan_authz_probes + classify_authz; AnatomyResult+commit_anatomy gain the system_edges leg). Inverse-pyramid: one interface-B probe per role carrying that role's SELECTED creds (select_auth_context); authorised roles -> AUTHORIZED_BY {role} typed edges (to AuthorizationSystem), denied -> none; AUTHENTICATED_BY {realm} per realm (to AuthenticationMechanism); mechanism/policy separate (L1D-5). Written STRUCTURALLY via the l1_curator sole-writer (reuses FR-ENRICH's build_system_edge_cypher). SKILL.md at skills/analysis/anatomy/authorization-pyramid. 7 unit + verifier's 5 live-neo4j enrich integration green; verifier confirmed denied->no-edge structural, sole-writer + MVP fence held (records who CAN, not who SHOULD). |
| FR-NFR | cross | **DONE (verifier-APPROVED)** | 7 / 7 | tests/e2e/test_walkthrough_nfr.py — the §15 walkthrough fires every in-scope primitive through the REAL writers on live neo4j + asserts all cross-cutting invariants (idempotency, __singleton__ vs populated discriminator coexist, provenance on every node+edge, identity ⊥ membership, sole-writer static grep, MVP fence). Caught + fixed TWO real sole-writer defects: (1) system-edge MERGE keyed on rel only -> multiple AUTHORIZED_BY{role} edges collapsed (last role wins); fixed by folding non-null role/realm into the MERGE key. (2) secondary writers minted L1 nodes with no prov_job; fixed with ON CREATE node-provenance (preserves a primary writer's prov). 7 e2e + regression guards green; verifier ran full sweep (708 passed). |
| FR-STREAM | post-MVP | **DONE (verifier-APPROVED)** | 6 / 6 | streaming.py::stream_analyser_step + a per-job pipeline hook gated on settings.recon.streaming_analysis; analyser fed each job's surface DURING recon, run synchronously between sequential jobs (OOM-safe, no concurrent consumer). Batch stays DEFAULT (L1D-23 two-way door). Live: 100% analyser:stream- provenance, 0 dup identities, growth [0,77,142,143,143] with idempotent convergence. Committed 5fec65b. |
| FR-INVENTORY | curation | **DONE (verifier-APPROVED)** | 2 / 2 | l1_inventory.py::read_l1_inventory (services/systems/data-items, sorted+deduped, fail-open) + an un-truncated EXISTING L1 IDENTITIES block at the TOP of both analyser prompts and bootstrap elicitation. Fixes synonym-slug drift at WRITE time. Committed 43a8629. |
| FR-MERGE | curation | **DONE (verifier-APPROVED)** | 4 / 4 | l1_curator merge/delete/relabel + reconcile: idempotent, provenance-stamped, edges re-pointed never orphaned, fail-open per op, :L1*-only (never an L0 write). Destructive reconciliation permitted in l1_curator ONLY. Committed c782df6. |
| FR-JOURNEY | curation | **DONE (verifier-APPROVED)** | 1 / 1 | journeys: list[str] on L1Service + services_in_journey; membership never keys identity (L1D-11). Ordered promotion registered as AMV-11, not pre-built (two-way: the prop is a subset of that model). Committed a5b05f6. |
| FR-TYPESEP | curation | **DONE (verifier-APPROVED)** | 2 / 2 | (a) prompt/skill rule: mechanism facts are System edges, never Service props, with the Stage-3 DFS rationale. (b) structural re-homing backstop in curation. Committed 43a8629 + b39d20b. |
| FR-CURATE | curation | **DONE (verifier-APPROVED)** | 3 / 3 | curation.py::run_curation + curation_types.py + skills/analysis/curation/SKILL.md: propose -> reconcile -> journeys -> anatomy -> sweep -> report, fail-open per stage. Driver-invoked; deliberately NOT wired into run_pipeline (operator decision, protects the 3.8GiB host). Committed b39d20b. |
| FR-MODELFIX | curation | **DONE (verifier-APPROVED)** | 4 / 4 | The mechanism-as-System correction (catalogue doc is authoritative): ONE WebPresentation System carrying rendering_model + navigation_model as INDEPENDENT props via EXPOSED_VIA; RENDERED_BY + both RenderingSystem_* kinds deleted; the SPA->CSR inference deleted (violated L1D-31a); api_paradigm/auth_methods re-homed off the Service. Committed c782df6. |
| FR-CURE2E | curation | **OPEN — the only remaining area** | 0 / 6 | NOT STARTED; no e2e_curation.py driver exists. Bootstrap-first seeding -> recon (batch AND streaming) -> run_curation -> assert dedup / no mechanism props on Services / journey coherence / sweep / streaming-vs-batch convergence -> independent verifier. Plan §7. |

## Watch List (monitor, do not act yet)

- `STEEL_API_KEY` must be supplied before FR-SPINE can exercise the CDP taps end-to-end (config gate degrades gracefully until then).
- `LLM_MODEL_ANALYSER` + its provider key must be set before FR-ANALYSER boots if the `analyser` role is added to `ROLES` (`providers.py:14,44-57`); alternative is to reuse `job_orchestrator` (no bootstrap change).
- Integration/e2e tiers need the docker-compose stack up (`agent / kali / neo4j:5-community / pgvector:pg16`).

## Recent Noise (ignored this run)

- (none this run)

---
Run log: see `loop-run-log.md` (append-only). Latest: 2026-07-16 | Phase-0 | 5 doors ratified, plan + state seeded | escalations: 1 (checkpoint for human review).
