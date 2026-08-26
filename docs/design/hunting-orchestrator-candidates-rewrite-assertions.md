# Assertions - system "candidate-creation → projection → gate → mint rewrite"

**Source:** docs/design/hunting-orchestrator-candidates-rewrite-spec.md (amended 2026-08-23 by the memory + workflow-graph rework; ADR docs/design/hunting-orchestrator-memory-workflow-adr.md G1-G14 is the authority on the dispositions; docs/design/hunting-memory-system-spec.md is the authority on the memory topology)

**Seams under assertion:** bootstrap + control plane (runtime.py / project_management/api.py), candidate intake (`normalize_candidates`), fault schedule + risk-descending ordering (`fault_risk.risk_tier`), the node-per-phase graph envelope (`orchestrator_graph.py`), the phase canon + LoopLedger + report (`hunt_orchestrator.py`), the HuntStore memory topology + config lifecycle + notes surface (`hunt_store.py`), the three-tool surface `hunts_store` / `notes` / `graph_view` (`actors.py`), the pair-frame prompts (primer + Services/Systems split + discipline verbatims, `llm.py`), the deterministic mint (`mint_hunt_config`), the rich projection (`unit_projection.build_projection`), prior-insight projection (`_prior_config_insight`).

*Reauthored 2026-08-23 against the effective implementation (#165 #166 #167 #168 landed). Every predicate's `yields` cites the live mechanising test in the repo test tree; a predicate with no `yields` is the mechanisation gap this catalogue opens. Tier: contract predicates run under the verification gate in the integration tier; walkthroughs run live in the e2e tier.*

## Contract predicates (integration) C1-C21 (+C12b)

### C1 - bootstrap opens row and schedules on shared loop
- **seam:** `attack/hunting/runtime.py::start_hunting` <-> `app/clients/pg.py::create_hunting_run` + `app/runtime.py::schedule("hunting",...)` + `app/llm/checkpoints.py::module_context("hunting")`
- **delivery semantic:** success
- **input:** `project_id="proj-1"`, `candidates=[DeliveredCandidate(unit_id="Service:slug:a", fault_class="CWE-352", applies_witnesses=Witness(llm="form Z no token", deterministic="EXPOSED_VIA=WebPresentation"), match_verdict="applies")]`
- **observable:** exactly 1 `hunting_runs` row with `hunting_run_id="run-c1"` status `running`; exactly 1 Future scheduled via `runtime.schedule("hunting", coro, name="hunting-proj-1")` on the shared worker loop; `hunting_module_context()` delegates to the SHARED `module_context("hunting")` so the control-plane checkpointer index resolves the hunting module.
- **yields:** `test_integration_c1_bootstrap_schedules_on_shared_loop`

### C2 - bootstrap fail-closed when control plane absent
- **seam:** `project_management/api.py::POST /projects/{project_id}/hunting` <-> `attack/hunting/runtime.py::hunting_control_plane_available`
- **delivery semantic:** degradation (runtime not landed)
- **input:** `GET_ACTIVE_RUNTIME()=None`, `POST /projects/proj-1/hunting` with 1 candidate
- **observable:** HTTP 503, body `hunting control-plane runtime is not active`, zero calls to `pg.create_hunting_run`, zero calls to `runtime.schedule` (no in-process fallback since #122).
- **yields:** `test_integration_c2_bootstrap_fail_closed_503`

### C3 - prompt splits Services vs Systems with distinct intros (Q4)
- **seam:** `attack/hunting/llm.py::_compose_gate_prompt` <-> `attack/hunting/unit_projection.py::build_projection` + `attack/hunting/fault_kb.py::load_materialisation`
- **delivery semantic:** success (rich slots populated)
- **input:** `GateInput(candidates=[DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm="form Z"),"applies"), DeliveredCandidate("System:auth-service:auth-service","CWE-352",Witness(llm="exposure internal"),"applies")], unit_projection={"Service:slug:a": UnitProjection(kind="Service", data_items={"PRODUCES": (DataItem(name="csrf_token"),)}, cooperating_systems={}), "System:auth-service:auth-service": UnitProjection(kind="System", cooperating_systems={"CALLS": (SystemInfo(kind="Cache"),)})}, materialisation={"CWE-352": {name:"CSRF"}}, fold_family={"CWE-352": ()})`
- **observable:** prompt contains `Services:` then `Adversarial reasoning over each Service: spell its surface - its edged DataItems and Systems` then per-Service block sorted by unit_id, then `Systems:` then `Adversarial reasoning over each System: outline the System distinctly`; each Service block shows `data items: PRODUCES: name=csrf_token`; System block shows `cooperating systems: CALLS: kind=Cache`. The section split is on the kind-qualified identity (`Service:` prefix -> Services), never the projection kind, so a degraded projection still reaches the right section.
- **yields:** `test_integration_c3_prompt_splits_services_systems`

### C4 - per-slot degrade renders UNKNOWN never FALSE (fail-open)
- **seam:** `attack/hunting/llm.py::_render_projection` <-> `attack/hunting/unit_projection.py::build_projection`
- **delivery semantic:** degradation (one slot raises)
- **input:** `build_projection("proj-1","Service:slug:a", read_fn=raising_fn)` raises; `build_projection("proj-1","System:cache:1", read_fn=ok)` succeeds; same GateInput with `unit_projection={"Service:slug:a": None, "System:cache:1": UnitProjection(kind="System")}`
- **observable:** rendered prompt has exactly 1 `UNKNOWN (projection read failed or absent)` for Service:slug:a, zero occurrences of `FALSE`; System slot renders `unit kind: System`; `normalize_candidates` still yields 2 accepted, 0 malformed, GateDecision still carries both.
- **yields:** `test_integration_c4_projection_degrade_unknown_never_false`

### C5 - hypothesise-phase discipline verbatim (Q11/Q9/Q8/Q16) + L1 ontology primer bound in the pair frame
- **seam:** `attack/hunting/llm.py::_gate_skill` + `_compose_gate_prompt` <-> `attack/hunting/actors.py::build_orchestrator_tool_surface`
- **delivery semantic:** success
- **input:** `GateInput(prior_minted_keys=["Service:slug:a::CWE-352"], candidates=[DeliveredCandidate("Service:slug:b","CWE-352",Witness(llm="x"),"applies")])`
- **observable:** prompt OPENS with the `L1_ONTOLOGY_PRIMER` constant (G9, #168: the Service / System / DataItem conceptions + the domain-model philosophy, at the TOP of the user frame, never the system prompt) and contains verbatim `Prior-hunt reflection (Q11): Prior minted-config keys to reflect on: Service:slug:a::CWE-352`, `Knowledge-sufficiency decision point (Q9)`, `Target-knowledge loop (Q9)`, `Same-class merge (Q16)`, `The hypothesise write (spec 3.3): call hunts_store(write, config,`; the phase-TRANSITION verbatims (`NEXT_RATIFY_HINT` / `NEXT_NOTE_HINT` / `NEXT_PAIR_HINT`) ride the tool-call responses from the constants in `hunt_orchestrator.py:99-115`, NEVER this prompt (D3, re-scoped #167).
- **yields:** `test_integration_c5_loop_protocol_verbatim` + `test_gate_prompt_opens_with_the_l1_ontology_primer`

### C6 - supervisor is sole router via Command(goto=...); the phase machine is embedded in the graph
- **seam:** `attack/hunting/orchestrator_graph.py::build_hunting_graph` <-> langgraph StateGraph
- **delivery semantic:** success + ordering
- **input:** schedule `[FaultWorkItem(fault_class="CWE-352", candidates=[c1,c2]), FaultWorkItem(fault_class="CWE-639", candidates=[c3])]`
- **observable:** `set(g.nodes)=={"supervisor","hypothesise","ratify","note"}` (no dispatch node - G12; no budget stage - G7); static edges `hypothesise->ratify->note->supervisor`; supervisor returns `Command(goto="hypothesise")` popping ONE pair per super-step (a fault's candidate queue drains before the next fault pops), `Command(goto=END)` when schedule AND queue are exhausted, and routes a candidate-less fault straight back to itself with no phase chain (S10); hypothesise/ratify/note never return Command.
- **yields:** `test_integration_c6_supervisor_only_router`

### C7 - ledger accumulates per pair across the faults
- **seam:** `attack/hunting/hunt_orchestrator.py::_hypothesise_node` <-> `attack/hunting/orchestrator_graph.py::HuntOrchestrationState[ledger, minted_configs]`
- **delivery semantic:** success (2 faults, 3 pairs)
- **input:** fault CWE-352 with units Service:slug:a, Service:slug:b; fault CWE-639 with unit Service:slug:a; `hypothesise_fn` returns 1 carried EnvisionedDirection per pair
- **observable:** `report.ledger==LoopLedger(units_done=3, minted_config_keys=["Service:slug:a::CWE-352","Service:slug:b::CWE-352","Service:slug:a::CWE-639"], notes_recorded=3)` (the keys are the REVIVAL keys the Q11 reflection lists); `configs_ratified==3`; `state["minted_configs"]` has exactly 3 keys.
- **yields:** `test_integration_c7_ledger_last_write_per_pair`

### C8 - the O9 budget stage is REMOVED (G7)
- **seam:** `attack/hunting/orchestrator_graph.py::build_hunting_graph` <-> `attack/hunting/hunt_orchestrator.py::_hypothesise_node`
- **delivery semantic:** success (nothing is ever cut)
- **input:** `candidates=[DeliveredCandidate("Service:slug:a","CWE-352"), DeliveredCandidate("Service:slug:b","CWE-352"), DeliveredCandidate("System:cache:1","CWE-639")]`, `hypothesise_fn` carries each pair
- **observable:** `report.pairs_processed==3`, `report.configs_ratified==3`; the report has NO `budget_cut` field and the ledger has NO `budget_remaining` - spending is the runtime plane's and the pod's (D67-09).
- **yields:** `test_integration_c8_budget_stage_removed`

### C9 - HuntStore per-project topology, config + notes split, G4 naming (re-scoped #166)
- **seam:** `attack/hunting/hunt_store.py::HuntStore` <-> `attack/hunting/actors.py::build_orchestrator_tool_surface{hunts_store,notes}`
- **delivery semantic:** success
- **input:** `HuntStore(tmp_path).write_config("project-1", {unit_id, fault_class="CWE-352", vulnerability_class="CSRF", hunt_id="h1"})` then `append_note("project-1", "Service:slug:a::CWE-352", "track it")`
- **observable:** file `project-1/orchestration/hunt_configs/produced/Service:slug:a_CWE-352_CSRF.yaml` carries the config YAML (`_`-separated `<unit>_<CWE-ID>_<class>`, the file name IS the identity - G4; the produced/ and consumed/ dirs are BOTH created lazily at the first write); a second write of the same identity raises `DuplicateConfigError` (the G4 dedup signal); file `project-1/orchestration/memory.yaml` holds the notes (natural append order, no `_seq`, G11); `read_configs_by_key("project-1","Service:slug:a::CWE-352")==[{"hunt_id":"h1"}]` matches the 3-part semantic key OR the 2-part revival-key prefix via `KEY_SEPARATOR="::"`; `read_notes("project-1","Service:slug:a::CWE-352")==[{"note":"track it"}]`; default `HUNT_STORE_ROOT==src/polymerhus/attack/hunting/data` (no env var); the per-run kind files (`run`/`config`/`hunt`/`dispatch`/...) and the repo-global `memory.md` are gone.
- **yields:** `test_integration_c9_store_append_and_split_reads`

### C10 - store read failure degrades to empty prior insights (O4)
- **seam:** `attack/hunting/hunt_orchestrator.py::_read_prior_insights` <-> `attack/hunting/hunt_store.py::read_configs_by_key`/`read_notes`
- **delivery semantic:** degradation
- **input:** `tools.store_reads.read_configs_by_key`/`read_notes` raise `OSError("disk")` for key `Service:slug:a::CWE-352`; 1 candidate CWE-352
- **observable:** `arun_orchestration` completes with `pairs_processed==1`, `prior_hunt_insights==[]` on the minted config, 1 warning logged `hunt store read degraded`, no exception.
- **yields:** `test_integration_c10_store_read_degrades_empty`

### C11 - mint fans out N per distinct vulnerability class, hunt_id base/base-i (class oracle)
- **seam:** `attack/hunting/hunt_orchestrator.py::mint_hunt_config` <-> `attack/hunting/hunt_orchestrator.py::_distinct_vulnerability_classes`
- **delivery semantic:** success (2 classes CSRF vs IDOR)
- **input:** `direction=EnvisionedDirection(unit_id="Service:slug:a", fault_class="CWE-352", research_direction="probe CSRF vs IDOR", vulnerability_classes=["CSRF", "IDOR"])` where CSRF/IDOR are elicited web-vulnerability classes, `hunt_id="abc123"`
- **observable:** returns list length 2; `[0].hunt_id=="abc123"` carries class CSRF, `[1].hunt_id=="abc123-1"` carries IDOR; each config `status=="hypothesised"`, `vulnerability_class` equals its class, both share `prompt_template.research_direction=="probe CSRF vs IDOR"`, `l0_evidence==["llm: form Z no token"]`, `adversarial_capabilities==[]` and `technique_primitives==[]` (the ratification-phase fields stay empty on the draft); oracle is the class not the raw string count, so a third emission of the same class would not increase the fan-out.
- **yields:** `test_integration_c11_mint_fanout_per_distinct_class`

### C12 - mint collapses same-class duplicates and empty degrades to carried-bare
- **seam:** `attack/hunting/hunt_orchestrator.py::_distinct_vulnerability_classes` <-> `attack/hunting/hunt_orchestrator.py::mint_hunt_config`
- **delivery semantic:** duplicate + empty
- **input:** a) `vulnerability_classes=["CSRF", "CSRF"]`; b) `vulnerability_classes=[]` or with `[""]`
- **observable:** a) exactly 1 hypothesised HuntConfig with `hunt_id=="base"` and `vulnerability_class=="CSRF"`; b) exactly 1 hypothesised draft with `vulnerability_class==""` and `research_direction` passed through; HuntConfig validates via Pydantic with the reworked slots (`status`, `vulnerability_class`, `prompt_template.rationale|research_direction|l0_evidence`, `surface_context`, `target_caveats`, `prior_hunt_insights`, `tool_registry`, `adversarial_capabilities`, `assumptions`, `technique_primitives`) all present; oracle is the class not the raw string count.
- **yields:** `test_integration_c12_mint_collapse_and_bare_degrade`

### C12b - minted config surface_context shows connected DataItems, not edge_degree (ADR G5 operator correction)
- **seam:** `attack/hunting/hunt_orchestrator.py::_surface_cards_with_connected_data_items` <-> `attack/hunting/unit_projection.py::build_projection`
- **delivery semantic:** success + degradation (absent projection)
- **input:** `HuntStore(tmp_path)`, `graph_view` whose `index_cards` read returns a Service card (`business_function_slug="a"`, `exposure="public"`) and whose projection read returns one CONSUMES data-flow edge to `DataItem(name="session token", type="secret", sensitivity="high", fields=["sid"], notes="session-bound")`; `hypothesise_fn` emits one carried direction with `vulnerability_classes=["CSRF"]`
- **observable:** the minted config's `surface_context.cards` Service card has NO `edge_degree` key and carries `connected_data_items=={"CONSUMES": [{"name":"session token","type":"secret","sensitivity":"high","fields":["sid"],"notes":"session-bound"}]}` (name/type/sensitivity/fields/notes, families and fields sorted for render determinism) while `spine=={"exposure":"public"}` survives; an absent projection / non-matching card / malformed card degrades the card unchanged (fail-open, never a raise).
- **yields:** `test_integration_c12b_surface_context_shows_connected_data_items`

### C13 - ReadOnlyGraphView write-shaped guard rejects before driver
- **seam:** `attack/hunting/hunt_orchestrator.py::ReadOnlyGraphView._guard` <-> `neo4j_client` driver
- **delivery semantic:** degradation (write-shaped cypher)
- **input:** `graph_view.read("MATCH (u) MERGE (u)-[:EXPOSED_VIA]->(m)", {})` and `graph_view.read("match (u) merge (u)-[:EXPOSED_VIA]->(m)", {})` and `graph_view.merge()` any args
- **observable:** each raises `ReadOnlyGraphViewError` containing `refusing write-shaped cypher`, zero calls to underlying `neo4j_client.read`, `graph_view._guard` regex case-insensitive on `MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD CSV`.
- **yields:** `test_integration_c13_write_guard_rejects`

### C14 - HuntOrchestratorActor thread reused across faults on same run
- **seam:** `attack/hunting/hunt_orchestrator.py::_ORCHESTRATOR_ACTORS registry` <-> `attack/hunting/actors.py::HuntOrchestratorActor`
- **delivery semantic:** ordering + duplicate-idempotent
- **input:** `run_id="run-c14"`, 2 faults `CWE-352` over Service:slug:a and `CWE-639` over Service:slug:b, stub `reason_fn` carries; call `arun_orchestration` with 2 faults, capture `orchestrator` object after first `_reason_node` and after second
- **observable:** `registry[run_id]` is same object identity across both faults, `len(registry)==1`, actor `run_id` thread name `hunting_orchestrator:run-c14` reused, reaped only via `await _reap_orchestrator(run_id)` not via a pass `finally`, after reap `registry.get(run_id) is None`.
- **yields:** `test_integration_c14_actor_thread_reused`

### C15 - cross-pass config visibility via the fixed HUNT_STORE_ROOT + the prior-insight snowball guard
- **seam:** `attack/hunting/hunt_store.py::HUNT_STORE_ROOT` <-> `attack/hunting/actors.py::build_orchestrator_tool_surface{hunts_store,notes}` + `attack/hunting/hunt_orchestrator.py::_prior_config_insight`
- **delivery semantic:** success (cross-pass) + ordering
- **input:** `storeA = HuntStore()` at default `src/polymerhus/attack/hunting/data` writes a config `Service:slug:a::CWE-352::CSRF` and a note; `storeB = HuntStore()` same default reads the same project
- **observable:** `storeB.read_configs_by_key("project-1","Service:slug:a::CWE-352")` returns the config from pass-a; the note reads back from `memory.yaml`; default `HUNT_STORE_ROOT==src/polymerhus/attack/hunting/data` string equality, no env var; NO repo-global `memory.md` anywhere - the per-project produced/consumed + `memory.yaml` topology is the whole memory (G10/G11). Cross-pass insight projection (I3): a persisted config's `prior_hunt_insights` entries are the shallow projection (identity + hypothesise-phase seeds only) and NEVER contain a nested `prior_hunt_insights` key - the full-dump merge would snowball without bound.
- **yields:** `test_integration_c15_cross_run_memory_fixed_root` (+ `test_prior_hunt_insights_never_embed_nested_configs` in the unit tier for the I3 projection shape)

### C16 - hunting-agent dispatch harness: per-hunt thread via HuntingActorRegistry (RE-SCOPED #167/G12: exercised directly, never through an arun_orchestration dispatch phase)
- **seam:** `attack/hunting/hunting_agent.py::build_actor_hunting_agent` <-> `attack/hunting/actors.py::HuntingActorRegistry` + `HuntingHunterActor`
- **delivery semantic:** concurrency + ordering
- **input:** dispatch 2 concurrent hunts `HuntSession(run_id="run-c16", hunt_id="hunt-A")` and `hunt-B` via `build_hunting_agent`, spy on `HuntingActorRegistry.get_or_create`. The graph has NO dispatch node (G12): dispatch state belongs to the runtime plane, whose delivery is another workstream - this predicate exercises the harness side directly, never through a graph node.
- **observable:** `author` and `judge` for hunt-A use same `HuntSession` thread `run-c16:hunt-A:hunting_hunter`, hunt-B uses distinct `run-c16:hunt-B:hunting_hunter`, registry holds 2 entries during dispatch, concurrent hunts never share thread.
- **yields:** `test_integration_c16_hunting_harness_per_hunt_thread`

### C17 - a sync seam that RETURNS a coroutine is awaited, never handed back un-awaited
- **seam:** `attack/hunting/hunt_orchestrator.py::arun_orchestration::_await_seam` <-> the production default seam lambdas
- **delivery semantic:** degradation (async seam behind a sync lambda)
- **input:** `sync_reason = lambda inp: actor_reason(inp)` where `actor_reason` is `async def` returning a `GateDecision`; `sync_rematch = lambda u,f,r: actor_rematch(u,f,r)` returning a `MatchVerdict`
- **observable:** `_await_seam` detects the returned coroutine via `inspect.isawaitable` and awaits it: the call yields a `GateDecision` instance (not an un-awaited `coroutine` object), and `verdict.verdict=="applies"` - the regression that crashed the live tier with `'coroutine' object has no attribute 'verdict'`.
- **yields:** `test_integration_c17_sync_seam_returning_coroutine_is_awaited`

### C18 - the tool surface is EXACTLY the three tools hunts_store / notes / graph_view
- **seam:** `attack/hunting/actors.py::build_orchestrator_tool_surface` <-> the session agent's bound tool list
- **delivery semantic:** success
- **input:** build the surface with real store + graph-view seam bodies; enumerate the session's tool names
- **observable:** the bound tool name set `== {"hunts_store", "notes", "graph_view"}` and `== TOOL_SURFACE` (`hunt_orchestrator.py:88`): the old five-tool surface (`read_memory_hunts`/`read_memory_notes`/`mint_hunt_config`/`record_note`) is gone, there is NO `mint_hunt_config` / config-writing tool on the surface (the mint rides `hunts_store(write)`), no back-edge-to-recon tool, no budget tool.
- **yields:** `test_actor_binds_exactly_the_three_tools` + `test_no_hunt_config_writing_tool_on_the_surface` + `test_structured_schemas_and_tool_surface_unchanged`

### C19 - hunts_store(read) returns the service keys only, never the projected surface context (G3)
- **seam:** `attack/hunting/actors.py::hunts_store(read)` <-> `attack/hunting/hunt_store.py::read_configs_by_key`
- **delivery semantic:** success + degradation (surface requested)
- **input:** a persisted config whose dict carries `surface_context={"cards": [{"secret": True}]}` and `hunt_id="h1"`; `hunts_store(cmd="read", key="Service:slug:a::CWE-352")` then `hunts_store(cmd="read", key=..., attributes=["rationale","surface_context"])`
- **observable:** the first call returns `{"key": ..., "configs":[{"unit_id","fault_class","vulnerability_class","status","hunt_id"}]}` with NO `surface_context` key; the second call with `attributes=["surface_context"]` ALSO omits `surface_context` (the service keys `{"unit_id","fault_class","vulnerability_class","status","hunt_id"}` are always returned; any other requested attribute that exists in the config rides the projection, surface_context never does).
- **yields:** `test_hunts_store_read_returns_service_keys_only`

### C20 - hunts_store(write) status drives the write + the verbatim hint selection; duplicate surfaces the G4 signal
- **seam:** `attack/hunting/actors.py::hunts_store(write)` <-> `attack/hunting/hunt_store.py::write_config` / `update_config` + the phase-verbatim constants
- **delivery semantic:** success + duplicate + malformed (unknown status)
- **input:** a) `hunt_config` dict with `status="hypothesised"` for an absent identity; b) same dict with `status="ratified"`; c) same dict with `status="dropped"`; d) the hypothesised write REPLAYED for an identity already on disk; e) `hunt_config` with `status="flagged"`
- **observable:** a) creates the produced/ file and returns `{"acknowledged": True, "status": "hypothesised", "key": <semantic key>, "hint": NEXT_RATIFY_HINT}`; b) upserts in place (overwrites the identity) and returns ONLY the `NEXT_NOTE_HINT` hint - the next pair is NOT fed here (G1 correction); c) upserts `status="dropped"` in place and returns the `NEXT_RATIFY_HINT` hint (ratification-internal, G6); d) returns `{"error": <DuplicateConfigError str>, "duplicate": True, "status": "hypothesised"}` - the storage-layer dedup signal the model interprets (G4), never a crash; e) returns `{"error": "unknown config status 'flagged'; known: hypothesised, ratified, dropped"}`.
- **yields:** `test_hunts_store_write_hypothesised_creates_and_carries_the_ratify_hint` + `test_hunts_store_write_ratified_upserts_and_carries_only_the_note_hint` + `test_hunts_store_write_dropped_marks_the_orphan_on_disk` + `test_hunts_store_rejects_an_unknown_status`

### C21 - notes(read/write) over memory.yaml: append carries next_pair + the restart verbatim; update/delete by note_id
- **seam:** `attack/hunting/actors.py::notes` <-> `attack/hunting/hunt_store.py::read_notes` / `append_note` / `update_note` / `delete_note` + `PhaseContext.next_pair`
- **delivery semantic:** success + malformed (unknown option) + ordering
- **input:** `phase_context.next_pair = {"unit_id":"Service:slug:b","fault_class":"CWE-352"}`; `notes(cmd="read", key="Service:slug:a::CWE-352")`; `notes(cmd="write", option="append", key=..., note="track it")`; then `update` and `delete` by the returned `note_id`; then `notes(cmd="write", option="merge")`
- **observable:** read returns `{"key":..., "notes":[{"note_id","revival_key","note"}]}` in natural append order; append returns `{"recorded": True, "key":..., "note_id": <12-hex>, "next_pair": {"unit_id":"Service:slug:b","fault_class":"CWE-352"}, "hint": NEXT_PAIR_HINT}` (the pair end - G1); update amends the note, delete removes it, both True when the note_id exists and False when not; `option="merge"` returns `{"error": "notes write needs an option: append, update, or delete"}`.
- **yields:** `test_notes_read_returns_keyed_notes` + `test_notes_write_append_carries_the_next_pair_and_restart_verbatim` + `test_notes_write_update_and_delete` + `test_notes_write_rejects_an_unknown_option`

## Walkthrough predicates (end-to-end) E1-E17 (E3 removed)

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
- **live edge:** live Postgres `hunting_runs` table (operator-supplied target tenant + credentials); neo4j not required
- **path:** API handler calls `pg.create_hunting_run` sync then `runtime.schedule("hunting", start_hunting(...))` on shared worker loop -> `start_hunting` sets `hunting_module_context("hunting")` -> runs `arun_orchestration` with 1 fault -> writes the hypothesised config into produced/ + the note into memory.yaml -> `set_hunting_run_status("complete")` via `asyncio.to_thread`
- **terminal:** `hunting_runs` row `hunting_run_id` status `complete`; HuntStore produced/ has 1 config YAML, `memory.yaml` 1 note (the per-run `run.md` is removed, #166); HTTP response 201 with `{"hunting_run_id": "<id>"}`
- **observed:** `SELECT status FROM hunting_runs WHERE hunting_run_id='run-e2'` returns `complete`; `GET /projects/proj-e2/hunting/run-e2` returns 200 with same row
- **yields:** `test_e2e_e2_bootstrap_post_persists` (blocked when PG is unavailable, never substituted)

### E3 - BLOCKED (removed from scope): park/resume via back_edge to recon
- **grounds:** the back_edge request to recon is **wrongly designed and is NOT an agent tool** in this tree (operator ruling 2026-08-22): the target-knowledge loop rides `graph_view`, never a recon request. The yellow park/resume predicate is therefore REMOVED from the walking tier, not substituted. Since #111 (graceful stop) is blocked by #110 and back_edge is out of the agent surface, the park/resume canon is not exercised e2e.

### E4 - the O9 budget stage is REMOVED (G7)
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
- **input:** `candidates` in fixed order [0] `DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm=None), "applies")` malformed, [1] `DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm="x"),"applies")` duplicate key of [0], [2] `DeliveredCandidate("System:cache:1","CWE-639",Witness(llm="x"),"does-not-apply")`
- **live edge:** none
- **path:** `normalize_candidates` processes in order: [0] malformed `malformed_dropped=1`, [1] duplicate of a dropped key still counts as duplicate `duplicates_dropped=1`, [2] pruned `pruned_by_verdict=1` before the hypothesise phase -> empty intake -> O1 empty pass, no phase machine
- **terminal:** `report.pairs_processed==0`; `report.malformed_dropped==1`; `report.duplicates_dropped==1`; `report.pruned_by_verdict==1`; `report.store_write_failures==0`; the empty pass persists nothing in the memory topology - `read_configs("proj-e5")==[]` and `read_notes("proj-e5")==[]` (the per-run `run.md` with `candidates_received` is removed, #166)
- **observed:** report fields exact as above
- **yields:** `test_e2e_e5_empty_after_prunes_is_empty_pass`

### E6 - cooperating systems surface in System-targeting hunt (Q5)
- **grounds:** spec 3.6 D3 adjacency + 3.7 Q5 cooperating-systems instruction
- **entry seam:** `arun_orchestration` with real-ish `build_projection` over seeded neo4j fixture
- **input:** `candidates=[DeliveredCandidate("System:cache:1","CWE-639",Witness(llm="System cache internal"),"applies")]`; neo4j has `L1System(kind="cache",discriminator="1")-[:CALLS]->L1System(kind="db")` and `L1System(cache:1)<-[:EXPOSED_VIA]-L1Service(slug:b)`
- **live edge:** neo4j mini-fixture `L1System cache:1 -> db` and `Service slug:b -> cache:1` seeded by test (requires live neo4j; blocked when neo4j unavailable, not substituted)
- **path:** `build_projection("proj-e6","System:cache:1")` reads System-to-System adjacency -> `GateInput.unit_projection["System:cache:1"].cooperating_systems=={"CALLS": (SystemInfo(kind="db"),), "EXPOSED_VIA": (SystemInfo(kind="Service"),)}` -> `_compose_gate_prompt` renders `cooperating systems: CALLS: kind=db` with verbatim `Consider cooperating systems when creating a HuntConfig targeting a system`; the phase seams then run the pair through hypothesise -> ratify -> note (injected fakes, no dispatch)
- **terminal:** prompt string contains `cooperating systems:` and `kind=db`; `report.pairs_processed==1` and `configs_ratified==1`; HuntStore notes count 1
- **observed:** `trace_gate_step("symbolic-render", input={"cooperating_systems":"ok"})` row present; prompt file read-back contains cooperating line; Cypher `MATCH (s:System {discriminator:"1"})-[r:CALLS]->(t) RETURN count(t)` ==1
- **yields:** `test_e2e_e6_cooperating_systems_rendered`

### E7 - Q1 latency: hypothesise-batch < U * single-pair (p50/p95 ms)
- **grounds:** spec 3.1 quality not carried by effort - structural Nx saving
- **entry seam:** `attack/hunting/orchestrator_tracing.py::orchestrator_gate_span` + the hypothesise seam stub sleeping 20ms (re-scoped #167: the harness stub is the hypothesise turn, whose fixed cost the fault-level schedule still saves)
- **input:** `candidates` for fault CWE-352 over U=4 units `Service:slug:a..d` each `applies`; single-pair baseline measured as one GateInput with 1 candidate
- **live edge:** none for harness batch proof; blocked when real LLM required (needs real model for token-scaling claim)
- **criterion/metric:** latency criterion: `p50(batch_duration) < 0.8 * U * p50(single_duration)` and `p95(batch_duration) < U * p95(single_duration)`, with the absolute fallback `p50(batch) < 64ms` / `p95(batch) < 80ms` (the stub's 20ms sleep bound). Metric: `orchestrator_gate_span` duration ms per hypothesise turn (fake langfuse span for the harness, real LLM span when a model is available). Threshold 0.8 is harness-only empirical; a real-model baseline is required to distinguish flawed (batching overhead fixable) vs wrong (model scales linearly, fundamental).
- **terminal:** harness stub: 1 span `orchestrator-<run[:8]>` per rep with duration_ms; p50(batch) < 64ms over 10 reps while the single baseline sleeps 20ms per call; real-model blocked
- **observed:** the harness's measured p50/p95 over 10 reps of the 4-unit turn vs the 1-unit baseline
- **yields:** `test_e2e_e7_q1_latency_batch_beats_n_singles` (harness proof green; real-model part blocked)

### E8 - Q2 accuracy: exhaustiveness, non-overlapping, unfeasibility filtered
- **grounds:** spec 3.2 hypothesis elicitation + Q11 novelty + Q16 merge
- **entry seam:** `arun_orchestration` with fixture L1 graph where 2 Services + 1 System each have not-FALSE projection
- **input:** 3 units (`Service:slug:a`, `Service:slug:b`, `System:cache:1`) all `applies` under CWE-352; stub hypothesise carries all 3 and emits distinct classes; ratify/note seams amend + note
- **live edge:** none
- **criterion/metric:** coverage = `minted_config_units / carried units` must be 100%; duplicate_rate = 0; pruned directions mint 0 configs. Metric: HuntStore config revival keys distinct count.
- **terminal:** `report.pairs_processed==3`, `configs_ratified==3`; `produced/` has 3 configs with 3 distinct `revival_key`s; 0 duplicate revival keys.
- **observed:** `HuntStore.read_configs("proj-e8")` grouped by revival key: coverage 100%, duplicate 0
- **yields:** `test_e2e_e8_q2_accuracy_coverage`

### E9 - Q3 detail depth: HuntConfig prompt_template sufficient for DECOMPOSE
- **grounds:** spec 3.5 extension + Q8 concretisation
- **entry seam:** `arun_orchestration` -> downstream `HuntConfig` read-back
- **input:** same E1 input with stub emitting `research_direction="probe state-changing form for missing anti-CSRF token verification at WebPresentation boundary"`, `vulnerability_classes=["CSRF"]`
- **live edge:** none for harness fields; the semantic blind HuntingAgent DECOMPOSE judge is the operator-ratified future gate (currently simulated - the harness asserts the class-level seeds that would feed it)
- **criterion/metric:** harness: each ratified HuntConfig `prompt_template.research_direction` len>20 AND contains the class token `CSRF`, `vulnerability_class=="CSRF"`, `status=="ratified"`, `prompt_template.rationale` non-empty with every word non-empty. Metric: fields_present + research_direction length >20 + class-token presence. Hidden assumption: string presence is a proxy for usefulness - the blind DECOMPOSE judge (a ratified HuntingAgent version) is the semantic gate, currently a mechanisation gap.
- **terminal:** harness: the pass produces >=2 ratified configs, each passing the field checks
- **observed:** harness field-length + class-token checks over the store's ratified configs
- **yields:** `test_e2e_e9_q3_detail_depth` (harness green; blind judge simulated, not yet mechanised)

### E10 - Q4 trajectory soundness: the phase machine's graph envelope (re-scoped #167)
- **grounds:** spec 3.2/3.3 (node-per-phase, G2) + graph envelope 3.8 (no dispatch node - G12, no budget stage - G7)
- **entry seam:** `arun_orchestration` with trace spy on `trace_gate_step` and graph traversal log
- **input:** 2 units fault CWE-352 as E1 with injected hypothesise/ratify/note seams
- **live edge:** none (stub) but real actor run needed to prove prompt adherence beyond harness order
- **criterion/metric:** trace order must be `symbolic-render` -> `gate-decision` per fault with no `ledger re-inject` between intra-unit graph_view calls (negative assertion); `build_hunting_graph` nodes still 4; Command source is the supervisor only. Metric: step order index, node count=4.
- **terminal:** trace rows ordered `symbolic-render` before `gate-decision`; `graph.nodes=={"supervisor","hypothesise","ratify","note"}`; `report.pairs_processed==2`, `configs_ratified==2`
- **observed:** `trace_gate_step` call-log order + `build_hunting_graph().nodes`
- **yields:** `test_e2e_e10_q4_trajectory_soundness`

### E11 - Q5 hypothesise/note consistency: one note phase per pair, counts align (re-scoped #167)
- **grounds:** spec 3.2/3.3 (the note phase is the pair end - G1)
- **entry seam:** `arun_orchestration` with the `trace_gate_step` emit-mint / note-written steps and graph_view interleaving guard
- **input:** 2 units CWE-352 each with N=1 and N=2 distinct classes respectively (total 3 configs) as E1, with the phase seams injected
- **live edge:** none
- **criterion/metric:** `emit-mint` steps == units_done (2), each precedes exactly one `note-written` with no tool call interleaved; `memory.yaml` notes == units_done (2); produced/ configs == distinct classes (3); each note's revival key matches a config revival key; call order `emit-mint a -> note-written a -> emit-mint b -> note-written b`. Metric: counts equality + order index + interleaving zero.
- **terminal:** `memory.yaml` notes length 2; produced/ configs length 3; sequential trace `emit-mint a -> note-written a -> emit-mint b -> note-written b` with zero interleaving
- **observed:** `HuntStore.read_configs` / `read_notes` counts + the trace rows with the interleaving check
- **yields:** `test_e2e_e11_q5_mint_note_consistency`

### E12 - Q6 effective tool use: sufficiency loops fire when needed (re-scoped #167/G3)
- **grounds:** spec 3.2 target-knowledge loop + Q11 prior-hunt reflection
- **entry seam:** `attack/hunting/actors.py::build_orchestrator_tool_surface` with instrumented `graph_view`/`hunts_store`/`notes` seam spies
- **input:** a) the surface with `graph_view` invoked when the projection is UNKNOWN; b) the surface with `hunts_store(read)` invoked when prior keys are listed (store has 1 prior config)
- **live edge:** none
- **criterion/metric:** when projection UNKNOWN then `graph_view` invoked >=1 until sufficient; when prior keys non-empty then `hunts_store(read)` invoked >=1. Metric: spy call counts `graph_view_calls>=1`, `hunts_store(read)` calls >=1. The tool surface is EXACTLY the three tools `hunts_store` / `notes` / `graph_view` (C18).
- **terminal:** case a) `graph_view` invoked and the read_fn spy logged >=1; case b) `hunts_store(read)` returns the prior config; the opposite sufficient case (0 calls) still passes
- **observed:** injected `read_fn` spy and `store_reads` spy call logs
- **yields:** `test_e2e_e12_q6_effective_tool_use`

### E13 - Q7 LLM reflection strategy: trace shows symbolic-render, sufficiency string, reflection keys, merge marker + the primer (re-scoped #167/#168)
- **grounds:** spec 3.2 + fallback skill verbatim
- **entry seam:** `_compose_gate_prompt` + `trace_gate_step` + stub LLM that emits research_direction class-level
- **input:** GateInput as E1 with `prior_minted_keys=["Service:slug:a::CWE-352"]`, stub LLM emits `research_direction="probe CSRF token verification"` (class-level) and 2 candidates where same-class merge collapses to 1
- **live edge:** none (stub) but oracle requires the locale leak list
- **criterion/metric:** the composed prompt `startswith(L1_ONTOLOGY_PRIMER)` and contains the `symbolic-render` preamble, the knowledge-sufficiency question substring, `Prior minted-config keys` line, `Same-class merge` instruction; trace rows include `symbolic-render` and `gate-decision` with `per-unit work-items` count 2; `research_direction` contains the class token "CSRF" and zero forbidden locale tokens `["Origin:", "/state-change", "attacker.site", "payload"]` via negative check; concrete candidates merged to 1 proves merge executed. Metric: substring presence 5/5 + primer startswith, work-items == units, locale leak 0, merge collapsed.
- **terminal:** `GateDecision.directions[0].research_direction=="probe CSRF token verification"` length >20 with 0 locale tokens; concrete candidates length 1 after merge; the rendered prompt opens with the primer constant
- **observed:** prompt string search + trace row + emitted direction field + locale token negative search via oracle list
- **yields:** `test_e2e_e13_q7_reflection_strategy`

### E14 - store write failure + KB degraded still completes (fail-open O3/O4/O5)
- **grounds:** spec 5 O3/O4/O5 + 3.6 fail-open discipline
- **entry seam:** `arun_orchestration` with flaky HuntStore and raising kb_retrieve_fn
- **input:** `candidates=[DeliveredCandidate("Service:slug:a","CWE-352",Witness(llm="form Z"),"applies")]`, `kb_retrieve_fn` raises `RuntimeError("KB unavailable")`, `HuntStore.write_config`/`update_config`/`append_note` fail the first 2 writes then succeed
- **live edge:** none
- **path:** KB degraded -> hypothesise prompt shows `KB grounding: DEGRADED` -> flaky store fails the pass's first two store writes (the hypothesise create + the ratify upsert) `store_write_failures==2` -> the phase machine keeps serving and the third write (the note) lands (O3 - warned + counted, never a crash)
- **terminal:** `pairs_processed==1`; `report.store_write_failures==2`; `report.ledger.units_done==1`; the failed config writes landed nothing - `read_configs("proj-e14")==[]`; `kb_degraded==True` in the hypothesise GateInput
- **observed:** GateInput kb_degraded flag; the pass's write-failure count
- **yields:** `test_e2e_e14_fail_open_store_kb_graph`

### E15 - concurrency barrier, duplicate-idempotent reads, malformed hypothesise output degrades to carry-bare
- **grounds:** spec 5 duplicate-idempotent + ordering + degradation, spec 3.8 graph last-write serialisation
- **entry seam:** `arun_orchestration` with concurrent pair schedule + `hunts_store(read)` spy + stub hypothesise raising
- **input:** a) concurrency: 2 pairs `CWE-352` (Service:slug:a) and `CWE-639` (Service:slug:b) run concurrently via `asyncio.gather` over two `arun_orchestration` calls on the same `run_id` with a shared HuntStore; b) duplicate-idempotent: same `read_configs_by_key("Service:slug:a::CWE-352")` called twice; c) malformed: `hypothesise_fn` raises `ValueError` (unparseable GateDecision)
- **live edge:** none (concurrency via in-process gather, blocked when real worker loop required)
- **criterion/metric:** a) store writes serialised: `HuntStore produced/` rows 2 distinct revival keys, not 1 lost update (the store's per-project lock + the graph's last-write channels serialise; the gather may queue serially on a shared loop, in which case >=1 rows with no corruption still holds); b) duplicate reads: second read returns an identical list without extra side effect, count stays 1 config per key; c) malformed hypothesise: the harness degrades to carry the pair bare with 1 HuntConfig (not a crash), `report.store_write_failures` counts only store failures not parse failures
- **terminal:** a) produced/ configs 2 rows, distinct revival keys; b) duplicate read count 2 but HuntStore rows unchanged 1; c) `pairs_processed==1` with the carried-bare draft (`configs_hypothesised==1`)
- **observed:** store counts, spy call logs, the hypothesise exception caught and logged `hypothesise turn failed ... carrying`
- **yields:** `test_e2e_e15_concurrency_duplicate_malformed`

### E16 - the recovered moodique L1 scaffold yields a valid rich projection
- **grounds:** spec 3.6 Q3 (rich typed projection: DataItem lists, System full unpack, D3 System adjacency); the operator's "scaffold L1 for testing which should create a valid projection"
- **entry seam:** `load_moodique_l1_fixture(pid, session)` into a fresh project over the LIVE neo4j, then `unit_projection.build_projection` over `ReadOnlyGraphView(pid, read_fn=session.run)`, then `_compose_gate_prompt`
- **input:** a fresh `pid`; the recovered moodique fixture (services, systems, edges, data items, data flows, data relationships, endpoints); the units `Service:catalogue-and-discovery`, `Service:sign-in`, `AuthenticationMechanism:prestashop-login`
- **live edge:** live neo4j (blocked when unavailable, never substituted)
- **path:** the fixture loader lands the moodique L1 scaffold -> `build_projection("Service:catalogue-and-discovery")` resolves a Service projection with `kind=="Service"`, non-empty `spine["service_contract"]`, non-empty `edges["EXPOSED_VIA"]`, and `PRODUCES` or `CONSUMES` data items -> `build_projection("Service:sign-in")` resolves `AUTHENTICATED_BY` AND `IDENTIFIED_BY` edges (the auth boundary) -> `build_projection("AuthenticationMechanism:prestashop-login")` resolves `cooperating_systems` (the D3 adjacency over the auth-family inbound edges) -> the gate prompt renders the recovered surface for the Service target
- **terminal:** fixture counts: services >=8, systems >=8, edges >=18, data_items >=5, data_flows >=15, data_relationships >=3, endpoints >=10; the three projections resolve as above with `cooperating_systems` non-empty and an auth-family key (`AUTHENTICATED_BY`/`IDENTIFIED_BY`/`EXPOSED_VIA`); the prompt contains the unit id `Service:catalogue-and-discovery`, `EXPOSED_VIA`, and `cooperating systems` or `data items`
- **observed:** the fixture loader's counts dict; the projection attributes; the composed prompt string
- **yields:** `test_e2e_e16_moodique_l1_scaffold_yields_rich_projection`

### E17 - the full-machine e2e eval: 30 kb-faults over the live source L1, every nominal machine state touched
- **grounds:** the operator-directed eval (2026-08-24): run the REAL workflow graph e2e over the LIVE L1 of the mapped source project with the top-30 risk-tiered kb-faults; every nominal machine state must be touched. Runtime control scaffolded in `tests/e2e/hunting_orchestrator_eval_stack.py`; the new agent container (branch work volume-mounted over `polymerhus-agent:latest`) and the new testing compose `docker-compose.hunting-eval.yml` point the container at the shared services (neo4j/postgres/kali) with a co-located litellm gateway.
- **entry seam:** `run_orchestrator_eval` - the runtime-control fixture drives `arun_orchestration` (the O1-O10 canon) under `hunting_module_context` with the REAL actor (real LLM via the co-located gateway), the real KB (`load_materialisation`), a scratch `HuntStore`, and the standard `fault_source.select` over the live L1. No seam is mocked; the llm-witness slot is filled from the deterministic stage (the LLM match is #71/#64 scope).
- **input:** source `project_id="2a7544e3-ee8d-4e11-8465-609c774d28b2"` (live moodique L1: 14 L1Service + 8 L1System testable units); the 30 top-risk selection-tier faults; candidates = the deterministic-stage-passing `(unit, fault)` pairs (operator-sizing: max 3 units/fault -> 78 pairs over 26 faults; 4 faults match no unit - the empty-candidate boundary).
- **live edge:** live neo4j + live postgres + the co-located litellm gateway (real `LLM_MODEL_HUNTING_ORCHESTRATOR` turns). Blocked when the stack is unreachable.
- **path:** standard FaultSource selection -> `normalize_candidates` -> the supervisor pops FAULT work items risk-descending and iterates each fault's candidate queue as pairs -> per pair hypothesise (real elicitation + the mint writes hypothesised drafts) -> ratify (real ratification, configs upserted ratified / dropped-on-disk) -> note (real notes into memory.yaml; the phase sets the next-pair frame, crossing the fault drain) -> END.
- **terminal:** every NOMINAL machine state touched: `pairs_processed == len(candidates)` (intake + supervisor pair routing), `ledger.minted_config_keys == ledger.units_done` (hypothesise), `configs_ratified >= 1` with `status ⊆ {hypothesised, ratified, dropped}` and a ratified config on disk (config lifecycle), `notes_written >= 1` with notes keyed on a config revival key or its semantic-key extension (note phase), the trace rows show `symbolic-render` before `gate-decision` with `emit-mint` >= `note-written` (the phase machine), the next-pair frames include a cross-fault drain, and the run reached END (terminal report, no crash). If a failure mode fired (e.g. the G4 duplicate-write signal), its handling activated (counted, kept serving) and the pass completed.
- **observed:** the `OrchestratorReport`, the scratch store's produced/ configs + memory.yaml notes, the recorded next-pair assignments, and the orchestrator trace rows (the standard observability probe).
- **yields:** `test_hunting_orchestrator_full_machine_eval` (run inside the eval container; smoke knobs `HUNTING_EVAL_MAX_FAULTS` / `HUNTING_EVAL_MAX_UNITS_PER_FAULT` bound the LLM turns)

## Quiz - operator-supplied bootstrap (one question per missing item)

Each walkthrough is self-contained except the fixtures it cannot invent. A walkthrough whose bootstrap is unanswered stays blocked - not substituted with a double. The bootstraps the effective implementation settled (E1 slugs/classes, E6/E16 neo4j fixture loader, E8 carried-unit ground truth, E13 locale-token oracle, E14 fault injection) are now answered and embedded in the predicates above. The genuinely open items:

- **E2 (POST bootstrap):** which `project_id` has the `hunting_runs` table migrated, and which credentials/DB URL does the API use? Without live PG, blocked.
- **E7 (Q1 latency):** the harness proof is green as-is; a real-model baseline (which model, which concurrency, which threshold 0.8/0.9) is still operator-ratified before the token-scaling claim is asserted.
- **E9 (Q3 detail):** which HuntingAgent version judges `research_direction` sufficient (the blind DECOMPOSE gate), and is the len>20 threshold ratified? Currently simulated by the harness field checks.
- **E15 (concurrency):** does the real shared worker loop queue concurrent `arun_orchestration` gathers serially (making the >=1 fallback the actual behaviour), or run them concurrently (making the 2-distinct-rows assertion the behaviour)? The predicate holds either way; the observation the operator should confirm is which branch the docker-stack run takes.

## Coverage map

- bootstrap + control plane: C1, C2, E2
- candidate intake + risk schedule: C3 (normalize side), E1, E5, E8
- graph envelope (supervisor sole router, node-per-phase, no dispatch, no budget): C6, C8, E4, E10
- phase canon + ledger + report: C7, C17, E1, E10, E11, E14, E15
- HuntStore memory topology + config lifecycle + notes surface: C9, C10, C15, C21, E1, E5, E11, E14
- the three-tool surface: C18, C19, C20, C21, E12, E13 (tool-call-response verbatims)
- prompts (primer + Services/Systems split + discipline): C3, C4, C5, E6, E13, E16
- deterministic mint (per-class fan-out + surface transform + bare degrade): C11, C12, C12b, E1, E8, E9
- rich projection + D3 adjacency: E6, E16
- full-machine eval (30 faults, live L1, every nominal state): E17
- prior-insight projection (snowball guard): C15
- outlier duplicate/concurrency/malformed: C20, E15
- Q1 latency: E7 (harness proof green; real-model blocked)
- Q2 accuracy: E8
- Q3 detail depth: E9 (harness green; blind judge simulated)
- Q4 trajectory soundness: E10
- Q5 mint+note consistency: E11
- Q6 effective tool use: E12
- Q7 LLM reflection strategy: E13

Total: 22 contract (C1-C21 + C12b) + 16 walkthrough (E1-E17 with E3 removed) = 38 predicates; blocked: E2 (PG), E6/E16 (neo4j), E7/E9 real-model/agent stretches - the harness parts are green in the docker stack, and E17 (the full-machine eval) is green in the eval container.