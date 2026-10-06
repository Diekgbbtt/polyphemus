# ADR: a degraded KB result is unavailable evidence, never absence (#304)

*Status: RATIFIED pending verifier review (2026-10-06). Match check: `hunting-329-provider-failure-classification-adr.md` classifies a provider failure raised by an agent TURN; this record scopes the adjacent hole where the KB TOOL fails open instead of raising. Complements `domain-model.md` section 3.5 (absence is operational, not ontological) and supersedes nothing.*

## Context

The test-executor pod's triager holds an EXHAUSTION rule (`prompts/pod-triager.md`): when a knowledge-base query returns no precise new variant and reflection yields nothing new, terminate `{unsuccessful, space-exhausted, clean=true}`. The rule conflated two different events:

- the KB **answered** and held no new variant (a genuine knowledge-space exhaustion); and
- the KB query **degraded** - the tool fell back to its deterministic bundle (`lightrag/tool.py::LightragQueryTool.stream` catches every exception and returns `_deterministic_fallback`) or failed open (`pod/tools.py::KbQueryTool`).

The C1 cortex adversarial review (round 2) found the laundering live: pod-triager trace `11881bf037b69f5e340bdc56d5f4016f` reasoned "KB degraded again (tool_failed: RuntimeError, deterministic fallback, no validated model answer). So per the exhaustion rule ... Terminate with space-exhausted", output `verdict: unsuccessful, terminal_reason: space-exhausted, clean: true`. Quantified over the observation set: 33/72 mention a degraded domain, 36/72 mention `space-exhausted`, 42/72 mention both.

The binary pod outcome feeds the hunter's pure verdict derivation (`hunting_agent.derive_verdict`): `space-exhausted` always derives `unsuccessful`, regardless of `clean`. So a degraded KB became a clean false absence, corrupting the hypothesis verdict.

The failure was not a provider failure in the #329 sense: the observed cause was a `RuntimeError` with no provider status. #329's guard does not fire because nothing raises into the triager turn - the KB tool swallows and returns a bundle.

## Decision

### 1. The KB answer is machine-marked available or degraded

`lightrag/tool.py::LightRagQueryTool._run` sets `degraded = not accepted` on the answer it returns. An unaccepted answer is the deterministic fallback - an empty retrieval, a validation failure, or `tool_failed` - and carries no validated model answer. The flag is model-visible and machine-readable; the pod's own fail-open bundle also sets `degraded: true`.

`pod/types.py::KbObservation` gains `degraded: bool = False`; `pod/tools.py::KbQueryTool._record` stamps it from the answer (and treats an unparseable answer as degraded). The flag is EVIDENCE METADATA on the D6 trail, never a domain result.

### 2. A degraded KB observation can never license a clean absence

The graph's triager node (`pod/graph.py`) applies a deterministic guard (`_guard_degraded_kb`) after the triager decision and before it is recorded:

- `space-exhausted` is downgraded to `no-symptom-evidence` with `clean=false`. The ratified derivation (`derive_verdict`) then yields `insufficient-evidence`, never a false absence.
- any other absence claim (`no-symptom-evidence`, `budget-timeout`) has `clean` forced false.
- positive (`symptom-confirmed`) and structural (`technical-infeasibility`, `specific-defence-prevention`) terminals are untouched: they do not depend on KB coverage.

The guard is deterministic and log-aware, so it applies to the production triager and to any injected seam alike - prompt obedience is not load-bearing. The runner-exhausted path is covered too: `_clean_from_trail` returns false when the run's KB evidence was degraded, so `exhausted_terminal` lands `no-symptom-evidence` rather than `space-exhausted`.

### 3. Scope is the whole run, by design

`_degraded_kb_evidence` inspects every `KbObservation` in the run, not just the triager's last query. `space-exhausted` asserts the testing space was fully and cleanly exercised; a degraded KB read anywhere during the run means the knowledge-space exploration was impaired. The over-blocking direction is safe - it yields `insufficient-evidence`, never a false absence. Per-variant scoping was rejected: a variant is derived from its parent, so an earlier degraded read can hide a technique the later variant never recovered.

### 4. The prompt states the rule; the guard enforces it

`prompts/pod-triager.md` now states that a degraded/failed/unavailable KB result is NOT evidence of absence, that the EXHAUSTION rule applies only to a query that RETURNED an answer, and that `clean` is false when a KB query degraded. The prompt is the reasoning aid; the graph guard is the guarantee.

### 5. Provider classification is not forced at this seam

The KB tool deliberately fails open (the hunting author lane depends on it - `test_stream_fails_open_on_llm_error`, C2/C3), so a provider failure swallowed inside lightrag is not reliably classifiable at the pod seam. The honest handling is the degraded marker plus the guard; #329's propagation covers provider failures raised by an agent turn, and #331 owns pausing. Surfacing the swallowed cause from lightrag is deferred.

## Consequences

### The good

- A degraded knowledge domain is never recorded as an exhausted one. The hypothesis verdict is `insufficient-evidence` (unresolved), never a false absence.
- The distinction is machine-enforced, not prompt-dependent, and shared by the production and injected triagers.
- The six-value terminal vocabulary is unchanged; no infrastructure condition is encoded as a new domain value.

### Still open

1. **Per-variant precision.** A transient KB blip in an early variant downgrades a later genuine exhaustion. Accepted as the safe direction.
2. **KB provider-cause surfacing.** A provider failure inside the KB tool still degrades rather than pausing the run; revisit with the lightrag author-lane contract.
3. **Eval register.** EV-25 records this defect; the round-3 "not triager laundering" reading in `eval-bugs-map.md` section 3 was a different run and stands for that run.

## Impact map (as built)

- `lightrag/tool.py` - `_run` marks `degraded` from `accepted`.
- `src/polymerhus/attack/hunting/pod/types.py` - `KbObservation.degraded`.
- `src/polymerhus/attack/hunting/pod/tools.py` - `KbQueryTool._record` stamps `degraded`; the fail-open bundle sets it.
- `src/polymerhus/attack/hunting/pod/graph.py` - `_degraded_kb_evidence`, `_guard_degraded_kb`, `_clean_from_trail`.
- `src/polymerhus/attack/hunting/prompts/pod-triager.md` - the EXHAUSTION rule distinguishes unavailable from absent.
- Tests - `tests/attack/pod/test_kb_degradation_guard.py` (new), `tests/lightrag/test_tool.py`.
