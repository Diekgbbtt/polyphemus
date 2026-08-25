# Assertions - system "candidate-creation → projection → gate → mint rewrite"
**Source:** docs/design/hunting-orchestrator-candidates-rewrite-spec.md
**Seams under assertion:** candidate intake, per-fault REASON pass, rich projection, gate prompt, deterministic mint, graph envelope, HuntStore, runtime bootstrap

## Contract predicates (integration) C1-C12

### C1 - bootstrap opens row and schedules on shared loop
- **seam:** `attack/hunting/runtime.py::start_hunting` <-> `app/clients/pg.py::create_hunting_run` + `app/runtime.py::schedule("hunting",...)` + `app/llm/checkpoints.py::module_context("hunting")`
- **delivery semantic:** success
- **input:** `project_id="proj-1"`, `candidates=[DeliveredCandidate(unit_id="Service:slug:a", fault_class="CWE-352", applies_witnesses=Witness(llm="form Z no token", deterministic="EXPOSED_VIA=WebPresentation"), match_verdict="applies")]`
- **observable:** exactly 1 `hunting_runs` row with `hunting_run_id="run-c1"` status `running`; exactly 1 Future scheduled via `runtime.schedule("hunting", coro, name="hunting-proj-1")` on shared worker loop; `hunting_module_context()` active so `get_session_checkpointer()` resolves hunting index during `arun_orchestration`
- **yields:** `test_integration_c1_bootstrap_schedules_on_shared_loop`

### C2 - bootstrap fail-closed when control plane absent
- **seam:** `project_management/api.py::POST /projects/{project_id}/hunting` <-> `attack/hunting/runtime.py::hunting_control_plane_available`
- **delivery semantic:** degradation (runtime not landed)
- **input:** `GET_ACTIVE_RUNTIME()=None`, `POST /projects/proj-1/hunting` with 1 candidate
- **observable:** HTTP 503, body `hunting control-plane runtime is not active`, zero calls to `pg.create_hunting_run`, zero calls to `runtime.schedule`
- **yields:** `test_integration_c2_bootstrap_fail_closed_503`

### C3 - prompt splits Services vs Systems with distinct intros (Q4)
- **seam:** `attack/hunting/llm.py::_compose_gate_prompt` <-> `attack/hunting/unit_projection.py::build_projection` + `attack/hunting/fault_kb.py::load_materialisation`
- **delivery semantic:** success (rich slots populated)
- **input:** `GateInput(candidates=[DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm="form Z"),"applies"), DeliveredCandidate("System:auth-service:auth-service","CWE-352",Witness(llm="exposure internal"),"applies")], unit_projection={"Service:slug:a": UnitProjection(kind="Service", data_items={"PRODUCES": (DataItem(name="csrf_token"),)}, cooperating_systems={}), "System:auth-service:auth-service": UnitProjection(kind="System", cooperating_systems={"CALLS": (SystemInfo(kind="Cache"),)})}, materialisation={"CWE-352": {name:"CSRF"}}, fold_family={"CWE-352": ()})`
- **observable:** prompt contains `Services:` then `Adversarial reasoning over each Service: spell its surface - its edged DataItems and Systems` then per-Service block sorted by unit_id, then `Systems:` then `Adversarial reasoning over each System: outline the System distinctly`; each Service block shows `data items: PRODUCES: name=csrf_token`; System block shows `cooperating systems: CALLS: kind=Cache`
- **yields:** `test_integration_c3_prompt_splits_services_systems`

### C4 - per-slot degrade renders UNKNOWN never FALSE (fail-open)
- **seam:** `attack/hunting/llm.py::_render_projection` <-> `attack/hunting/unit_projection.py::build_projection`
- **delivery semantic:** degradation (one slot raises)
- **input:** `build_projection("proj-1","Service:slug:a", read_fn=raising_fn)` raises; `build_projection("proj-1","System:cache:1", read_fn=ok)` succeeds; same GateInput with `unit_projection={"Service:slug:a": None, "System:cache:1": UnitProjection(kind="System")}`
- **observable:** rendered prompt has exactly 1 `UNKNOWN (projection read failed or absent)` for Service:slug:a, zero occurrences of `FALSE`; System slot renders `unit kind: System`; `normalize_candidates` still yields 2 accepted, 0 malformed, GateDecision still carries both
- **yields:** `test_integration_c4_projection_degrade_unknown_never_false`

### C5 - hypothesise-phase discipline verbatim (Q11/Q9/Q8/Q16) bound in prompt
- **seam:** `attack/hunting/llm.py::_gate_skill` + `_compose_gate_prompt` <-> `attack/hunting/actors.py::build_orchestrator_tool_surface`
- **delivery semantic:** success
- **input:** `GateInput(prior_minted_keys=["Service:slug:a::CWE-352"], candidates=[DeliveredCandidate("Service:slug:b","CWE-352",Witness(llm="x"),"applies")])`
- **observable:** prompt OPENS with the `L1_ONTOLOGY_PRIMER` constant (G9, #168: the Service / System / DataItem conceptions + the domain-model philosophy, at the TOP of the user frame, never the system prompt) and contains verbatim `Prior-hunt reflection (Q11): Prior minted-config keys to reflect on: Service:slug:a::CWE-352`, `Knowledge-sufficiency decision point (Q9)`, `Target-knowledge loop (Q9)`, `Same-class merge (Q16)`, `The hypothesise write (spec 3.3): call hunts_store(write, config,`; the phase-TRANSITION verbatims ride the tool-call responses (constants), never this prompt (re-scoped #167)
- **yields:** `test_integration_c5_loop_protocol_verbatim` + `test_gate_prompt_opens_with_the_l1_ontology_primer`

### C6 - supervisor is sole router via Command(goto=...) DP-5; the phase machine is the REASON stretch (re-scoped #167)
- **seam:** `attack/hunting/orchestrator_graph.py::build_hunting_graph` <-> langgraph StateGraph
- **delivery semantic:** success + ordering
- **input:** schedule `[FaultWorkItem(fault_class="CWE-352", candidates=[c1,c2]), FaultWorkItem(fault_class="CWE-639", candidates=[c3])]`
- **observable:** `set(g.nodes)=={"supervisor","hypothesise","ratify","note"}` (the dispatch node - G12 - and the budget stage - G7 - are removed); supervisor returns `Command(goto="hypothesise")` popping ONE pair per super-step (a fault's candidate queue drains before the next fault pops), `Command(goto=END)` when schedule AND queue are exhausted; hypothesise/ratify/note never return Command
- **yields:** `test_integration_c6_supervisor_only_router`

### C7 - ledger accumulates per pair across the faults (re-scoped #167)
- **seam:** `attack/hunting/hunt_orchestrator.py::_hypothesise_node` <-> `attack/hunting/orchestrator_graph.py::HuntOrchestrationState[ledger, minted_configs]`
- **delivery semantic:** success (2 faults, 3 pairs)
- **input:** fault CWE-352 with units Service:slug:a, Service:slug:b; fault CWE-639 with unit Service:slug:a; `hypothesise_fn` returns 1 carried EnvisionedDirection per pair
- **observable:** `report.ledger==LoopLedger(units_done=3, minted_config_keys=["Service:slug:a::CWE-352","Service:slug:b::CWE-352","Service:slug:a::CWE-639"], notes_recorded=3)`; `configs_ratified==3`; `state["minted_configs"]` has exactly 3 keys
- **yields:** `test_integration_c7_ledger_last_write_per_pair`

### C8 - the O9 BUDGET stage is REMOVED (G7, re-scoped #167)
- **seam:** `attack/hunting/orchestrator_graph.py::build_hunting_graph` <-> `attack/hunting/hunt_orchestrator.py::_hypothesise_node`
- **delivery semantic:** success (nothing is ever cut)
- **input:** `candidates=[DeliveredCandidate("Service:slug:a","CWE-352"), DeliveredCandidate("Service:slug:b","CWE-352"), DeliveredCandidate("System:cache:1","CWE-639")]`, `hypothesise_fn` carries each pair
- **observable:** `report.pairs_processed==3`, `report.configs_ratified==3`; the report has NO `budget_cut` field and the ledger has NO `budget_remaining` - spending is the runtime plane's and the pod's (D67-09)
- **yields:** `test_integration_c8_budget_stage_removed`

### C9 - HuntStore per-project topology, config + notes split (re-scoped #166, tool surface re-scoped #168)
- **seam:** `attack/hunting/hunt_store.py::HuntStore` <-> `attack/hunting/actors.py::build_orchestrator_tool_surface{hunts_store,notes}`
- **delivery semantic:** success
- **input:** `HuntStore(tmp_path).write_config("project-1", {unit_id, fault_class="CWE-352", vulnerability_class="CSRF", hunt_id="h1"})` then `append_note("project-1", "Service:slug:a::CWE-352", "track it")`
- **observable:** file `project-1/orchestration/hunt_configs/produced/Service:slug:a_CWE-352_CSRF.yaml` carries the config YAML - the produced/consumed kind files carry NO `_seq`/`_ref` (G11, the file name IS the key); file `project-1/orchestration/memory.yaml` holds the notes (natural append order, no `_seq`); `read_configs_by_key("project-1","Service:slug:a::CWE-352")==[{"hunt_id":"h1"}]`; `read_notes("project-1","Service:slug:a::CWE-352")==[{"note":"track it"}]`; default `HUNT_STORE_ROOT==src/polymerhus/attack/hunting/data` (no env var); the per-run kind files (`run`/`config`/`hunt`/`dispatch`/...) and the repo-global `memory.md` are gone
- **yields:** `test_integration_c9_store_append_and_split_reads`

### C10 - store read failure degrades to empty prior insights (O4)
- **seam:** `attack/hunting/hunt_orchestrator.py::_read_prior_insights` <-> `attack/hunting/hunt_store.py::read_configs_by_key`/`read_notes`
- **delivery semantic:** degradation
- **input:** `tools.store_reads.read_configs_by_key`/`read_notes` raise `OSError("disk")` for key `Service:slug:a::CWE-352`; 1 candidate CWE-352
- **observable:** `arun_orchestration` completes with `hunts_dispatched==1`, `prior_hunt_insights==[]` on minted config, 1 warning logged `hunt store read degraded`, no exception
- **yields:** `test_integration_c10_store_read_degrades_empty`

### C11 - mint fans out N per distinct vulnerability class, hunt_id base/base-i (class oracle)
- **seam:** `attack/hunting/hunt_orchestrator.py::mint_hunt_config` <-> `attack/hunting/hunt_orchestrator.py::_distinct_vulnerability_classes` + the elicited class vocabulary (ADR G5)
- **delivery semantic:** success (2 classes CSRF vs IDOR)
- **input:** `direction=EnvisionedDirection(unit_id="Service:slug:a", fault_class="CWE-352", research_direction="probe CSRF vs IDOR", vulnerability_classes=["CSRF", "IDOR"])` where CSRF/IDOR are elicited web-vulnerability classes, `hunt_id="abc123"`
- **observable:** returns list length 2; `[0].hunt_id=="abc123"` carries class CSRF, `[1].hunt_id=="abc123-1"` carries IDOR; each config `status=="hypothesised"`, `vulnerability_class` equals its class, both share `prompt_template.research_direction=="probe CSRF vs IDOR"`, `l0_evidence==["llm: form Z no token"]`, `adversarial_capabilities==[]` and `technique_primitives==[]`; oracle is the class not the raw string count, so adding a third emission of the same class would not increase the fan-out
- **yields:** `test_integration_c11_mint_fanout_per_distinct_class`

### C12 - mint collapses same-class duplicates and empty degrades to carried-bare
- **seam:** `attack/hunting/hunt_orchestrator.py::_distinct_vulnerability_classes` <-> `attack/hunting/hunt_orchestrator.py::mint_hunt_config`
- **delivery semantic:** duplicate + empty
- **input:** a) `vulnerability_classes=["CSRF", "CSRF"]`; b) `vulnerability_classes=[]` or with `[""]`
- **observable:** a) exactly 1 hypothesised HuntConfig with `hunt_id=="base"` and `vulnerability_class=="CSRF"`; b) exactly 1 hypothesised draft with `vulnerability_class==""` and `research_direction` passed through; HuntConfig validates via Pydantic with the reworked slots (`status`, `vulnerability_class`, `prompt_template.rationale|research_direction|l0_evidence`, `surface_context`, `target_caveats`, `prior_hunt_insights`, `tool_registry`, `adversarial_capabilities`, `assumptions`, `technique_primitives`) all present; oracle is the class not the raw string count
- **yields:** `test_integration_c12_mint_collapse_and_bare_degrade`

### C13 - ReadOnlyGraphView write-shaped guard rejects before driver
- **seam:** `attack/hunting/hunt_orchestrator.py::ReadOnlyGraphView._guard` <-> `neo4j_client` driver
- **delivery semantic:** degradation (write-shaped cypher)
- **input:** `graph_view.read("MATCH (u) MERGE (u)-[:EXPOSED_VIA]->(m)", {})` and `graph_view.read("match (u) merge (u)-[:EXPOSED_VIA]->(m)", {})` and `graph_view.merge()` any args
- **observable:** each raises `ReadOnlyGraphViewError` containing `refusing write-shaped cypher`, zero calls to underlying `neo4j_client.read`, `graph_view._guard` regex case-insensitive on `MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD CSV`
- **yields:** `test_integration_c13_write_guard_rejects`

### C14 - HuntOrchestratorActor thread reused across faults on same run
- **seam:** `attack/hunting/hunt_orchestrator.py::_ORCHESTRATOR_ACTORS registry` <-> `attack/hunting/actors.py::HuntOrchestratorActor`
- **delivery semantic:** ordering + duplicate-idempotent
- **input:** `run_id="run-c14"`, 2 faults `CWE-352` over Service:slug:a and `CWE-639` over Service:slug:b, stub `reason_fn` carries; call `arun_orchestration` with 2 faults, capture `orchestrator` object after first `_reason_node` and after second
- **observable:** `registry[run_id]` is same object identity across both faults, `len(registry)==1`, actor `run_id` thread name `hunting_orchestrator:run-c14` reused, reaped only via `await _reap_orchestrator(run_id)` not via pass finally, after reap `registry.get(run_id) is None`
- **yields:** `test_integration_c14_actor_thread_reused`

### C15 - cross-pass config visibility via the fixed HUNT_STORE_ROOT (re-scoped #166, tool surface re-scoped #168)
- **seam:** `attack/hunting/hunt_store.py::HUNT_STORE_ROOT` <-> `attack/hunting/actors.py::build_orchestrator_tool_surface{hunts_store,notes}`
- **delivery semantic:** success (cross-pass) + ordering
- **input:** `storeA = HuntStore()` at default `src/polymerhus/attack/hunting/data` writes a config `Service:slug:a::CWE-352::CSRF` and a note; `storeB = HuntStore()` same default reads the same project
- **observable:** `storeB.read_configs_by_key("project-1","Service:slug:a::CWE-352")` returns the config from pass-a; the note reads back from `memory.yaml`; default `HUNT_STORE_ROOT==src/polymerhus/attack/hunting/data` string equality, no env var; NO repo-global `memory.md` anywhere - the per-project produced/consumed + `memory.yaml` topology is the whole memory (G10/G11)
- **yields:** `test_integration_c15_cross_run_memory_fixed_root`

### C16 - HuntingAgent dispatch harness per-hunt thread via HuntingActorRegistry
- **seam:** `attack/hunting/hunting_agent.py::build_actor_hunting_agent` <-> `attack/hunting/actors.py::HuntingActorRegistry` + `HuntingHunterActor`
- **delivery semantic:** concurrency + ordering
- **input:** dispatch 2 concurrent hunts `HuntSession(run_id="run-c16", hunt_id="hunt-A")` and `hunt-B` via `build_hunting_agent` inside `arun_orchestration` dispatch phase, spy on `HuntingActorRegistry.get_or_create`
- **observable:** `author` and `judge` for hunt-A use same `HuntSession` thread `run-c16:hunt-A:hunting_hunter`, hunt-B uses distinct `run-c16:hunt-B:hunting_hunter`, registry holds 2 entries during dispatch, concurrent hunts never share thread
- **yields:** `test_integration_c16_hunting_harness_per_hunt_thread`

## Walkthrough predicates (end-to-end) E1-E14

### E1 - per-fault fan-out 2 units x 2 classes -> 3 ratified configs (re-scoped #167)
- **grounds:** spec 3.1 Q1 (fault schedule unit), 3.2 node-per-phase, 3.5 Q2/Q12 (N per class), 3.6 rich projection
- **entry seam:** `attack/hunting/runtime.py::start_hunting` scheduled via `runtime.schedule("hunting",...)`
- **input:** `project_id="proj-e1"`, `run_id="run-e1"`, `candidates=[DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm="form Z no token"),"applies"), DeliveredCandidate("Service:slug:b","CWE-352",Witness(llm="form Y carries token, Z does not"),"applies")]`; stub `hypothesise_fn` returns per pair: Service:slug:a -> 2 candidates (CSRF, IDOR), Service:slug:b -> 1 (CSRF); `ratify_fn` amends every draft to ratified; `note_fn` writes one note per pair
- **live edge:** none (all in-process, graph seam mocked `read_fn=lambda cy,p: []`, LLM stubbed)
- **path:** candidate intake normalizes 2 accepted, 0 dropped -> supervisor pops FaultWorkItem(CWE-352, [a,b]) and iterates its candidate queue as pairs -> per pair, hypothesise (elicitation + mint of the drafts, status='hypothesised') -> ratify (status='ratified', the filled ratification fields) -> note (one note per pair) -> graph ENDs at the note phase (no dispatch node, G12; no budget stage, G7)
- **terminal:** `report.pairs_processed==2`; `configs_hypothesised==3`; `configs_ratified==3`; HuntStore produced/ has 3 config YAML files all status='ratified', `memory.yaml` has 2 notes (one per pair) - the per-run `config.md`/`notes.md`/`hunt.md`/`dispatch.md` kind files are removed (#166); `ledger==LoopLedger(units_done=2, notes_recorded=2, minted_config_keys=["Service:slug:a::CWE-352","Service:slug:b::CWE-352"])`; report has no budget-cut field
- **observed:** `HuntStore(tmp).read_configs("proj-e1")` returns 3 dicts with hunt_ids `base, base-1` pattern; `read_notes("proj-e1")` shows 2 notes keyed correctly
- **yields:** `test_e2e_e1_per_fault_fanout`

### E2 - runtime bootstrap via POST completes and persists
- **grounds:** spec 3.8 reuse + runtime seam F1 + O1-O10
- **entry seam:** `POST /projects/proj-e2/hunting`
- **input:** `project_id="proj-e2"`, HTTP body `{candidates:[Service:slug:a CWE-352 applies]}` with real `hunting_runs` table
- **live edge:** none (worker loop seeded, neo4j not required)
- **path:** API handler calls `pg.create_hunting_run` sync then `runtime.schedule("hunting", start_hunting(...))` on shared worker loop -> `start_hunting` sets `hunting_module_context("hunting")` -> runs `arun_orchestration` with 1 fault -> writes the hypothesised config into produced/ + the note into memory.yaml -> `set_hunting_run_status("complete")` via `asyncio.to_thread`
- **terminal:** `hunting_runs` row `hunting_run_id` status `complete`; HuntStore produced/ has 1 config YAML, `memory.yaml` 1 note (the per-run `run.md` is removed, #166); HTTP response 201 with `{"hunting_run_id": "<id>"}`
- **observed:** `SELECT status FROM hunting_runs WHERE hunting_run_id='run-e2'` returns `complete`; `GET /projects/proj-e2/hunting/run-e2` returns 200 with same row
- **yields:** `test_e2e_e2_bootstrap_post_persists`

### E3 - BLOCKED (removed from scope): park/resume via back_edge to recon
- **grounds:** the back_edge request to recon is **wrongly designed and is NOT an agent tool** in this tree (operator ruling 2026-08-22): the target-knowledge loop rides `graph_view`, never a recon request. The yellow park/resume predicate is therefore REMOVED from the walking tier, not substituted. Since #111 (graceful stop) is blocked by #110 and back_edge is out of the agent surface, the park/resume canon is not exercised e2e.

### E4 - the O9 budget stage is REMOVED (G7, re-scoped #167)
- **grounds:** ADR G7 (the O9 envelope BUDGET stage is removed - spending is the runtime plane's and the pod's, D67-09)
- **entry seam:** `arun_orchestration` with injected hypothesise/ratify/note seams
- **input:** `candidates=[DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm="a"),"applies"), DeliveredCandidate("Service:slug:b","CWE-352",Witness(llm="b"),"applies")]`, stub hypothesise returns 3 classes (2 for a, 1 for b)
- **live edge:** none
- **path:** per pair: hypothesise writes the drafts -> ratify amends them to ratified -> note -> END
- **terminal:** `report.pairs_processed==2`, `configs_ratified==3`, no `budget_cut` field; `produced/` has 3 configs all status='ratified' (nothing was ever cut - a removed-stage assertion)
- **observed:** store counts exact; the report has no budget-cut field
- **yields:** `test_e2e_e4_budget_stage_removed`

### E5 - malformed + does-not-apply + UNKNOWN degrade never abort (O1/O7/O10)
- **grounds:** spec 5 O1/O7/O10 fail-open
- **entry seam:** `arun_orchestration`
- **input:** `candidates` in fixed order [0] `DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm=None), "applies")` malformed, [1] `DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm="x"),"applies")` duplicate key of [0], [2] `DeliveredCandidate("System:cache:1","CWE-639",Witness(llm="x"),"does-not-apply")` plus `read_fn` that raises for System slot but gated after prune
- **live edge:** none
- **path:** `normalize_candidates` processes in order: [0] malformed `malformed_dropped=1`, [1] duplicate of dropped key still counts as duplicate `duplicates_dropped=1`, [2] pruned `pruned_by_verdict=1` before the hypothesise phase -> empty intake -> O1 empty pass, no phase machine
- **terminal:** `report.pairs_processed==0`; `report.malformed_dropped==1`; `report.duplicates_dropped==1`; `report.pruned_by_verdict==1`; `report.store_write_failures==0`; the empty pass persists nothing in the memory topology - `read_configs("proj-e5")==[]` and `read_notes("proj-e5")==[]` (the per-run `run.md` with `candidates_received` is removed, #166)
- **observed:** report fields exact as above
- **yields:** `test_e2e_e5_empty_after_prunes_is_empty_pass`

### E6 - cooperating systems surface in System-targeting hunt (Q5)
- **grounds:** spec 3.6 D3 adjacency + 3.7 Q5 cooperating-systems instruction
- **entry seam:** `arun_orchestration` with real-ish `build_projection` over seeded neo4j fixture
- **input:** `candidates=[DeliveredCandidate("System:cache:1","CWE-639",Witness(llm="System cache internal"),"applies")]`; neo4j has `L1System(kind="cache",discriminator="1")-[:CALLS]->L1System(kind="db")` and `L1System(cache:1)<-[:EXPOSED_VIA]-L1Service(slug:b)`
- **live edge:** neo4j mini-fixture `L1System cache:1 -> db` and `Service slug:b -> cache:1` seeded by test (requires live neo4j; blocked when neo4j unavailable, not substituted)
- **path:** `build_projection("proj-e6","System:cache:1")` reads System-to-System adjacency -> `GateInput.unit_projection["System:cache:1"].cooperating_systems=={"CALLS": (SystemInfo(kind="db"),), "EXPOSED_VIA": (SystemInfo(kind="Service"),)}` -> `_compose_gate_prompt` renders `cooperating systems: CALLS: kind=db` with verbatim `Consider cooperating systems when creating a HuntConfig targeting a system`; the phase seams then run the pair through hypothesise -> ratify -> note (re-scoped #167: injected hypothesise/ratify/note fakes, no dispatch)
- **terminal:** prompt string contains `cooperating systems:` and `kind=db`; `report.pairs_processed==1` and `configs_ratified==1`; HuntStore notes count 1
- **observed:** `trace_gate_step("symbolic-render", input={"cooperating_systems":"ok"})` row present; prompt file read-back contains cooperating line; Cypher `MATCH (s:System {discriminator:"1"})-[r:CALLS]->(t) RETURN count(t)` ==1
- **yields:** `test_e2e_e6_cooperating_systems_rendered`

### E7 - Q1 latency: hypothesise-batch < U * single-pair (p50/p95 ms)
- **grounds:** spec 3.1 quality not carried by effort - structural Nx saving
- **entry seam:** `attack/hunting/orchestrator_tracing.py::orchestrator_gate_span` + the hypothesise seam stub sleeping 20ms (re-scoped #167: the harness stub is the hypothesise turn, whose fixed cost the fault-level schedule still saves)
- **input:** `candidates` for fault CWE-352 over U=4 units `Service:slug:a..d` each `applies`; single-pair baseline measured as one GateInput with 1 candidate
- **live edge:** none for harness batch proof; blocked when real LLM required (needs real model for token-scaling claim)
- **criterion/metric:** latency criterion: `p50(batch_duration) < 0.8 * U * p50(single_duration)` and `p95(batch_duration) < U * p95(single_duration)`. Metric: `orchestrator_gate_span` duration ms per REASON turn from trace table (fake langfuse span for harness, real LLM span when model available). Threshold 0.8 is harness-only empirical; real-model baseline required to distinguish flawed (batching overhead fixable) vs wrong (model scales linearly fundamental). Fixable if threshold breached by overhead - batching bug; fundamental if LLM prompt tokens grow linearly despite batching.
- **critical examination:** core claim batch cheaper than N singles; stub sleep proves harness not model - needs real LLM distribution for burden of proof. Hidden assumption: token overhead dominates - fails if model does per-unit reasoning anyway. Metric currently collapses flawed vs wrong without real-model baseline.
- **terminal:** harness stub: 1 span `orchestrator-<run[:8]>` with duration_ms; batch < 64ms (4*20*0.8) at p50 over 10 reps; real-model blocked
- **observed:** `SELECT duration_ms FROM trace WHERE name like 'orchestrator-%'` aggregated p50/p95; assert only for harness
- **yields:** `test_e2e_e7_q1_latency_batch_beats_n_singles`
- **verdict:** flawed if harness threshold not met - fixable; wrong if real model intrinsically linear - fundamental re-architecture needed; currently blocked for real-model

### E8 - Q2 accuracy: exhaustiveness, non-overlapping, unfeasibility filtered
- **grounds:** spec 3.2 hypothesis elicitation + Q11 novelty + Q16 merge
- **entry seam:** `arun_orchestration` with fixture L1 graph where 2 Services + 1 System each have not-FALSE projection
- **input:** 3 units all `applies` under CWE-352; stub hypothesise carries all 3 and emits distinct classes; one pruned direction `carried=False` for unreachable unit; ratify/note seams amend + note (re-scoped #167)
- **live edge:** none
- **criterion/metric:** coverage = `minted_config_units / units_where_not_FALSE_and_carried` must be 100%; duplicate_rate = `duplicate_revival_keys / total_configs` must be 0; filtered = pruned directions mint 0 configs. Metric: HuntStore config revival keys distinct count.
- **critical examination:** core claim every plausible locus gets >=1 config without dupes; evidence needs ground truth of which units truly not-FALSE - seeded fixture defines it. Hidden assumption: stub LLM carries correctly - real LLM may miss subtle unit (exhaustiveness failure). Flawed (fixable by prompt tuning) vs wrong (model cannot discriminate faults) - latter fundamental.
- **terminal:** `report.pairs_processed==3`, `configs_ratified==3`; `produced/` has 3 configs with distinct `revival_key`; 0 duplicate hunt_ids; pruned key absent
- **observed:** `HuntStore.read_configs("proj-e8")` grouped by revival_key coverage 100% duplicate 0
- **yields:** `test_e2e_e8_q2_accuracy_coverage`

### E9 - Q3 detail depth: HuntConfig prompt_template sufficient for DECOMPOSE
- **grounds:** spec 3.5 extension + Q8 concretisation
- **entry seam:** `arun_orchestration` -> downstream `HuntConfig` read-back -> `hunting_agent` dry-run `DECOMPOSE` judge
- **input:** same E1 input with stub emitting `research_direction="probe state-changing form for missing anti-CSRF token verification at WebPresentation boundary"`, `vulnerability_classes=["CSRF"]`
- **live edge:** none for harness fields; HuntingAgent judge version is operator-ratified gate for semantic sufficiency
- **criterion/metric:** harness: each ratified HuntConfig `prompt_template.research_direction` len>20 and contains class name not locale/payload, `vulnerability_class` non-empty, `status=="ratified"`, `prompt_template.rationale` non-empty; metric fields_present and avg length>20; semantic: blind HuntingAgent `DECOMPOSE` returns at least one `TestImplementationSpec` with `TestVariant` non-empty when fed the HuntConfig, asserting agent can extend without re-deriving. Hidden assumption len correlates with usefulness - vacuous 72-char CSRF string would pass len but fail blind judge.
- **critical examination:** string presence alone is weak proxy - length equals usefulness is hasty generalisation. Needs blind judge rating to distinguish flawed (missing field fixable via schema) vs wrong (vacuous fluent prose fundamental prompt failure).
- **terminal:** harness 3 configs pass Pydantic and len; blind judge 3/3 `TestVariant` produced with provenance
- **observed:** harness field length checks + `HuntingAgent.dry_run(HuntConfig)` TestVariant count
- **yields:** `test_e2e_e9_q3_detail_depth`
- **verdict:** flawed if missing field - fixable; wrong if fluent but vacuous and blind judge 0 variants - needs human eval fundamental

### E10 - Q4 trajectory soundness: the phase machine's graph envelope (re-scoped #167)
- **grounds:** spec 3.2/3.3 (node-per-phase, G2) + graph envelope 3.8 (no dispatch node - G12, no budget stage - G7)
- **entry seam:** `arun_orchestration` with trace spy on `trace_gate_step` and graph traversal log
- **input:** 2 units fault CWE-352 as E1 with injected hypothesise/ratify/note seams
- **live edge:** none (stub) but real actor run needed to prove prompt adherence beyond harness order
- **criterion/metric:** trace order must be `symbolic-render` -> `gate-decision` per fault with `ledger re-inject` must-not-happen between intra-unit graph_view calls (negative assertion), and supervisor phases observed as `reason` -> `budget` -> `dispatch` via Command(goto=...) order; `build_hunting_graph` nodes still 4. Metric: step order index, ledger_inject_count==faults (2) not tool_calls, node count=4, Command source is supervisor only.
- **critical examination:** harness order proves code, not that LLM internal graph in system prompt is followed - stub bypasses prompt. Needs real actor trace to prove model respects prompt graph vs invents steps. Fixable if harness mis-orders, fundamental if model ignores prompt.
- **terminal:** `trace rows` ordered `symbolic-render` before `gate-decision`; `graph.nodes=={"supervisor","hypothesise","ratify","note"}`; `report.ledger.units_done==2`, `configs_ratified==2`
- **observed:** `trace_gate_step` call log order + `build_hunting_graph().nodes`
- **yields:** `test_e2e_e10_q4_trajectory_soundness`
- **verdict:** flawed if harness mis-orders - fixable; wrong if model invents steps - fundamental prompt hardening needed

### E11 - Q5 hypothesise/note consistency: one note phase per pair, counts align (re-scoped #167)
- **grounds:** spec 3.2/3.3 (the note phase is the pair end - G1)
- **entry seam:** `arun_orchestration` with the `trace_gate_step` emit-mint / note-written steps and graph_view interleaving guard
- **input:** 2 units CWE-352 each with N=1 and N=2 distinct classes respectively (total 3 configs) as E1, with the phase seams injected
- **live edge:** none
- **criterion/metric:** `emit-mint` steps == units_done (2), each precedes exactly one `note-written` with no tool call interleaved (the phase machine's adjacency); `memory.yaml` notes == units_done (2); produced/ configs == distinct classes (3); each note's revival_key matches a config revival_key; call order `emit-mint a -> note-written a -> emit-mint b -> note-written b`. Metric: counts equality + order index + interleaving zero.
- **critical examination:** counts alone prove the phase boundary but not that the harness never interleaves a tool between the mint and its note - stub mimics discipline, real LLM may double-write or interleave graph_view. Flawed (retry logic) fixable vs wrong (prompt ambiguous) fundamental.
- **terminal:** `memory.yaml` notes length 2; produced/ configs length 3; sequential trace `emit-mint a -> note-written a -> emit-mint b -> note-written b` with zero interleaving
- **observed:** `HuntStore.read_configs` / `read_notes` counts + the probe's trace rows with the interleaving check
- **yields:** `test_e2e_e11_q5_mint_note_consistency`
- **verdict:** flawed if counts off by harness - fixable; wrong if model double-writes or interleaves - needs tool guard fundamental

### E12 - Q6 effective tool use: sufficiency loops fire when needed (re-scoped #167/G3)
- **grounds:** spec 3.2 target-knowledge loop + Q11 prior-hunt reflection
- **entry seam:** `attack/hunting/actors.py::build_orchestrator_tool_surface` with instrumented `graph_view`/`hunts_store`/`notes` seam spies
- **input:** a) the surface with `graph_view` invoked when the projection is UNKNOWN; b) the surface with `hunts_store(read)` invoked when prior keys are listed (store has 1 prior config)
- **live edge:** none
- **criterion/metric:** when projection UNKNOWN then `graph_view` invoked >=1 until sufficient; when prior keys non-empty then `hunts_store(read)` invoked >=1. Metric: spy call counts `graph_view_calls>=1`, `hunts_store(read)` calls >=1. The tool surface is EXACTLY the three tools `hunts_store` / `notes` / `graph_view`.
- **critical examination:** core claim the tool-augmented phases use tools conditionally; evidence sufficiency needs observable decision - call log proves use but not sufficiency reasoning. Hidden assumption: UNKNOWN always needs graph_view - but some faults may be decidable without it (false positive). What is missing: negative case (when sufficient, zero calls allowed). Flawed if harness never calls - prompt bug fixable; fundamental if LLM never learns to call despite prompt.
- **terminal:** case a) `graph_view` invoked and the read_fn spy logged >=1; case b) `hunts_store(read)` returns the prior config; opposite sufficient case 0 calls still passes
- **observed:** injected `read_fn` spy and `store_reads` spy call logs
- **yields:** `test_e2e_e12_q6_effective_tool_use`
- **verdict:** flawed if spy counts wrong - fix harness; wrong if LLM ignores prompt - prompt redesign fundamental

### E13 - Q7 LLM reflection strategy: trace shows symbolic-render, sufficiency string, reflection keys, merge marker (re-scoped #167)
- **grounds:** spec 3.2 + fallback skill verbatim
- **entry seam:** `_compose_gate_prompt` + `trace_gate_step` + stub LLM that emits research_direction class-level
- **input:** GateInput as E1 with `prior_minted_keys=["Service:slug:a::CWE-352"]`, stub LLM emits `research_direction="probe CSRF token verification"` (class-level) and 2 candidates where same-class merge collapses to 1
- **live edge:** none (stub) but oracle requires locale leak list
- **criterion/metric:** prompt contains `symbolic-render` preamble, knowledge-sufficiency question substring, `Prior minted-config keys` line, `Same-class merge` instruction; trace rows include `symbolic-render` and `gate-decision` with `per-unit work-items` count 2; `research_direction` contains class token "CSRF" and zero forbidden locale tokens `["Origin:", "/state-change", "attacker.site", "payload"]` via negative check; concrete candidates merged to 1 proves merge executed. Metric: substring presence 5/5, work-items ==units, locale leak 0, merge collapsed.
- **critical examination:** substring check alone passes vacuous reflection - locale negative check and merge collapse prove strategy not just prompt presence. Hidden assumption: prompt substring equals execution - still proxy. Missing independent judge for class-level vs narrowed - added locale oracle fixes part. Flawed (missing marker) fixable vs wrong (fluent but locale-leaking despite marker) needs fine-tuning fundamental.
- **terminal:** `GateDecision.directions[0].research_direction=="probe CSRF token verification"` length >20 with 0 locale tokens; concrete candidates length 1 after merge
- **observed:** prompt string search + trace row + emitted direction field + locale token negative search via oracle list
- **yields:** `test_e2e_e13_q7_reflection_strategy`
- **verdict:** flawed if missing marker - add to skill; wrong if LLM leaks payload despite marker - fundamental alignment

### E14 - store write failure still completes (fail-open O3/O4/O5); the KB seam is retired
- **grounds:** spec 5 O3/O4/O5 + 3.6 fail-open discipline
- **entry seam:** `arun_orchestration` with flaky HuntStore
- **input:** `candidates=[DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm="form Z"),"applies")]`, `HuntStore.write_config`/`update_config`/`append_note` fail the first 2 writes then succeed. The gate's `kb_retrieve_fn` duplicate seam is RETIRED (the gate grounds via the direct `load_materialisation` read, so `kb_degraded` is always `False`).
- **live edge:** none
- **path:** the flaky store fails the pass's first two store writes (the hypothesise create + the ratify upsert) `store_write_failures==2` -> the phase machine keeps serving and the third write (the note) lands (O3 - warned + counted, never a crash)
- **terminal:** `pairs_processed==1`; `report.store_write_failures==2`; `report.ledger.units_done==1`; the failed config writes landed nothing - `read_configs("proj-e14")==[]`
- **observed:** GateInput kb_degraded flag (False - the direct materialisation read is the gate's grounding); the pass's write-failure count
- **yields:** `test_e2e_e14_fail_open_store_kb_graph`

### E15 - concurrency barrier, duplicate-idempotent reads, malformed hypothesise output degrades to carry-bare
- **grounds:** spec 5 duplicate-idempotent + ordering + degradation, spec 3.8 graph last-write serialisation
- **entry seam:** `arun_orchestration` with concurrent pair schedule + `hunts_store(read)` spy + stub hypothesise raising
- **input:** a) concurrency: 2 pairs `CWE-352` and `CWE-639` run concurrently via `asyncio.gather` over two `arun_orchestration` calls on same `run_id` with shared HuntStore; b) duplicate-idempotent: same `read_configs_by_key("Service:slug:a::CWE-352")` called twice in the same hypothesise turn; c) malformed: `hypothesise_fn` raises `ValueError` (unparseable GateDecision)
- **live edge:** none (concurrency via in-process gather, blocked when real worker loop required)
- **criterion/metric:** a) store writes serialised: `HuntStore produced/` rows 2 distinct revival keys, not 1 lost update; b) duplicate reads: second read returns identical list without extra HuntStore side effect, count stays 1 config per key; c) malformed hypothesise: the harness degrades to carry the pair bare with 1 HuntConfig (not crash), `report.store_write_failures` counts only store failures not parse failures
- **critical examination:** core claim the store's per-project lock + the graph's last-write channels provide serialisation; evidence is the final store state not intermediate interleaving. Hidden assumption: asyncio.gather mimics worker loop concurrency - real shared worker loop may queue serially anyway. Flawed (missing lock) fixable via the lock, fundamental if the store cannot serialise.
- **terminal:** a) produced/ configs 2 rows, distinct revival keys; b) duplicate read count 2 but HuntStore rows unchanged 1; c) `pairs_processed==1` with the carried-bare draft
- **observed:** store counts, spy call logs, the hypothesise exception caught and logged `hypothesise turn failed ... carrying`
- **yields:** `test_e2e_e15_concurrency_duplicate_malformed`

## Quiz - operator-supplied bootstrap (one question per missing item)

Each walkthrough is self-contained except the fixtures it cannot invent. A walkthrough whose bootstrap is unanswered stays blocked - not substituted with a double.

- **E1 (per-fault fan-out):** Q: seed L1 fixture - which 2 Service slugs and fault CWE-352 witnesses define the expected 3 configs? Provide slugs + distinct class names (CSRF, IDOR) or carry as blocked.
- **E2 (POST bootstrap):** Q: target tenant - which `project_id` has `hunting_runs` table migrated and which credentials/DB URL does the API use? Without live PG, blocked.
- **E3 (yellow rematch):** REMOVED from scope - the back_edge request to recon is wrongly designed and not an agent tool (operator ruling 2026-08-22). No bootstrap question needed.
- **E4 (budget cut):** Q: budget policy - what deterministic `budget_fn` threshold cuts 3->1, and which revival key is expected survivor?
- **E5 (prunes):** Q: known surface - for the empty-pass assertion, confirm the expected `pruned_by_verdict` count matches the seeded `known_faults` list.
- **E6 (cooperating systems):** Q: L1 System graph fixture - which System kinds and edge families (`CALLS`, `EXPOSED_VIA`) are seeded for System:cache:1's cooperating neighbors?
- **E7 (Q1 latency):** Q: LLM latency baseline - what real model and concurrency provides `single_duration` ms, and what threshold multiplier (0.8) is approved?
- **E8 (Q2 accuracy):** Q: ground truth - for the 3-unit fixture, which units are not-FALSE by predicate so coverage denominator is known?
- **E9 (Q3 detail):** Q: HuntingAgent DECOMPOSE - which agent version judges research_direction sufficient, and what length threshold (>20) is ratified?
- **E10 (Q4 trajectory):** Q: trace backend - which Langfuse/span table holds `orchestrator_gate_span` durations and is it writable in CI?
- **E11 (Q5 mint+note):** Q: store path - confirm `data/` root is writable for count assertions, or is HuntStore tmp_path acceptable?
- **E12 (Q6 tool use):** Q: read seam - which `graph_view` spy and prior `hunts_store(read)` store fixture define the UNKNOWN/keys cases?
- **E13 (Q7 reflection):** Q: locale leak oracle - which forbidden locale tokens (`Origin:`, `/state-change`, payload strings) define class-level vs narrowed?
- **E14 (fail-open):** Q: fault injection - which store failure mode (first 2 appends raise) and KB unavailability stub are used to assert fail-open counts?
- **E15 (concurrency/duplicate/malformed):** Q: worker loop - which shared loop runs concurrent `arun_orchestration` gathers, and what malformed GateDecision JSON triggers carry-bare degrade vs crash?

Blocked walkthroughs carried as blocked (not doubled): E2 if PG unavailable, E6 if neo4j fixture unavailable, E7 if real LLM/trace backend unavailable, E15 concurrency part if worker loop not available - all others use in-process stubs and remain mechanisable.

## Coverage map

- F1 bootstrap: C1, C2, E2
- F2 prompt materialization: C3, C4, C5, E6, E13
- F3 graph workflow: C6, C7, C14, E1, E10
- F4 deterministic phases: C8, C13, E4, E14, E15
- F5 memory: C9, C10, C15, E3, E8, E15
- F6 mint: C11, C12, E1, E11
- dispatch harness: C16
- outlier duplicate/concurrency/malformed: C13, E15
- Q1 latency: E7 (harness proof; blocked for real-model)
- Q2 accuracy: E8
- Q3 detail depth: E9 (harness + blind judge)
- Q4 trajectory soundness: E10 (order + negative ledger re-inject)
- Q5 mint+note consistency: E11 (counts + order + interleaving guard)
- Q6 effective tool use: E12
- Q7 LLM reflection strategy: E13 (substrings + locale negative + merge)

Total: 16 contract + 15 walkthrough = 31 predicates; blocked: up to 4 (E2 PG, E6 neo4j, E7 real LLM, E15 concurrency when worker loop not available) when live edges unavailable, plus E7 real-model part and E9 blind judge when agent unavailable.
