# Assertions - work-item "hunt-orchestrator LLM-local artifacts" (#135)

**Source:** github.com/Diekgbbtt/polyphemus/issues/135; spec
`docs/design/hunting-orchestrator-llm-artifacts-spec.md` (extends
`hunting-67-orchestrator-spec.md`; graph engine from #110).

**Seams under assertion:** the four LLM-local artifact surfaces the spec owns -
(1) the per-pair symbolic render inside the reason stretch
(`arun_orchestration._reason_node` assembling `GateInput` from
`unit_projection.build_projection` / `fault_kb.load_materialisation` /
`fault_kb.load_fold_families`, rendered by `llm._compose_gate_prompt`), (2) the
tool surface bound onto the orchestrator's session agent (`HuntOrchestratorActor`
-> `session._build_agent`'s `create_agent(tools=...)`), (3) the skill mounts
(`llm._gate_skill` / `_rematch_skill` -> `recon/domain/skills.skill_for`), (4)
the observability (`attack/hunting/orchestrator_tracing.py` mirroring
`hunting_tracing.py`), (5) the ORDER/topology invariants (no new graph nodes, no
schema change) the delivery-semantics section pins.

Numbering continues the existing orchestrator catalogue (C1-C12 in
`tests/integration/test_hunt_orchestrator_contracts.py`, E1-E2 in
`tests/e2e/test_hunt_orchestrator_walkthrough.py`), so ids are continuous across
the shared integration/e2e seam files. The new contract predicates live in a NEW
integration file `tests/integration/test_orchestrator_llm_artifacts.py`; the new
walkthroughs extend the existing walkthrough file.

## Contract predicates (integration tier)

### C13 - the gate skill mount resolves (success)
| | |
|---|---|
| **seam** | `llm._gate_skill()` vs the mounted `skills/hunting/hunt-orchestrator/SKILL.md` (via `skill_for`). |
| **delivery semantic** | success - mount present. |
| **input** | none (mount is a repo file). |
| **observable** | `_gate_skill()` returns the mount's body (frontmatter stripped), strictly longer than `_GATE_SKILL_FALLBACK`, and containing the cognitive-architecture markers of spec 3.2 (backward-from-end, four consecutive sub-problems, hypothesise-and-verify, prune-only-on-positive, emit contract). |
| **yields** | `test_gate_skill_mount_serves_the_cognitive_architecture` in `tests/integration/test_orchestrator_llm_artifacts.py`. |

### C14 - the rematch skill mount resolves (success)
| | |
|---|---|
| **seam** | `llm._rematch_skill()` vs the mounted `skills/hunting/hunt-orchestrator-rematch/SKILL.md`. |
| **delivery semantic** | success - mount present. |
| **input** | none. |
| **observable** | `_rematch_skill()` returns the rematch body (frontmatter stripped), distinct from the gate body, pinning the D2 three-valued verdict + depth-1 cap; the gate and rematch prompts served to the actor are `[SystemMessage(skill), HumanMessage(prompt)]` (the composed-turn pattern, spec 5). |
| **yields** | `test_rematch_skill_mount_serves_the_d2_discipline`; `test_actor_composes_system_message_plus_turn`. |

### C15 - the per-pair render carries the projection + materialisation + fold family (success)
| | |
|---|---|
| **seam** | reason stretch (`arun_orchestration._reason_node` -> `GateInput`) -> `_compose_gate_prompt`. |
| **delivery semantic** | success - all three symbolic reads resolve. |
| **input** | one accepted candidate `(Service:slug:a, fault-x, applies)`; projection for `Service:slug:a` returns a typed `UnitProjection` (kind=Service, spine non-empty, one Service->System edge); `load_materialisation()` returns fault-x's NL content; `load_fold_families()` returns `("fault-x1", "fault-x2")` under fault-x. |
| **observable** | the `GateInput` the reason stretch hands the gate carries exactly ONE candidate, plus a `projection` slot, a `materialisation` slot for fault-x, a `fold_family` tuple `("fault-x1", "fault-x2")`; `_compose_gate_prompt` renders all three deterministically (sorted fold ids, deterministic projection render). |
| **yields** | `test_reason_stretch_render_carries_projection_materialisation_fold_family`; `test_fold_family_renders_sorted`. |

### C16 - absent / raising symbolic reads degrade per-slot, never abort (degradation)
| | |
|---|---|
| **seam** | the same render, with a read failure per slot. |
| **delivery semantic** | degradation - projection returns None or raises; materialisation map lacks the fault; fold-family map lacks the fault. |
| **input** | three runs: (a) projection read_fn raises, (b) materialisation absent, (c) fold family absent. |
| **observable** | each degraded slot renders as UNKNOWN (never FALSE, never prunes); the turn still assembles the `GateInput` with the surviving slots; the run completes (report produced, no raise), the carried direction is minted/dispatched as if grounded on the reduced evidence. |
| **yields** | `test_absent_projection_degrades_to_unknown`, `test_materialisation_failure_degrades_to_unknown`, `test_fold_family_failure_degrades_to_unknown`; a combined `test_all_slots_degraded_still_runs`. |

### C17 - exactly three tools are bound onto the actor turn; no HuntConfig writer (success / constraint)
| | |
|---|---|
| **seam** | `HuntOrchestratorActor._ensure_started` -> `session._build_agent` -> `create_agent(tools=...)`. |
| **delivery semantic** | success (surface shape). |
| **input** | an actor constructed with the three real `OrchestratorTools` bodies. |
| **observable** | the agent the actor builds binds EXACTLY the three tool names `back_edge`, `graph_view`, `store_reads` (`TOOL_SURFACE`), and NO fourth tool that writes/fabricates a `HuntConfig`; the bound tools are real callables (fail-open when a seam is absent, spec 4). |
| **yields** | `test_actor_binds_exactly_the_three_tools` (spy `_build_agent` recording the `tools=` list); `test_no_hunt_config_writing_tool_on_the_surface`. |

### C18 - a missing seam body leaves the tool absent or fail-open-stubbed, never raising into the turn (degradation)
| | |
|---|---|
| **seam** | the same binding, with one seam body per tool unavailable. |
| **delivery semantic** | degradation. |
| **input** | `OrchestratorTools(back_edge=None)`, `graph_view=None`, `store_reads=None` in turn. |
| **observable** | the build still succeeds; a tool whose seam is absent is either not bound (surface shrinks) or bound to a stub returning a denoted error (never raises into the turn); the turn's structured reply still yields a `GateDecision` path (the actor's fail-open canon from #110 is untouched). |
| **yields** | `test_absent_back_edge_degrades_the_surface`, `test_absent_graph_view_degrades_the_surface`, `test_absent_store_reads_degrades_the_surface`. |

### C19 - the read-only graph view still rejects writes through the bound tool (ordering / write rejection)
| | |
|---|---|
| **seam** | the `graph_view` tool body -> `ReadOnlyGraphView.read`. |
| **delivery semantic** | malformed / write rejection. |
| **input** | a write-shaped cypher string (`MERGE ...`) passed to the `graph_view` tool body. |
| **observable** | the body surfaces `ReadOnlyGraphViewError` (the underlying view's guard), never executes the write; `merge()` still raises. |
| **yields** | `test_graph_view_tool_rejects_write_shaped_requests` (extends existing C5). |

### C20 - the render is pure symbolic mapping: no LLM call precedes it (ordering / concurrency)
| | |
|---|---|
| **seam** | reason stretch render. |
| **delivery semantic** | ordering - the render happens BEFORE the gate turn. |
| **input** | one candidate; a spy `reason_fn`. |
| **observable** | the fully rendered `GateInput` (projection/materialisation/fold-family populated) is passed to `reason_fn` BEFORE any model side-effect; on its own the render never invokes `reason_fn` (a degenerate pass that assembles the render but never reasons does not fire the gate). D67-11 illustrated: `kb_degraded` still rides the state and the render still marks it, the gate still reasons. |
| **yields** | `test_render_precedes_the_gate_turn`, `test_degenerate_pass_renders_without_firing_the_gate`. |

### C21 - one span per gate turn, session=run_id, fail-open when Langfuse absent (success + degradation)
| | |
|---|---|
| **seam** | `orchestrator_tracing.orchestrator_gate_span(run_id)` + `trace_gate_step` + `flush_orchestrator_traces()` (mirroring `hunting_tracing`). |
| **delivery semantic** | success + degradation. |
| **input** | a fake `langfuse` module (the `test_analyser_tracing.py` recipe). |
| **observable** | `orchestrator_gate_span` opens ONE agent span named `orchestrator-<run>`, `propagate_attributes(session_id=run_id, tags=["attack","hunting","orchestrator-gate"])`, and the symbolic-render step nests under it via `trace_gate_step` (pair identity + degraded slots); with Langfuse raising, every helper degrades to a no-op (the pass traces nothing but completes). |
| **yields** | `test_orchestrator_gate_span_correlates_to_the_run`, `test_gate_step_records_pair_and_degraded_slots`, `test_orchestrator_tracing_fails_open_when_langfuse_absent`. |

### C22 - no new graph nodes, no schema change (topology / contract freeze)
| | |
|---|---|
| **seam** | `build_hunting_graph` node set; `GateDecision`/`EnvisionedDirection`/`MatchVerdict` schemas. |
| **delivery semantic** | ordering (invariant preservation). |
| **input** | build the graph with injected nodes. |
| **observable** | the node set stays exactly `{supervisor, reason, budget, dispatch}` (no new nodes for the prompt/tools/observability - the render lives INSIDE the reason stretch); the structural-output schemas `GateDecision`/`EnvisionedDirection`/`MatchVerdict` and the report/trail/store-record shapes compile unchanged and the tool surface is the same `TOOL_SURFACE` frozenset. |
| **yields** | `test_no_new_graph_nodes`, `test_structured_schemas_and_surface_unchanged` (the existing 110-vs-135 regression guard). |

## Walkthrough predicates (end-to-end tee tier)

All four walkthroughs' live edge is a REAL hunting-orchestrator LLM role (the gate turn) + a real or proxy `reason_fn`. The skill-loading lane (C13/C14) and the tracing lane (C21) are contract-covered without a live model; these walkthroughs prove the composed prompt + tool surface actually round-trip the model in a real turn.

### E3 - a real gate turn reasons over the rich render and emits a carried direction (grounds stories 1-5)
| | |
|---|---|
| **grounds** | spec 3.1/3.2/3.3 (render + cognitive architecture), 4 (tools bound), 5 (mounted skill). |
| **entry seam** | `arun_orchestration` per-pair gate turn on `HuntOrchestratorActor`. |
| **input** | one candidate `(Service:slug:a, fault-x, applies)`; a live L1 project carrying the typed `Service:slug:a` with outgoing edges, a real fault-KB catalogue; `reason_fn` = the production build (skill mount + `_compose_gate_prompt`), a real graph view over the live project, a real hunt store. |
| **live edge** | real hunting-orchestrator LLM role (the gate turn); real Neo4j L1 graph; real skills mount; repeated twice for determinism confidence. |
| **path** | intake -> reason stretch renders projection/materialisation/fold-family -> mounted system prompt + per-pair user prompt on the actor thread -> GateDecision (structured) -> mint for the carried direction -> dispatch -> store records. |
| **terminal** | exactly one carried, non-pruned direction; one config record with the four seed fields non-empty; one hunt record; `gate_pruned == ()`; the deterministic-report/trail shared shapes intact. |
| **observed** | the actor's composed `[SystemMessage(skill), HumanMessage(prompt)]`, the `GateDecision` object, store config/hunt records read back by run id. |
| **yields** | `test_live_gate_turn_reasons_over_the_rich_render` in `tests/e2e/test_hunt_orchestrator_walkthrough.py` (skip-gated on a live hunting LLM role + Neo4j, matching E1/E2's fixture gates). |

### E4 - the gate prunes ONLY on positive grounds across real degraded slots (grounds stories 2/4, prune-only rule)
| | |
|---|---|
| **grounds** | spec 3.2.5 (prune only on positive grounds), 3.1 (UNKNOWN, never FALSE). |
| **entry seam** | the same gate turn. |
| **input** | one candidate `(Service:slug:a, fault-x, applies)` against a project where the projection read returns the FULL typed unit but the materialisation and fold-family reads hit a degraded catalogue (both UNKNOWN). |
| **live edge** | real LLM role; real stochastic model behaviour accepted - the assertion is on the RENDER (UNKNOWN markers present, no FALSE) plus the model's recorded rationale, NOT on which direction. |
| **path** | intake -> render marks materialisation/fold UNKNOWN -> mounted gate skill + degraded-marked prompt -> GateDecision. |
| **terminal** | the render text visibly carries UNKNOWN slots for the degraded facets and NEVER a FALSE/prune signal during the turn; the model's carried direction is recorded with its rationale; the run's trail/report still record the decision regardless of carried or pruned. |
| **observed** | the composed prompt text (degradation markers), the structured `GateDecision`, the report's gate-prune/trail entries. |
| **yields** | `test_gate_renders_unknown_never_false_on_degraded_slots_live` (skip-gated as E3). |

### E5 - a real back-edge tool call flows origin="hunting" and lands in the store (grounds stories 5/7, tool surface live)
| | |
|---|---|
| **grounds** | spec 4.1 (back_edge tool), IA-6, `hunt_store` back_edge records. |
| **entry seam** | the gate turn's `back_edge` tool on the real agent. |
| **input** | a candidate where the model (or a deterministic fixture `reason_fn`) invokes `back_edge` with a targeted `AnalyserReconRequest(origin="hunting", scope.unit_id="Service:slug:a")`; the recon seam returns a `TargetedReconResult`. |
| **live edge** | real LLM role (or a scripted reason_fn for deterministic replay); the `request_targeted_recon` seam real or a recorded stub. |
| **path** | turn binds `back_edge` -> target-recon request with `origin="hunting"` -> `TargetedReconResult` -> the orchard store `back_edge` record + `fault-evidence` entry. C17's 3-tool constraint observable live. |
| **terminal** | `order.applies`: the store carries exactly one `back_edge` record whose `correlation_id`/`origin` (and the `fault-evidence` memory entry) round-trip; the run completes with the carried/refuted outcome recorded. |
| **observed** | store records by run id; the `TargetedReconResult`. |
| **yields** | `test_live_back_edge_tool_round_trips_hunting_origin` (skip-gated as E3). |

### E6 - the full pass keeps the 110 canon intact with the new artifacts (grounds stories 6/7/8, no-regression)
| | |
|---|---|
| **grounds** | spec 7 (delivery semantics unchanged), the C1-C12 canon. |
| **entry seam** | a full `arun_orchestration` pass with the production seam set (rich render + mounted skills + three tools + tracing) over two candidates (one applies, one yellow insufficient-evidence). |
| **input** | the two-candidate fixture from E1, live L1 graph defaults, real store. |
| **live edge** | real LLM role + real Neo4j. |
| **path** | full reason/dispatch walkthrough with park/resume for the yellow. |
| **terminal** | the O1-O10 report shape, `hunts_dispatched`, `gate_pruned`, `unresolved`, `budget_cut`, and trail/store-record shapes identical to the #110 canon exercised WITHOUT the new artifacts (the same fixture drives both a with-artifacts and a without-artifacts pass). |
| **observed** | both reports and both store listings compared field-by-field. |
| **yields** | `test_full_pass_canon_unchanged_with_new_artifacts` (skip-gated as E3). |

## Bootstrap dependencies (operator-supplied; validate at setup, fail loudly)

1. A live hunting-orchestrator LLM role (`hunting_orchestrator` + `hunting_hunter`, the #68/#71 baseline) for E3-E6.
2. A live L1 Neo4j project with the fixture units `Service:slug:a` (+ edges) for the projection path and the graph view.
3. Optionally wapped Langfuse for C21's live branch (fail-open without).
4. The repo fault-KB catalogue (present already) - root cause of the materialisation / fold-family slots.