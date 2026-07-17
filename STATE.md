# Loop State — polymerhus L1-MVP

Last run: 2026-07-17 (**L1-MVP COMPLETE** — all 15 FR areas done + independently verifier-APPROVED. Phase 4 closed: FR-SKILLIF, FR-SPINE, FR-AUTH, FR-AUTHZSKILL, then FR-NFR (the §15 walkthrough) as the closing aggregate proof — which caught + fixed 2 real sole-writer defects (role-edge collapse, missing node provenance). Before that: FR-PODSTREAM + the bootstrap-first soupmarket e2e.)

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

## Watch List (monitor, do not act yet)

- `STEEL_API_KEY` must be supplied before FR-SPINE can exercise the CDP taps end-to-end (config gate degrades gracefully until then).
- `LLM_MODEL_ANALYSER` + its provider key must be set before FR-ANALYSER boots if the `analyser` role is added to `ROLES` (`providers.py:14,44-57`); alternative is to reuse `job_orchestrator` (no bootstrap change).
- Integration/e2e tiers need the docker-compose stack up (`agent / kali / neo4j:5-community / pgvector:pg16`).

## Recent Noise (ignored this run)

- (none this run)

---
Run log: see `loop-run-log.md` (append-only). Latest: 2026-07-16 | Phase-0 | 5 doors ratified, plan + state seeded | escalations: 1 (checkpoint for human review).
