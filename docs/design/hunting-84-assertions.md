# Assertions - hunting test-executor pod regrounding (#84)

**Source:** spec `docs/design/hunting-67-test-executor-pod-spec.md` section 6; ADR `docs/design/hunting-84-regrounding-decisions.md` (D84-1..D84-32); parent `docs/design/hunting-67-per-agent-specs-spec.md` section 6.
**Seams under assertion:** the `arun_pod` async entry (IA-3 in / IA-4 out, D84-15); the HIGH-LEVEL workflow map (INIT -> RUNNER STRETCH -> TRIAGER -> decide -> TERMINAL, D84-16/29); the six-way termination + `terminal_reason`/`clean`/`init_validation` vocabulary (D5, Q3-amended); the fixed caps (`HUNT_POD_MAX_TOOL_CALLS`=200, `HUNT_POD_MAX_ITERS`=8, `MAX_POD_ITERS`=3, `EXEC_TIMEOUT_S`=300); variants + experiment log (D67-08, D6); the per-project deterministic-key pod experiment-memory store + `note` tool (D84-33 through D84-38 - the store's public read/write contract, the notes `notes.yaml` keyed `<fault>_<strategy>:<order>:<note_name>`, the minted variants `variants/<ref>.yaml`, the experiment-log slice `<fault>_<strategy>/experiment-log/<order>.yaml` with the `experiment_summary` terminal record, the typed attribute filters order/kind/classification/symptom_status, no `_seq`/`_ref`, per-project scoping, idempotent overwrite); the pod's OWN terminal `PodExport` persistence (T7/#183, `<spec_id>/<run_id>.yaml`, GP1-GP5); the KB tool binding (D84-16/26); the production ReAct lane vs the injected contract lane (D84-22/29); the E1-E4 bulletproof chain walkthroughs (merged spec section 10).

**Coverage state (2026-08-22):** the catalogue is three-tier. The CONTRACT predicates C1-C15 are mechanised at the `arun_pod` seam in `tests/integration/test_test_executor_pod_contracts.py` (C1-C12 + C13-C15 via the injected-symbolic lane for the workflow temperature and the production fake-model lane for the T7 tool/KB/note surface). Walkthrough E1 is mechanised hermetically (`tests/e2e/test_test_executor_pod_walkthrough.py`). **Scope is the test-executor pod ONLY**: the full-pipeline chain walkthroughs (orchestrator -> hunter -> pod) and any other single-component testing are OUT OF SCOPE for this workstream; the E2-E4 chain predicates are REMOVED, never active coverage here. The holistic pod e2e (E5-E8, sibling-container in-network stack + the four juice-shop spec fixtures in `tests/e2e/fixtures/specs/`) is SCAFFOLDED in `tests/e2e/test_pod_e2e_holistic.py` + `tests/e2e/harness/` and skip-gated on the stack being up; the NFR scorer is implemented + unit-proven in `tests/e2e/test_pod_e2e_nfr.py`.

## Contract predicates (integration tier)

**C1 - INIT rejection.** seam: `arun_pod` IA-3. semantic: malformed.
input: a spec violating the typed base schema (`target_identity` empty, empty verification symptoms, empty payload vector).
observable: `{unsuccessful, technical-infeasibility}`, `init_validation` non-empty, ZERO tool calls executed.
yields: `test_init_rejects_invalid_spec`.

**C2 - Binary terminal invariant.** seam: `arun_pod` IA-4. semantic: ordering.
input: any spec and any tool behaviour (confirmed / absent / infeasible / invalid).
observable: every run terminates in exactly one of `{successful, unsuccessful}` with a `terminal_reason` in the six-value vocabulary.
yields: `test_binary_terminal_invariant`.

**C3 - Symptom confirmed.** seam: `arun_pod`. semantic: success.
input: a spec whose verification symptom a scripted 200 trailer satisfies (symbolic fast path).
observable: `{successful, symptom-confirmed}`, iterations >= 1, log holds variant spec + raw observation + interpretation.
yields: `test_symptom_confirmed_lands_successful`.

**C4 - Space exhausted.** seam: `arun_pod`. semantic: empty-valid.
input: a spec whose symptom never appears across the probe space (404 trailer, symbolic undecidable so the critic runs).
observable: `{unsuccessful, space-exhausted}`.
yields: `test_space_exhausted_lands_unsuccessful`.

**C5 - Infeasibility.** seam: `arun_pod`. semantic: degradation.
input: an unreachable target (exec returns code 7 / empty body).
observable: `{unsuccessful, technical-infeasibility}`, the infeasibility in the trail.
yields: `test_infeasibility_asserted_with_evidence`.

**C6 - Budget/timeout.** seam: `arun_pod`. semantic: degradation.
input: a critic that always mines variants, driven past `HUNT_POD_MAX_ITERS`.
observable: `{unsuccessful, budget-timeout}`, partial evidence, iterations == the cap.
yields: `test_budget_timeout_lands_unsuccessful`.

**C7 - Retry converges.** seam: `arun_pod` -> `run_with_retry`. semantic: degradation.
input: an exec failing non-zero `MAX_POD_ITERS - 1` times then succeeding.
observable: exactly `MAX_POD_ITERS = 3` exec attempts, run lands a binary end.
yields: `test_non_zero_exit_retries_to_converge`.

**C8 - Timeout enforcement.** seam: `arun_pod` -> `run_with_retry`. semantic: degradation.
input: an exec returning code 124 (timeout) with the timeout asserted passed through as `EXEC_TIMEOUT_S`.
observable: `MAX_POD_ITERS` attempts, run lands a binary end.
yields: `test_exec_timeout_enforced`.

**C9 - Variant provenance.** seam: `arun_pod` -> mint_variant -> D6. semantic: success.
input: a critic declining `payload_vector_space` into `/api`, then terminating.
observable: log holds the derived variant with `parent_ref="v0"` and `declined_attribute="payload_vector_space"`, plus raw observation + interpretation.
yields: `test_variant_derivation_with_provenance`.

**C10 - Duplicate probe dedup.** seam: `arun_pod` -> harness O7/C10. semantic: duplicate-idempotent.
input: the runner re-issues the identical probe command twice.
observable: exactly ONE exec execution and ONE recorded observation.
yields: `test_duplicate_probe_recorded_once`.

**C11 - Empty payload vector still probes.** seam: `arun_pod`. semantic: empty-valid.
input: a spec with `payload_vector_space: {}`.
observable: the default probe runs once (one exec), the log holds a raw observation (O12/C11).
yields: `test_empty_payload_vector_still_probes`.

**C12 - Langfuse failure is fail-open.** seam: `arun_pod` -> `trace_fn`. semantic: degradation.
input: a `trace_fn` that raises.
observable: the run completes unaffected (`{successful, symptom-confirmed}`).
yields: `test_langfuse_failure_is_fail_open`.

**C13 - KB tool bound on the Runner (T7-new; recording extended T3/#179).** seam: `arun_pod` production lane -> runner's `create_agent` tool list. semantic: tool-surface.
input: a production-lane run (fake model) whose ReAct script issues a `query_lightrag` call (the single config-gated KB tool, `KbQueryTool`; the former `kb_retrieve` seam is RETIRED).
observable: the binding is EXERCISED - EXACTLY ONE KB query happens and returns through the seam; the empty/degraded result fails-open and the runner degrades to the spec's own primitives (O13), landing a binary end; T3: the KB response is RECORDED - the persisted `experiment-log/<order>.yaml` slice carries one first-class `KbObservation` (the query's scenario/concern, the degraded bundle, `variant_ref == v0`) DISTINCT from the exec `RawObservation`s.
yields: `test_kb_query_tool_records_a_first_class_kb_observation` + the runner-binding tests (unit tier, `tests/attack/pod/test_tools.py`).

**C14 - Note written on P3, triager reads it (T7-new; re-scoped T2/#178).** seam: `arun_pod` production lane -> runner's `note` tool -> `PodMemoryStore` -> triager's note read. semantic: success.
input: a space-exhausted production run (fake model, 404 trailer) whose ReAct script writes the ONE consolidated `experiment_summary` as its final tool call.
observable: the summary is the TERMINAL RECORD of the variant's `experiment-log/<order>.yaml` slice (`experiment_summary` == the note body, `variant_ref == v0`, order 0 - the slice also holds the D6 observations/interpretations/executed); `notes.yaml` holds NO summary (`kb_insight`/`freeform` only); the triager's production turn terminates `{unsuccessful, space-exhausted}`.
yields: `test_note_written_on_p3_and_read_by_triager` (integration; production lane with fake model).

**C15 - Tool-contract validation (T7-new).** seam: `NoteToolSpec`/`ExecSpec`/`KbRetrieveSpec` `extra="forbid"` at a bound tool. semantic: degradation/malformed.
input: a tool call carrying a parameter outside the schema (e.g. `note` write with an unknown field, or `exec` with a foreign param).
observable: the call is REJECTED - a ToolMessage with the pydantic detail + the coded rejection (`NOTES_ARGS_REJECTED`/`NOTES_EMPTY_BODY`/`NOTES_BAD_KIND`/`NOTES_NO_STORE`), never executed, never harness-revalidated.
yields: `test_tool_contract_rejection_codes` (integration; direct bound-tool invocation + the create_agent-loop wrong-param path already in `tests/attack/pod/test_note_tool.py`).

**C16 - PodExport persistence (T7-new, #183).** seam: `arun_pod` -> the deterministic terminal node `_export` -> the pod memory store. semantic: success/idempotent/fail-open.
input: a completed run (production lane or injected-symbolic) with a bound store + `spec_id` + `run_id`.
observable: the pod OWNS its terminal result - the `PodExport` envelope persists to `<spec_id>/<run_id>.yaml`, the persisted record EQUALS the returned IA-4 envelope (GP3/GP4), a re-run with the same `run_id` OVERWRITES the same file (GP1, D84-37), and a WRITE FAILURE degrades fail-open to the in-memory envelope (the run still returns it, never raises - O3/IA-4); the `arun_pod` degrade path persists its real terminal result when a store is bound with a spec_id. The envelope body stays the D5/D6 fields unchanged (NO new correlation fields, GP2); the pure-log invariant holds (written by the deterministic node, never an LLM tool - GP5).
yields: `test_production_run_persists_its_pod_export` (integration; production lane) + the store-tier (`test_pod_export_*`) and graph-tier (`test_terminal_export_persists_to_spec_run_id`/`test_export_rerun_overwrites_the_same_file`/`test_export_write_failure_degrades_to_the_envelope`) in `tests/attack/pod/`.

## Walkthrough predicates (e2e tier)

**E1 - One trivial real run.** grounds merged spec 6.12 + H1 (spec 6.2 E1).
entry seam: IA-3 (a fixture `TestImplementationSpec`).
input: target identity `"service:web:soupmarket"`, verification symptom `"HTTP 200 with a non-empty body on GET /"`, testing pattern `"blind-boolean"`, assumptions `["network egress allowed"]`, payload vector space `{method: GET, path: "/"}`, rationale `"reachability probe from H1"`, interpretation guidance `"a 200 with a non-empty body confirms the symptom"`.
live edge: the eval target `soupmarket.shop` (Juice Shop on the operator's remote host, reached from kali via `192.33.91.87 soupmarket.shop` in `/etc/hosts`) - **HERMETICALLY MECHANISED** (D84-24/#158): the live LLM is a scripted `BaseChatModel` through `model_factory`, the terminal a fixed synthetic curl trailer (200), the KB fail-open (the config-gated `query_lightrag`/`KbQueryTool`, seam absent -> degraded bundle). **Live-edge readiness verified 2026-08-22**: `tests/e2e/fixtures/eval-targets.yaml` now exists in the tree (copied from `dev`); the kali container resolves `soupmarket.shop -> 192.33.91.87` (`docker-compose.yml` `extra_hosts`, confirmed live in `polymerhus-kali-1` `/etc/hosts`), and `curl -k https://soupmarket.shop/` returns `200` from inside kali. The pod's live LLM as the remaining un-wired piece (no model env / gateway in the in-network stack) - the sibling-container e2e harness is the scaffold that closes it.
path: INIT validates -> RUNNER STRETCH (production ReAct lane, `tool_exec` absent) -> the runner's first turn issues the default probe through `exec` (+ the config-gated KB tool) -> symbolic symptomatic classification -> TERMINAL.
terminal: exactly ONE verdict `{successful, symptom-confirmed, iterations >= 1}`, `clean is True`, experiment log holding the v0 variant spec, at least one raw observation with `status == 200` and a non-empty body, and an interpretation `classification == symptom-confirmed`; the KB binding ran at most once (the config-gated tool).
observed: the tool-call log (the curl command issued, status read back) and the result envelope.
yields: `test_trivial_real_run` (hermetic). A HOLISTIC sibling-container variant (real ReAct over the in-network stack, muse-spark models, mocked kb) is scaffolded for execution once the REST-exposure stream lands on dev.

**E1/H2 - Space-exhausted with the P3 note.** grounds spec 2 (H2/H6) + C14.
entry seam: IA-3. input: the same E1 spec; the terminal returns the 404 trailer.
live edge: as E1 (hermetic fake model; note store = temp-dir `PodMemoryStore`).
path: INIT -> RUNNER STRETCH (ReAct: `exec` 404 -> `note` FINAL tool call writing the consolidated `experiment_summary`; the config-gated KB tool is bound when enabled) -> TRIAGER production note-reading turn (`ToolStrategy(TriagerDecision)`) -> TERMINAL.
terminal: `{unsuccessful, space-exhausted}`, `clean True`, exactly 1 raw observation status 404; the summary is the TERMINAL RECORD of the variant's `experiment-log/0.yaml` slice (`experiment_summary` body mentions "404", `variant_ref == v0`), `notes.yaml` holds no summary; the triager's production interpretation note carries "third-party miner".
observed: the store read back (the variant log slice's terminal summary) + the interpretation.
yields: `test_space_exhausted_run_writes_the_p3_note`.

**E5-E8 - Holistic pod e2e over the in-network stack (SCAFFOLDED, executes after the REST-exposure stream lands).** grounds the NFR evaluation framework below (section 8). entry seam: `arun_pod` inside a sibling `polymerhus-agent` container mounting this worktree's `src/`, real session/checkpointer/compaction/memory-store stack, real kali exec, the config-gated `query_lightrag`/`KbQueryTool` (seam absent in a hermetic stack -> degraded bundle). input: the rich juice-shop fixture specs (section 9). live edge: `soupmarket.shop` live HTTP from kali. Each is a self-contained pass whose traces + experiment log + memory-store notes feed the scoring rubric.

## 8. Non-functional evaluation framework (pod e2e)

The qualitative gate for the holistic e2e. Every run is scored 0-3 (0 = absent/broken, 1 = present but shallow, 2 = correct, 3 = exemplary) on each criterion, with the evidence source named. The coordinator inspects per run: the Langfuse trace (model steps + tool calls + reasoning spans), the pod's experiment log (D6), the pod memory-store notes, and the returned envelope.

| # | Criterion | What is evaluated | Scoring anchors (4pt) | Evidence |
|---|---|---|---|---|
| N1 | Prompt materialization | The runner's system prompt carries every spec attribute: target identity, verification symptom(s), testing pattern, assumptions, payload vector space, rationale, interpretation guidance + the P0-P3 plan + the control-then-intervene paradigm + the KB/note tool contract | 3 = all spec attributes verbatim + plan phases clearly present; 2 = all attributes, plan implicit; 1 = partial; 0 = garbled/missing | Langfuse trace (system prompt) |
| N2 | Runner ReAct trajectory | Did the loop traverse P0-P3 (feasibility -> concretize -> execute -> confirm exhaustion)? Were tools called correctly (`exec` for probes, the config-gated `query_lightrag` for grounding, `note` for the P3 summary), in the right sequence, each succeeding? | 3 = full P0-P3 arc, tools correct + sequenced + recovered from a rejection; 2 = arc complete, minor tool misuse; 1 = partial arc / skipped phases; 0 = degenerate | Langfuse trace (model + tool steps) |
| N3 | Note detail level | The P3 `experiment_summary` note (and any `kb_insight`/`freeform`): does it carry a dense, specific account - what was probed, the payloads, the observations, the exhaustion evidence - not boilerplate? | 3 = dense, specific, references actual probes + observations; 2 = specific but thin; 1 = boilerplate; 0 = absent | memory-store note bodies |
| N4 | INIT validation criticality | Did the pod validate the spec against the typed base + environment contract before executing? Was a malformed/infeasible spec REJECTED with evidence, not silent-run? | 3 = strict rejection with init_validation evidence, zero tool calls; 2 = rejected, thin evidence; 1 = lenient/warnings-only; 0 = no validation | envelope `init_validation` + trace first step |
| N5 | Space exploration | Across the laps, did the triager mine VARIANTS that elicited different payloads/vectors/schemes, new symptoms, new techniques? How exhausted was the probe space really (raw observations count, distinct probes vs the cap)? | 3 = 2+ variant mints changing payload/scheme/technique + a genuinely exhausted space (many distinct probes); 2 = variants but narrow edits; 1 = re-executes same probes / single variant; 0 = no variation | experiment log variant_specs + raw_observations |
| N6 | Termination + persistence | Did the run terminate through the SIX-way vocabulary with the right `terminal_reason`/`clean`? Is the experiment log persisted (variant specs, raw observations, interpretations) and readable? | 3 = correct terminal + full D6 persisted; 2 = correct terminal, log thin; 1 = terminal wrong / log partial; 0 = no persistence | envelope + D6 export + hunt-store stub |
| N7 | Triager reflection | Prompt materialization for the triager; was the critic's reflection truly critical? Did it mint a NEW variant that SHARPLY changed the testing procedure paradigm (e.g. new technique, new vector family), not a cosmetic tweak? | 3 = critical reflection + paradigm-sharp new variant; 2 = reflective but incremental variant; 1 = rubber-stamp terminate; 0 = degenerate | Langfuse trace (triager turn) + variant_specs |
| N8 | Seamless spec-conformant loop | Overall: did the pod cycle INIT -> RUNNER STRETCH -> TRIAGER -> decide -> TERMINAL exactly as the spec's high-level map, with no hangs, no raise, fail-open degradation handled, within the fixed caps? | 3 = flawless arc in cap; 2 = one hiccup, recovered; 1 = several errors, still terminated; 0 = crashed/hung | full trace + envelope + logs |

Scoring: a run is GREEN for a criterion at >= 2; an e2e PASS requires N1-N4 each >= 2 AND N5-N8 each >= 1 (terminality is the floor). Each run's scorecard is appended to the run's entry in this document.

## Verification commands

The catalogue is the gate, not the loop: these run in the integration + e2e tiers only, under the verification gate, never in the red/green unit loop.

```
.venv/bin/python -m pytest tests/integration/test_test_executor_pod_contracts.py -q
.venv/bin/python -m pytest tests/e2e/test_test_executor_pod_walkthrough.py -q
.venv/bin/python -m pytest tests/attack/pod/test_pod_memory.py tests/attack/pod/test_note_tool.py tests/attack/pod/test_tools.py tests/attack/pod/test_react_seams.py -q
```

Do NOT run `tests/test_stack_smoke.py` / `tests/test_neo4j_schema.py` (live-tier docker), `tests/test_gateway_reasoning_passthrough.py` (fails to collect), `tests/test_agent_health.py` (hangs).