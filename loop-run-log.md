# Loop Run Log — polymerhus L1-MVP

Append one entry per iteration. Prune entries older than 30 days.

## Format

```json
{
  "run_id": "2026-07-16T00:00:00Z",
  "fr_area": "FR-LCUR",
  "attempt": 1,
  "assertions_green": 0,
  "assertions_total": 10,
  "tokens_estimate": 0,
  "escalations": 0,
  "outcome": "report-only | in-progress | verifier-review | approved | escalated | no-op"
}
```

## Recent Runs

<!-- Loop appends below this line -->

```json
{
  "run_id": "2026-07-16T-analyser-skill-and-e2e",
  "fr_area": "FR-ANALYSER-config + e2e",
  "attempt": 1,
  "assertions_green": null,
  "assertions_total": null,
  "tokens_estimate": 1250000,
  "escalations": 1,
  "outcome": "done",
  "notes_franalyser_config": "see below entry for FR-ELICIT/FR-ENRICH",
  "notes": "Operator-directed work: (1) Wired overthink + critical-thinking-logical-reasoning into the analyser via skills/analysis/analyser/SKILL.md + _load_analyser_skill loader (graceful degrade); 3 loader unit tests. (2) Created docs/design/after-mvp-work-items.md registry: AMV-1 = domain-specific service-dissection meta-reasoning skill (merges architecting-solutions + define-hypothesis + reverse-engineering meta-questions/hypothesis/verification, ties to interface B); AMV-2 = bake skills/analysis into image; AMV-3 = scope filtering for targeted recon. (3) LIVE E2E of request_targeted_recon vs app.onlineorders.com (DVWA-style PHP/nginx app, reached via kali extra_hosts->host-gateway->nginx): httpx (13 assets/4 obs) + katana (12 assets/4 obs) both status=success through the full kali-exec->parse->LLM-triage->curator->neo4j chain; registry row persisted (origin/requester/phase=-1). CAUGHT+FIXED a real bug: request_targeted_recon didn't set extra['project_id'] so the pod (job_agent.py:213 extra.get('project_id', run_id)) wrote L0 nodes under run_id, orphaning them; fixed (1 line) + regression guard in test_targeted.py. 100-test consolidated regression green. Escalation: operator must set LLM_MODEL_ANALYSER before app boot."
}
```

```json
{
  "run_id": "2026-07-16T-frlcur-a1",
  "fr_area": "FR-LCUR",
  "attempt": 1,
  "assertions_green": 8,
  "assertions_total": 10,
  "tokens_estimate": 210000,
  "escalations": 1,
  "outcome": "in-progress",
  "notes": "Implemented l1_schema (3 constraints), l1_types, l1_curator sole-writer (Service/System/SystemKind builders + seed). 14 unit + 7 integration tests green against live neo4j:5.26; L0 regression unaffected (13 passing). Blocked on AGGREGATES cross-layer-ref encoding (AST-LCUR-04/05) — one-way door escalated to human with options A/B/C, recommend A."
}
```

```json
{
  "run_id": "2026-07-16T-frlcur-a2",
  "fr_area": "FR-LCUR",
  "attempt": 1,
  "assertions_green": 10,
  "assertions_total": 10,
  "tokens_estimate": 360000,
  "escalations": 1,
  "outcome": "approved",
  "notes": "Operator chose AGGREGATES option B (reified :L1AggregatesRef + HAS_AGG_REF, MERGE on ref_key hash). Added build_aggregates_cypher/write_aggregates + l1_read.read_aggregated_l0 (traversal-then-fetch). Full suite 26 tests green (18 unit + 8 integration). Independent verifier (separate sub-agent) APPROVED: ran the suite itself, grep-confirmed sole-writer, live violating-CREATE confirmed constraint enforcement. 3 non-blocking follow-ups addressed (enforcement test, stale docstrings, SystemKind provenance). FR-LCUR DONE."
}
```

```json
{
  "run_id": "2026-07-16T-frlcur-a3",
  "fr_area": "FR-LCUR",
  "attempt": 1,
  "assertions_green": 10,
  "assertions_total": 10,
  "tokens_estimate": 520000,
  "escalations": 0,
  "outcome": "refactor-reverify",
  "notes": "AGGREGATES rolled back B->A after operator critical review invalidated option B (shared-L0 chaining unsound). Removed :L1AggregatesRef/HAS_AGG_REF/ref_key/l1aggref_unique; build_aggregates_cypher now MERGEs native (:L1Service)-[:AGGREGATES {envelope}]->(:L0), MATCHing (never creating) the L0 target; l1_read traverses the edge. Added test_aggregates_missing_l0_target_is_noop. Full suite 27 tests green + L0 regression clean. Plan §1/§5 + STATE updated to option A. Focused re-verification of the changed surface pending."
}
```

```json
{
  "run_id": "2026-07-16T-frreconreq-a1",
  "fr_area": "FR-RECONREQ",
  "attempt": 1,
  "assertions_green": 4,
  "assertions_total": 4,
  "tokens_estimate": 700000,
  "escalations": 0,
  "outcome": "implemented-verify-pending",
  "notes": "Interface agreement B. New agent/recon/targeted.py: AnalyserReconRequest/ReconScope/TargetedReconResult + request_targeted_recon (reuses run_job outside phase barrier at TARGETED_PHASE=-1, persists recon_jobs w/ correlation/requester/origin, fail-open, sync in-process return). pg.py: ensure_recon_schema (idempotent runtime migration), record_targeted_job, get_job_by_correlation. init.sql idempotent ALTER recon_jobs. main.py startup calls ensure_recon_schema + ensure_l1_schema. 9 unit + 3 integration green; 82-test cross-module regression green; app import smoke OK. Decision (two-way): pg columns applied via init.sql (fresh) + runtime ensure (live self-heal). Independent verifier pass next."
}
```

```json
{
  "run_id": "2026-07-16T-frreconreq-a2",
  "fr_area": "FR-RECONREQ",
  "attempt": 1,
  "assertions_green": 4,
  "assertions_total": 4,
  "tokens_estimate": 780000,
  "escalations": 0,
  "outcome": "approved",
  "notes": "Independent verifier (separate sub-agent) APPROVED: ran 9 unit + 3 integration (live PG+Neo4j, NOT skipped) + 39-test regression itself; verified all 4 assertions in code (one run_job at phase -1, correlation upsert, idempotent ingest via sanctioned curator count==1, 3 fail-open paths), migration idempotent, denylist (curator.py/schema.py) untouched. Non-blocking note: neo4j_client.py bundles ensure_l1_schema wiring (anticipated by the main.py task). FR-RECONREQ DONE. Phases 1-2 complete (FR-LCUR + FR-RECONREQ). Pausing for FR-ANALYSER design checkpoint (LLM role config + delta schema)."
}
```

```json
{
  "run_id": "2026-07-16T-franalyser-a1",
  "fr_area": "FR-ANALYSER",
  "attempt": 1,
  "assertions_green": 5,
  "assertions_total": 5,
  "tokens_estimate": 950000,
  "escalations": 1,
  "outcome": "implemented-verify-pending",
  "notes": "Operator chose dedicated analyser role + stronger model. Added 'analyser' to providers.ROLES (forces LLM_MODEL_ANALYSER at boot); refactored test_llm_providers loops to derive from P.ROLES (future-proof). New agent/recon/analysis/analyser_types.py (LLM-facing ServiceProposal/SystemProposal/AggregatesProposal + L1DeltaBatch, proposals_to_deltas injects system provenance so LLM can't spoof it) and pod.py (build_analyser_graph read->analyse->curate mirroring build_pod_graph style; fail-open each node; default_read_fn=graph_read, default_analyse_fn=analyser LLM function_calling, default_curate_fn=l1_curator; run_analyser). 9 unit + 1 integration green (LLM mocked, session-injected write path). 123-test cross-area regression green. Debug: integration first hit neo4j AuthenticationRateLimit from default_curate_fn using dummy NEO4J_PASSWORD in bare env -> fixed by injecting session write path (FR-LCUR pattern) + added default_curate_fn wiring unit test. Escalation: operator must set LLM_MODEL_ANALYSER in .env before app restart. Independent verifier next."
}
```

```json
{
  "run_id": "2026-07-16T-franalyser-a2",
  "fr_area": "FR-ANALYSER",
  "attempt": 1,
  "assertions_green": 5,
  "assertions_total": 5,
  "tokens_estimate": 1020000,
  "escalations": 0,
  "outcome": "approved",
  "notes": "Independent verifier (separate sub-agent) APPROVED: ran 9 unit + 7 provider + 1 integration (live neo4j, not skipped) + 72-test regression itself; verified all 5 assertions in code + live (twice->one idempotency count==1, 3-node fail-open, provenance run-scoped+unspoofable, analyser role required, tests derive from ROLES); denylist (curator.py/schema.py/.env) untouched; MVP-fence honored (placeholder prompt, no deferred reasoning). FR-ANALYSER DONE. 3 areas complete (FR-LCUR, FR-RECONREQ, FR-ANALYSER). STOPPING for FR-ELICIT/FR-ENRICH design checkpoint (operator_kb format, bootstrap prompt, DataItem/relationship-vocabulary open points L1OP-1/L1OP-2) + operator .env action (LLM_MODEL_ANALYSER)."
}
```

```json
{
  "run_id": "2026-07-16T-phase0",
  "fr_area": "PHASE-0",
  "attempt": 1,
  "assertions_green": 0,
  "assertions_total": 0,
  "tokens_estimate": 120000,
  "escalations": 1,
  "outcome": "report-only",
  "notes": "Ratified 5 one-way doors against real code (all confirmed to bridge option); wrote docs/design/L1-MVP-plan.md (14-area FR catalogue + FR-LCUR full ledger); seeded STATE.md / loop-constraints.md / loop-budget.md / loop-run-log.md. Escalated: checkpoint for human review before Phase-1 code."
}
```

```json
{
  "run_id": "2026-07-16T-frelicit-frenrich",
  "fr_area": "FR-ELICIT + FR-ENRICH",
  "attempt": 1,
  "assertions_green": 30,
  "assertions_total": 30,
  "tokens_estimate": 1500000,
  "escalations": 1,
  "outcome": "implemented-verify-pending",
  "notes": "Operator decisions: operator_kb=free-text (typed template=AMV-4); DataItem flexible identity+vocabulary NOW (L1OP-1/L1OP-2 into MVP). FR-ELICIT: bootstrap.py (operator_kb->Service skeleton via analyser LLM, always-linchpin auth Systems, SystemKind seed, NO L0 refs/aggregates dropped, idempotent, fail-open) + bootstrap->assignment flow; 7 unit + 3 integration green; live smoke confirmed fail-open on a real openrouter 400 (operator's LLM_MODEL_ANALYSER id 'deepseek/deepseek-v4' invalid -> Waiting-on-human). FR-ENRICH: DataItem flexible identity (project_id,item_key) identity-independent-of-SURFACES_AT-sites; extensible DataRelationshipKind catalogue (6 seeds) + DATA_RELATIONSHIP edge {kind,predicate,rationale}; PRODUCES/CONSUMES with assumption on CONSUMES; SURFACES_AT native cross-layer (L0 MATCHed never created); systems-as-typed-edges (§6, 11 rels); analyser proposes all in one batch (default_curate_with_enrichment_fn), proposals provenance-free (system-stamped); 15 unit + 5 integration green. 2 new l1_schema constraints (l1dataitem_unique, datarelationshipkind_unique). 127-test full-L1 regression green. Combined independent verifier next."
}
```

```json
{
  "run_id": "2026-07-16T-frelicit-frenrich-approved",
  "fr_area": "FR-ELICIT + FR-ENRICH",
  "attempt": 1,
  "assertions_green": 30,
  "assertions_total": 30,
  "tokens_estimate": 1620000,
  "escalations": 0,
  "outcome": "approved",
  "notes": "Combined independent verifier APPROVED both areas: ran 22 unit + 8 integration (live neo4j, no skips) + 40-test FR-LCUR/FR-ANALYSER regression itself; verified DataItem identity-perp-membership (one node, growing SURFACES_AT set), bootstrap no-L0-refs (count(AGGREGATES)==0, no code path to write one), SURFACES_AT MATCH-not-create, :L1DataItem in sole-writer scan, injection guards, provenance non-spoofable, assumption-on-CONSUMES-only. Denylist (curator.py/schema.py/.env) untouched; MVP-fence honored (predicate is text, no NM-8 engine). Non-blocking note: working tree intermingles multiple uncommitted features (targeted-recon, FR-LCUR wiring) - hygiene only. 5 FR areas now DONE+APPROVED (LCUR, RECONREQ, ANALYSER, ELICIT, ENRICH). STOPPING: operator model-id blocker + working-tree-hygiene decision + remaining Phase-3/4 areas (PODSTREAM/TEMPLATE/SWEEP/INDEXCARD, SKILLIF/SPINE/AUTH/AUTHZSKILL) await steer."
}
```

```json
{
  "run_id": "2026-07-16T-e2e-full-analyser",
  "fr_area": "e2e (full pipeline) + analyser-prompt fixes",
  "attempt": 1,
  "assertions_green": null,
  "assertions_total": null,
  "tokens_estimate": 1720000,
  "escalations": 0,
  "outcome": "in-progress",
  "notes": "Operator fixed LLM_MODEL_ANALYSER; repeated e2e. Bootstrap live smoke now works: 9 services elicited from free-text KB + 2 linchpin systems, no L0 refs. Full pipeline e2e (bootstrap->targeted httpx recon->run_analyser) ran end-to-end vs app.onlineorders.com. Caught 3 REAL defects the mocked tests couldn't: (1) analyser/bootstrap prompts didn't tell the LLM the controlled vocabularies -> LLM proposed 'Authentication'/'Authorization' (rejected by build_system_cypher, silently dropped) -> FIX: added l1_curator.vocabulary_prompt() injected into both prompts. (2) default analyser graph only wrote core deltas, not FR-ENRICH -> FIX: unified curate contract to curate_fn(batch, project_id, provenance) + wired default_curate_with_enrichment_fn as the default; updated 5 analyser tests to new signature; 70-test regression green. (3) analyser put a URL value in AGGREGATES l0.label instead of the node type -> ValueError safe-label guard dropped the assignment -> FIX: added _L0_REFERENCE_GUIDE (label=node type, identity=key dict, per-label key list) to the analyser prompt. Re-running full e2e to confirm assignments+enrichment land. 34 unit green after fixes."
}
```

```json
{
  "run_id": "2026-07-16T-e2e-full-analyser-PASS",
  "fr_area": "e2e (full pipeline) — PASS",
  "attempt": 2,
  "assertions_green": null,
  "assertions_total": null,
  "tokens_estimate": 1850000,
  "escalations": 0,
  "outcome": "done",
  "notes": "Full pipeline e2e (bootstrap->targeted httpx recon->run_analyser) runs CLEAN end-to-end vs app.onlineorders.com, err=None at every step. Confirms all 3 e2e-caught fixes live: (1) vocabulary prompt -> bootstrap elicited 9 services + 3 systems (was dropping non-canonical names); (2) enrichment wiring -> analyser wrote 4 system_edges (default_curate_with_enrichment_fn); (3) L0-label guide -> AGGREGATES now LAND (2 edges: accounts->BaseURL conf0.8, accounts->Endpoint/ conf0.9). Final L1 model: 9 L1Service, 5 L1System, 2 AGGREGATES, 4 system_edges; L1Service count stayed 9 (edges attached to real services, no orphan creation). DataItem enrichment = 0, which is CORRECT: a single httpx probe of a login-redirect exposes no Parameters/forms/data-flow surface, and the analyser skill says propose nothing you cannot evidence. Exercising DataItem enrichment needs a data-bearing surface (katana crawl + arjun params, or the authenticated area). 129 mocked tests green across all 5 L1 areas. Fixes touch already-APPROVED areas (analyser/enrich) -> re-verification offered."
}
```

```json
{
  "run_id": "2026-07-16T-reverify-e2e-fixes",
  "fr_area": "re-verify FR-ANALYSER/ELICIT/ENRICH (e2e fixes)",
  "attempt": 1,
  "assertions_green": null,
  "assertions_total": null,
  "tokens_estimate": 1950000,
  "escalations": 0,
  "outcome": "approved",
  "notes": "Independent re-verifier APPROVED the 3 e2e-caught fixes (vocabulary_prompt single-sourced+injected both prompts; unified curate_fn(batch,project_id,provenance)+default_curate_with_enrichment_fn wired as default with fail-open+system-provenance intact; _L0_REFERENCE_GUIDE label=type). Ran 36 unit + 9 integration (live neo4j, no skips) + 34 regression itself; denylist (curator.py/schema.py/.env) untouched; MVP-fence honored. One non-blocking note: default_curate_with_enrichment_fn had no end-to-end test (inspection-only). CLOSED by maker: added test_default_curate_with_enrichment_writes_core_and_enrichment (asserts core+enrich both fire, catalogue seeded, run-scoped provenance injected) + test_default_curate_with_enrichment_skips_enrich_when_no_enrichment_deltas. 90-test regression green. All 5 L1 FR areas + the e2e fixes now verified."
}
```

```json
{
  "run_id": "2026-07-17T-e2e-soupmarket-datarich",
  "fr_area": "e2e (data-rich) — DataItem validation",
  "attempt": 1,
  "assertions_green": null,
  "assertions_total": null,
  "tokens_estimate": 2100000,
  "escalations": 0,
  "outcome": "done",
  "notes": "Data-rich e2e vs soupmarket.shop (= OWASP Juice Shop, Angular SPA + REST API). New project; recon pipeline [httpx,katana,jsluice,httpx_reprofile,arjun] all success (katana 367 assets, arjun 9, jsluice 0). L0 surface: 133 Endpoints, 5 Parameters, 13 Headers. Analyser: 17 services, 7 systems, 55 AGGREGATES, enrichment {data_items:10, surfaces_at:15, data_flows:12, data_relationships:0, system_edges:28}, err=None. DataItem ASSESSMENT: (faithfulness) HIGH - all 10 items map to real Juice Shop endpoints, zero hallucination; (exhaustiveness) GOOD on high-value entities (user_identity, user_credential, payment_card, order, basket_item, product, address, complaint, feedback, challenge), partial on long tail (no review/wallet/quantity as distinct items); (vocabulary) EXCELLENT - semantic consistent snake_case business entities, notably splits user_identity vs user_credential (identity vs secret - an adversarial distinction). Real Tier-1 trust captured: shopping-basket CONSUMES product 'reference products by ID', order-management CONSUMES basket_item 'created from basket items at checkout'. Observations -> AMV-5 (SURFACES_AT lands on Endpoints not fields because arjun/jsluice thin surface; recon-layer, L1 accepts field-level already), AMV-6 (data_relationships=0 needs phase-B reflection). Stale pool: 79/133 endpoints unassigned -> FR-SWEEP well-motivated. Project soup_8b2797ad left in graph for inspection. Next loop phase: FR-TEMPLATE (ratified door D5)."
}
```

```json
{
  "run_id": "2026-07-17T-frtemplate-approved",
  "fr_area": "FR-TEMPLATE",
  "attempt": 1,
  "assertions_green": null,
  "assertions_total": null,
  "tokens_estimate": 2200000,
  "escalations": 0,
  "outcome": "approved",
  "notes": "endpoint_template(path) pure per-segment collapse (numeric/uuid -> {id}, idempotent, 2fa/v2 untouched); written on the AGGREGATES edge at assignment when L0 target is Endpoint (l1_curator never writes L0). Independent verifier APPROVED: ran 10 unit + 11 integration (live neo4j, no skip) + 39 regression itself; verified derivation, edge-not-L0 wiring, sole-writer intact, live dedup (two concrete /sellers/{1,2}/sales -> one /sellers/{id}/sales class), denylist clean, MVP-fence (key only, NM-10 reducer deferred). Committed feat(l1-template) + docs. 6 FR areas DONE+verified (LCUR, RECONREQ, ANALYSER, ELICIT, ENRICH, TEMPLATE). Remaining MVP: FR-SWEEP (79/133 stale endpoints on the e2e -> well-motivated), FR-INDEXCARD, FR-PODSTREAM; Phase 4 FR-SKILLIF/SPINE/AUTH/AUTHZSKILL; then the §15 walkthrough."
}
```

```json
{
  "run_id": "2026-07-17T-frsweep-approved",
  "fr_area": "FR-SWEEP",
  "attempt": 1,
  "assertions_green": null,
  "assertions_total": null,
  "tokens_estimate": 2320000,
  "escalations": 0,
  "outcome": "approved",
  "notes": "sweep.py: stale_pool/stale_pool_count (assignable L0 with no inbound AGGREGATES, default Endpoint, injection-guarded) + missing_system_kinds (SystemKind rows with no OF_KIND L1System, registry-driven). Derived queries, no table (L1D-24). Live-data confirmation on soupmarket project: stale_pool_count==79 (matches e2e; stale items are .pyc/.bak/chunk-*.js junk, correctly not business members). Independent verifier APPROVED: ran 6 unit + 2 integration (live neo4j, no skip) itself; verified no-inbound-AGGREGATES/no-OF_KIND queries, live assign->leaves-pool, seed-13-instantiate-1->12-missing, injection guard, read-only, denylist clean, MVP-fence (derived query). 7 FR areas DONE+verified. Realism note: missing_system_kinds only meaningful after bootstrap seeds full catalogue -> reinforces operator-KB-seeded e2e."
}
```

```json
{
  "run_id": "2026-07-17T-frindexcard-approved",
  "fr_area": "FR-INDEXCARD",
  "attempt": 1,
  "assertions_green": null,
  "assertions_total": null,
  "tokens_estimate": 2450000,
  "escalations": 0,
  "outcome": "approved",
  "notes": "index_card.py: index_cards (per-unit card {kind,key,spine,edge_degree-by-family,salience,nl_handles} - counts NOT member set, DD-4) + dfs_down (one typed hop, injection-guarded). Live-data: soupmarket 24 cards, busiest user-account 406 bytes w/ 11 aggregates+6 edge families, AGGREGATES degrees sum to 55. Independent verifier APPROVED: ran 6 unit + 3 integration (live) itself; verified degree-not-member-set (collect(type(r)), no member node in query; 10k-member card <500B), dfs-down one hop, injection guard, zero-degree units kept, read-only, denylist clean, MVP-fence (no NM-3 dfs-up). Non-blocking note: _SAFE_IDENT $ matches before trailing \\n (non-exploitable) -> will harden across sweep/index_card/l1_curator. 8 FR areas DONE+verified. Phase 3 complete except FR-PODSTREAM (L1D-23 two-way, batch default)."
}
```

```
{
  "run_id": "2026-07-17T-exhaustive-soupmarket-e2e",
  "fr_area": "ALL-15 (recon + attack-surface-analysis e2e)",
  "attempt": 2,
  "assertions_green": 222,
  "assertions_total": 222,
  "tokens_estimate": 3600000,
  "escalations": 0,
  "outcome": "approved",
  "notes": "Exhaustive live e2e vs DOMAIN soupmarket.shop (OWASP Juice Shop behind nginx; system blind to local/vuln identity), project soup_9b876a3c. 172 code-level ASA assertions (0 skips) + 50 live-graph FR/NFR assertions across all 15 FR areas. Flow: bootstrap(FR-ELICIT 7/7) -> recon[httpx,katana(341),jsluice(543),httpx_reprofile,arjun] -> analyser two-pass enrich(18 DataItems, 9 CONSUMES all w/ Tier-1 trust assumptions, 37 typed system-edges, envelope+prov on all AGGREGATES) -> sweep/index-card -> interface-B(httpx 16 assets) -> anatomy skills(FR-SPINE 2 independent SPA/CSR slots; FR-AUTH flat role/realm select+serialise; FR-AUTHZSKILL real guest401/shopper200 pyramid -> AUTHORIZED_BY{shopper}/AUTHENTICATED_BY{jwt}). Independent verifier ran baseline+graph itself. ATTEMPT 1 REJECTED: my anomaly-(B) narrative was materially FALSE ('3 noise endpoints, web-frontend only, unpolluted'); truth = 58/182 (31%; ~70 inclusive) noise across 5 services incl. genuine web3-wallet (soljson blobs) + file-server (node_modules). ATTEMPT 2 APPROVED after honest correction + AMV-8 (L0 crawl/parse noise) + AMV-9 (analyser assignment-confidence/stale = live-evidenced L1OP-5) registered. Root finding: stronger model (deepseek-v4-pro) OVER-assigns (0 stale vs prior weaker-model 79); empty stale pool is a NEGATIVE signal. No in-scope FR/NFR violated (assignment faithfulness = deferred L1OP-5, out of fence). Infra: agent RestartCount=0 (no OOM) - curated tool set avoided steel_crawl/ffuf/kiterunner. FR-AUTH driver bug (mine, fixed): role cred set is FLAT (Authorization top-level, not nested under 'headers'); selector keeps realm, serialiser strips it."
}
```

```
{
  "run_id": "2026-07-18T-fr-stream-nm7-approved",
  "fr_area": "FR-STREAM (NM-7 streaming analyser)",
  "attempt": 1,
  "assertions_green": 6,
  "assertions_total": 6,
  "tokens_estimate": 5200000,
  "escalations": 1,
  "outcome": "approved",
  "notes": "Operator-pulled NM-7 into scope after observing (confirmed via code+Langfuse traces) that L1 was only built post-recon batch, never progressively during recon - which was BY DESIGN (L1D-23 batch default), not a bug; escalated as a design decision (AskUserQuestion), operator chose Full streaming. Built streaming.py::stream_analyser_step (fail-open, stable stream-<run_id>, auto-deliver) + per-job pipeline hook gated on settings.recon.streaming_analysis, synchronous between sequential jobs (OOM-safe, no persistent consumer). Batch stays DEFAULT (two-way door). Unit 26 passed/0 skips. Live: clean artifact soupstream_faf091e0 (100% analyser:stream- prov, 0 dup identities) + scale growth [0,77,142,143,143] w/ idempotent convergence. Independent verifier APPROVED (ran unit+graph itself, reviewed code contract). VERIFICATION RESTARTED after operator teardown destroyed agent context (persisted data survived): root-caused a muddied artifact (my batch-verify convergence pass clobbered stream provenance -> fixed driver to use idempotent stream-step convergence) and a false 'kill' (detached python survived; relaunched via docker exec -d to container file, immune to exec-kill). Findings out-of-scope for FR-STREAM: infra flakiness (constrained host) + high analyser assignment variance (143 vs 11 same target) -> folded into AMV-9. NM-7 marked implemented (opt-in) in spec + L1D-23 two-way-door note."
}
```

```
{
  "run_id": "2026-07-19T-post-recon-curation-6-areas-approved",
  "fr_area": "FR-INVENTORY + FR-MERGE + FR-JOURNEY + FR-TYPESEP + FR-CURATE + FR-MODELFIX",
  "attempt": 1,
  "assertions_green": 16,
  "assertions_total": 16,
  "tokens_estimate": 6400000,
  "escalations": 3,
  "outcome": "approved",
  "notes": "Post-MVP curation + L1 remediation, plan docs/design/post-recon-curation-and-l1-remediation-plan.md, run with the MVP fence DOWN (operator, recorded in loop-constraints.md: destructive reconciliation + NM-1/NM-4 now in scope). SIX areas built via subagents and each independently verifier-APPROVED: FR-INVENTORY (read_l1_inventory + un-truncated EXISTING L1 IDENTITIES block atop both analyser prompts and bootstrap - kills synonym-slug drift at WRITE time; the old reuse hint was toothless because identities sat in a 400-capped slice the data pass dropped), FR-MERGE (l1_curator merge/delete/relabel: idempotent, provenance-stamped, edges re-pointed never orphaned, fail-open per op, :L1*-only), FR-JOURNEY (journeys prop + services_in_journey, identity independent of membership; ordered promotion registered as AMV-11 not pre-built), FR-TYPESEP a+b (prompt rule + structural re-homing backstop), FR-CURATE (run_curation: propose -> reconcile -> journeys -> anatomy -> sweep -> report, fail-open per stage, driver-invoked and deliberately NOT wired into run_pipeline to protect the 3.8GiB host), FR-MODELFIX (mechanism-as-System: ONE WebPresentation System carrying rendering_model + navigation_model as INDEPENDENT props via EXPOSED_VIA; RENDERED_BY + both RenderingSystem_* kinds deleted; api_paradigm/auth_methods re-homed off the Service). FR-MODELFIX exists because review of FR-CURATE caught the re-homing inferring rendering from navigation (SPA->CSR), violating L1D-31a; the audit then found the identical conflation for api_paradigm and auth_methods. THIS ITERATION was a resume-and-consolidate pass, not new build: the previous session left ALL of it UNCOMMITTED with STATE.md and this log never updated past FR-STREAM and every plan checkbox unchecked while the ledgers read green. Committed in 9 commits (7c8e31f gitignore hygiene, 5fec65b FR-STREAM, 221ee85 WI-1 viz, 43a8629 FR-INVENTORY+TYPESEP-a, a5b05f6 FR-JOURNEY, c782df6 FR-MERGE+FR-MODELFIX, b39d20b FR-CURATE+TYPESEP-b, 58ae4b6 jsluice, df9fdb4 skills). FR-MERGE and FR-MODELFIX share l1_curator.py so they could not be split without a red intermediate; the commit names both. HONESTY NOTE: this is a retro-split of one already-verified increment - the 827-test green baseline was measured on the FINAL tree, not re-measured at each intermediate commit. Baseline: 827 unit pass, 46 of them this plan (incl 4 live-neo4j integration, 0 skips), 4 frontend colour tests. ONE failure test_pipeline_e2e_httpx_to_arjun_prop_dependent_target is PRE-EXISTING - reproduced byte-identically at ce5e351 with .env present via a throwaway baseline worktree, so NOT curation fallout; separately a hermeticity defect (a tests/recon/ unit-tier test reaches live neo4j via read_steering_signals, fails open, leaves arjun unexecuted) -> escalated, not masked. Also corrected a stale FR-CURE2E assertion that still named RENDERED_BY (deleted by FR-MODELFIX) -> now EXPOSED_VIA a WebPresentation. 3 escalations landed in STATE.md Waiting-on-human: the non-hermetic test, the un-gated jsluice fix (no ledger, no verifier), and FR-CURE2E needing an operator go-ahead before it burns budget on a host with prior memory pressure. NEXT: FR-CURE2E is the only open area; no e2e_curation.py driver exists yet."
}
```
