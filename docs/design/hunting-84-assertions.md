# Assertions - hunting test-executor pod regrounding (#84)

**Source:** spec `docs/design/hunting-67-test-executor-pod-spec.md` section 6; ADR `docs/design/hunting-84-regrounding-decisions.md` (D84-1..D84-32); parent `docs/design/hunting-67-per-agent-specs-spec.md` section 6.
**Seams under assertion:** the `arun_pod` async entry (IA-3 in / IA-4 out, D84-15); the HIGH-LEVEL workflow map (INIT -> RUNNER STRETCH -> TRIAGER -> decide -> TERMINAL, D84-16/29); the six-way termination + `terminal_reason`/`clean`/`init_validation` vocabulary (D5, Q3-amended); the fixed caps (`HUNT_POD_MAX_TOOL_CALLS`=200, `HUNT_POD_MAX_ITERS`=8, `MAX_POD_ITERS`=3, `EXEC_TIMEOUT_S`=300); variants + experiment log (D67-08, D6); the pod experiment-memory store + `note` tool (D84-20/27/32); the KB tool binding (D84-16/26); the production ReAct lane vs the injected contract lane (D84-22/29); the E1-E4 bulletproof chain walkthroughs (merged spec section 10).

**Coverage state (2026-08-22):** the catalogue is three-tier. The CONTRACT predicates C1-C12 are mechanised at the `arun_pod` seam in `tests/integration/test_test_executor_pod_contracts.py` (the injected-symbolic lane). C13-C15 became `arun_pod`-mechanisable with T7 but currently stand only in the UNIT tier (tool/note-tool tests) and the e2e walkthrough - they are the focus of this pass. Walkthroughs E1 is mechanised hermetically; E2-E4 are carried skeletons blocked on the #83 chain.

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

**C13 - KB tool bound on the Runner (T7-new).** seam: `arun_pod` production lane -> runner's `create_agent` tool list. semantic: tool-surface.
input: a production-lane run (fake model) whose ReAct script issues a `kb_retrieve` call.
observable: the binding is EXERCISED - EXACTLY ONE `kb_retrieve` happens and returns through the typed seam; the KB empty result fails-open and the runner degrades to the spec's own primitives (O13), landing a binary end.
yields: `test_kb_retrieve_bound_and_fails_open` (integration; production lane with fake model).

**C14 - Note written on P3, triager reads it (T7-new).** seam: `arun_pod` production lane -> runner's `note` tool -> `PodMemoryStore` -> triager's note read. semantic: success.
input: a space-exhausted production run (fake model, 404 trailer) whose ReAct script writes the ONE consolidated `experiment_summary` note as its final tool call.
observable: the store holds exactly ONE note keyed by the spec id + variant `v0`, `kind == experiment_summary`, body mentions the 404; the triager's production turn terminates `{unsuccessful, space-exhausted}`.
yields: `test_note_written_on_p3_and_read_by_triager` (integration; production lane with fake model).

**C15 - Tool-contract validation (T7-new).** seam: `NoteToolSpec`/`ExecSpec`/`KbRetrieveSpec` `extra="forbid"` at a bound tool. semantic: degradation/malformed.
input: a tool call carrying a parameter outside the schema (e.g. `note` write with an unknown field, or `exec` with a foreign param).
observable: the call is REJECTED - a ToolMessage with the pydantic detail + the coded rejection (`NOTES_ARGS_REJECTED`/`NOTES_EMPTY_BODY`/`NOTES_BAD_KIND`/`NOTES_NO_STORE`), never executed, never harness-revalidated.
yields: `test_tool_contract_rejection_codes` (integration; direct bound-tool invocation + the create_agent-loop wrong-param path already in `tests/attack/pod/test_note_tool.py`).

## Walkthrough predicates (e2e tier)

**E1 - One trivial real run.** grounds merged spec 6.12 + H1 (spec 6.2 E1).
entry seam: IA-3 (a fixture `TestImplementationSpec`).
input: target identity `"service:web:soupmarket"`, verification symptom `"HTTP 200 with a non-empty body on GET /"`, testing pattern `"blind-boolean"`, assumptions `["network egress allowed"]`, payload vector space `{method: GET, path: "/"}`, rationale `"reachability probe from H1"`, interpretation guidance `"a 200 with a non-empty body confirms the symptom"`.
live edge: the eval target `soupmarket.shop` (live HTTP mode) - **HERMETICALLY MECHANISED** (D84-24/#158): the live LLM is a scripted `BaseChatModel` through `model_factory`, the terminal a fixed synthetic curl trailer (200), the KB a fail-open empty `kb_fn`. **Live-edge readiness verified 2026-08-22**: `tests/e2e/fixtures/eval-targets.yaml` now exists in the tree (copied from `dev`); the kali container resolves `soupmarket.shop -> 192.33.91.87` (`docker-compose.yml` `extra_hosts`, confirmed live in `polymerhus-kali-1` `/etc/hosts`), and `curl -k https://soupmarket.shop/` returns `200` from inside kali. The pod's live LLM as the remaining un-wired piece (no model env / gateway in the in-network stack) - a real live-target E1 can layer on when the pod LLM is wired.
path: INIT validates -> RUNNER STRETCH (production ReAct lane, `tool_exec` absent) -> the runner's first turn issues the default probe through `kb_retrieve` + `exec` -> symbolic symptomatic classification -> TERMINAL.
terminal: exactly ONE verdict `{successful, symptom-confirmed, iterations >= 1}`, `clean is True`, experiment log holding the v0 variant spec, at least one raw observation with `status == 200` and a non-empty body, and an interpretation `classification == symptom-confirmed`; the KB binding ran once (1 `kb_retrieve` call).
observed: the tool-call log (the curl command issued, status read back) and the result envelope.
yields: `test_trivial_real_run`.

**E1/H2 - Space-exhausted with the P3 note.** grounds spec 2 (H2/H6) + C14.
entry seam: IA-3. input: the same E1 spec; the terminal returns the 404 trailer.
live edge: as E1 (hermetic fake model; note store = temp-dir `PodMemoryStore`).
path: INIT -> RUNNER STRETCH (ReAct: `kb_retrieve` -> `exec` 404 -> `note` FINAL tool call writing the consolidated `experiment_summary`) -> TRIAGER production note-reading turn (`ToolStrategy(TriagerDecision)`) -> TERMINAL.
terminal: `{unsuccessful, space-exhausted}`, `clean True`, exactly 1 raw observation status 404; the store holds exactly ONE note (`kind experiment_summary`, `variant_ref v0`, key prefixed by the canonical spec id, body mentions "404"); the triager's production interpretation note carries "third-party miner".
observed: the store read back (one note) + the interpretation.
yields: `test_space_exhausted_run_writes_the_p3_note`.

**E2 - Full chain, two candidates.** grounds merged spec 10.1-10.8 + orchestrator E1.
entry seam: candidate-set delivery at IA-1. live edge: `soupmarket.shop` live HTTP.
path: FaultSource fixture -> gate -> ranker -> two `HuntConfig`s -> two hunting agents -> two pod runs -> two verdicts -> S7.
terminal: exactly two hunt records with spec/result refs and hypothesis verdicts.
yields: `test_full_chain_two_candidates` - **carried, blocked on the #83 dispatch wiring** (skipped; do not chase the parent chain).

**E3 - Yellow park/resume.** grounds merged spec 10.4/10.7 + orchestrator E2.
entry seam: IA-1. input: `{(service applies), (system yellow)}`.
path: dispatch for the service; park for the system; recon lands; re-match applies; second dispatch.
terminal: two hunt records, one back-edge record.
yields: `test_yellow_park_resume` - **carried, blocked on the #83 chain**.

**E4 - Zero-candidate run.** grounds merged spec 10.1 + orchestrator E1-empty.
entry seam: IA-1. input: the empty candidate set.
path: gate on nothing -> no dispatch -> S7.
terminal: zero hunt records, run complete.
yields: `test_zero_candidate_run` - **carried, blocked on the #83 chain**.

## Verification commands

The catalogue is the gate, not the loop: these run in the integration + e2e tiers only, under the verification gate, never in the red/green unit loop.

```
.venv/bin/python -m pytest tests/integration/test_test_executor_pod_contracts.py -q
.venv/bin/python -m pytest tests/e2e/test_test_executor_pod_walkthrough.py -q
.venv/bin/python -m pytest tests/attack/pod/test_pod_memory.py tests/attack/pod/test_note_tool.py tests/attack/pod/test_tools.py tests/attack/pod/test_react_seams.py -q
```

Do NOT run `tests/test_stack_smoke.py` / `tests/test_neo4j_schema.py` (live-tier docker), `tests/test_gateway_reasoning_passthrough.py` (fails to collect), `tests/test_agent_health.py` (hangs).