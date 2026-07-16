# Loop State — polymerhus L1-MVP

Last run: 2026-07-16 (Model fixed; repeated e2e. FULL pipeline (bootstrap->recon->analyser) runs clean end-to-end vs live target, err=None. Caught+fixed 3 analyser-prompt/wiring defects; AGGREGATES assignments now land live. 129 mocked tests green. 5 FR areas complete + verified.)

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
| FR-ELICIT | 3 | backlog | — | Dep: FR-LCUR, FR-ANALYSER. |
| FR-ENRICH | 3 | backlog | — | Dep: FR-ELICIT. Blocked-on-unbuilt D25 (rich data-flow). |
| FR-PODSTREAM | 3 | backlog | — | Dep: FR-ANALYSER. |
| FR-TEMPLATE | 3 | backlog | — | Lands with FR-ELICIT assignment. |
| FR-SWEEP | 3 | backlog | — | Dep: FR-LCUR, FR-ELICIT. |
| FR-INDEXCARD | 3 | backlog | — | Dep: FR-LCUR, FR-ENRICH. |
| FR-SKILLIF | 4 | backlog | — | Precedes anatomy skills; may parallel storage. |
| FR-SPINE | 4 | backlog | — | Dep: FR-SKILLIF, FR-RECONREQ; config-gated on `STEEL_API_KEY`. |
| FR-AUTH | 4 | backlog | — | Precedes FR-AUTHZSKILL. |
| FR-AUTHZSKILL | 4 | backlog | — | Dep: FR-SKILLIF, FR-AUTH, FR-RECONREQ. |
| FR-NFR | cross | continuous | — | Rides every area's verifier gate + one aggregate e2e (§15 walkthrough). |

## Watch List (monitor, do not act yet)

- `STEEL_API_KEY` must be supplied before FR-SPINE can exercise the CDP taps end-to-end (config gate degrades gracefully until then).
- `LLM_MODEL_ANALYSER` + its provider key must be set before FR-ANALYSER boots if the `analyser` role is added to `ROLES` (`providers.py:14,44-57`); alternative is to reuse `job_orchestrator` (no bootstrap change).
- Integration/e2e tiers need the docker-compose stack up (`agent / kali / neo4j:5-community / pgvector:pg16`).

## Recent Noise (ignored this run)

- (none this run)

---
Run log: see `loop-run-log.md` (append-only). Latest: 2026-07-16 | Phase-0 | 5 doors ratified, plan + state seeded | escalations: 1 (checkpoint for human review).
