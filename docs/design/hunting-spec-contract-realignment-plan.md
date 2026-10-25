# Hunting spec contract realignment - working plan

*Status: PROPOSED, awaiting operator decisions.
Branch: `fix/hunt-spec-contract-realign`.
Base: `hunt-enhancement-trunk` at `28c6a878`.*

## Objective

Realign the typed `TestImplementationSpec` with the hunter's actual reasoning.
The hunter must slice the failure-mode space and name each slot by the discrimination variables it used.
The spec must stop carrying retired ontology fields and copied skill excerpts.
The pod must load the abstract procedure from the skill itself.
The lifecycle must stop a degraded or malformed item from wedging the queue.

The work also mines the 2026-10-24 white-jotter run for the feedback items the operator raised.

## Invariants

- The model, compaction thresholds, token caps, USD guards, and trial protocol do not change.
- The status vocabulary stays `{hypothesised, ratified, dropped}`.
- The spec set is still one spec per write, then `finalize`.
- The bound hunt key and the derived spec identity stay symbolic.
- The pod stays the only source of experimental evidence.
- Every change lands test-first.

## Workstream A - context and contract audit

**A1. Render every verbatim that enters the model context.**
The renderer is the prompt loader plus the bound tool descriptions.
The audit covers:
- `prompts/hunting-agent.md` and `prompts/examples.md`;
- `render_spec_contract()`;
- every hunter, pod, modeller, and analysis tool description;
- the phase hints in `hunter_state.py`;
- the loop payload projection in `hunting_agent.py`;
- the pod context renderers.

**A2. Stale-field matrix.**
Search for `payload_vector_space`, `interpretation_guidance`, `testing_pattern`, `fault_class`, `fault_keyword`, `strategy_keyword`, `skill_procedure`, `hypothesis`, `mechanism`, `supports`, `conflicts`, `rank`.
Classify each hit as:
- injected into the model context;
- persisted but not injected;
- code comment or doc only;
- test fixture only;
- legitimate live use.

Deliverable: `docs/experiments/white-jotter-batched-2026-10-24/CONTEXT-INJECTION-AUDIT.md`.

**A3. Spurious verbatim fixes.**
Remove every context-injected stale field.
Add a regression test that renders the full hunter and pod prompt and asserts the retired names are absent.

## Workstream B - spec identity and discrimination

### B1. Problem with the current identity

`<fault_keyword>_<strategy_keyword>` has five defects.

1. The two words have no defined semantics against the SLICE and DISCRIMINATE reasoning.
2. `_` is both the separator and a legal character in a keyword, so two different tuples can collide.
3. The identity duplicates data that already has a home: the class is in provenance, the unit and loop are bound, the strategy is the rationale.
4. A fixed two-slot tuple cannot express separation on `actor`, `state`, or `chaining`.
5. `fault_keyword` carries the retired `fault_class` vocabulary into the hunter's context.

### B2. Proposed identity

The identity is the ordered tuple of instance values over the discrimination variables.

```
<vuln-class>__<axis>=<value>__<axis>=<value>[__...]
```

Example:

```
idor__object-id=report__delivery-route=signed-url
```

Rules:

- The class segment is `provenance.web_vulnerability_class`, falling back to `canonical_class`, then `spec`.
- The hunter authors `discriminators`: two to four ordered `{axis, value}` entries.
- The order is the DISCRIMINATE order, most discriminating first.
- `axis` is a lowercase token (`^[a-z][a-z0-9-]{1,40}$`).
- `value` is a lowercase token (`^[a-z0-9][a-z0-9._-]{0,59}$`).
- Axes are unique inside one spec.
- `=` separates axis and value; `__` separates dimensions.
- Both separators are outside the value alphabet, so the join is unambiguous.
- The derived id is capped at 120 characters.
- A fifth axis is rejected: it means the slot is a slice, not a spec.

The prompt supplies a recommended axis vocabulary.
The vocabulary maps to the COLLECT families and the SLICE boundary variables:

- `technique` - advanced technique or bypass technique;
- `chaining` - preliminary vulnerability;
- `technology` - technology-specific failure mode;
- `payload-vector` - effective request item, protocol, or delivery behaviour;
- `actor` - role or authority;
- `state` - object or lifecycle state;
- `surface` - route or endpoint family;
- `data-flow` - source-to-sink path.

The list is a recommendation, not a closed enum.
The hunter must reuse the exact axis names it wrote in `phase:discriminate`.

### B3. Why not the proposed `<vuln-class>-<technique>`

The two-slot form is better than fault plus strategy, but it keeps three defects.

1. It forces every separation into a "technique" slot.
   Separation on state or actor gets a compound or invented value.
2. `-` is both the separator and a legal value character.
3. It does not record the number of dimensions.
   Two slots separated by different axes can collide.

The axis-value form removes all three.
It also makes the prompt and the spec use one vocabulary: the variables named in DISCRIMINATE.

### B4. Merge and status-write stability

- A terminal status write must address an existing hypothesised identity.
- A terminal write for an unknown identity is a coded rejection.
  The hunter must write the new sub-slice as `hypothesised` first.
- A merge keeps the survivor identity.
- The survivor body widens; the absorbed identities are listed in `merged_from` and dropped.
- A discriminator value is never edited to widen a spec.

### B5. Symbolic target identity

`SpecWrite.target_identity` becomes optional.
The `hunts_store` tool injects the bound `TargetIdentity` from the dispatch context at write time.
The prompt stops asking the hunter to author the URL or the unit id.
The persisted spec still carries the identity for the pod.

### B6. Typed surface

```python
class Discriminator(BaseModel):
    axis: str
    value: str

class SpecWrite(BaseModel):
    status: str
    target_identity: TargetIdentity | None = None
    discriminators: list[Discriminator]   # 2..4
    verification_symptoms: list[str]
    assumptions: list[str]
    rationale: str
    parent_spec_ref: str | None
    provenance: SpecProvenance
    skills: list[str]
    procedure_overview: str
    merged_from: list[str]
```

`provenance` drops `skill_procedure`.
`SpecWrite` drops `fault_keyword` and `strategy_keyword`.

## Workstream C - skill procedure

### C1. Retire the copied excerpt

Remove:
- `SkillProcedure`;
- `SKILL_PROCEDURE_FIELDS`;
- `SKILL_PROCEDURE_MAX_CHARS`;
- `skill_procedure_from`;
- `skill_procedure_from_spec`;
- `_skill_procedure_context`;
- `_validate_skill_procedure`.

Remove `skill_procedure` from the stored spec and from the pod context.

### C2. Replace with a skill list plus a concretised overview

- `skills: list[str]` names the abstract procedures.
- `procedure_overview: str` is the target-specific concretisation, capped at 1200 characters.
- `rationale`, `verification_symptoms`, and `assumptions` stay the observable contract.

### C3. Pod loading

The pod runner's P0 step loads every declared skill with `load_skill` before probing.
The pod triager loads the same skills before the procedure diff.
The seven gap classes stay as the triager's lens, not as a copied payload.

The triager's Stage B is currently tool-free.
Enabling `load_skill` there adds one tool call per ambiguous pod.
The alternative is a harness-bound, bounded skill body in the Stage B context.
This is an open decision.

## Workstream D - lifecycle robustness

### D1. Blocked state

The gate keeps an anomaly record only for:

1. the graph did not reach COMPLETE;
2. a write appears after the terminal marker;
3. the body is malformed.

The anomaly record must not hold the queue when a degraded pod can run.
The halt cases are 1 and 2 only.
Case 3 dispatches a degraded pod.

### D2. Session timeout

The surfer needs a bounded wait per dispatched hunter and pod session.
The proposed state is `started_at` and `timeout_s` on the run-local dispatch record.
A session past its timeout is classified `degraded`, excluded from `hunts_in_graph` and `live_pod_hunts`, and recorded on the run.
This is simpler than polling the lower control plane's thread state.
The lower control plane API is the fallback if the run-local clock is insufficient.

### D3. Malformed spec fail-safe

- The mover emits a `TestSpecItem` for every produced ratified file, even when the body is unparsable.
- The item carries the raw body and a `malformed` flag.
- The pod projection reads each field with a default and catches parse errors locally.
- The pod renders what is parsable.
- The pod still runs and writes a PodExport.
- The mover consumes the spec.

### D4. Malformed risk assessment

The report must name the scenarios where a malformed body can still halt the pipeline.
The report must give the prevention for each.

## Workstream E - run feedback

**E1. `query_lightrag` fallbacks.**
Diagnose the 19 `model answer unavailable` responses.
Check the retrieval result, the generation finish reason, and the bundle validation errors.
Decide whether the root cause is the generator, the provider, or an artifact we control.

**E2. `auth_store` occupancy.**
Mine the runtime call shapes: `path`, `view`, `fields`, and response size.
Define the canonical minimal field set.
Narrow `view: full` and `view: account`.
Add a response budget with a coded narrowing hint.

**E3. Notes tools.**
Unify `notes` and `note` into one tool with one contract.
Diagnose the 128,813-char read.
Add a bounded read projection.

**E4. `search_http_history`.**
Mine filter profiles, five sample sessions, and the needed detail pairs.
Estimate the spurious-data share.

**E5. `exec`.**
Mine the binaries and command shapes.
Measure the response meaning density.
Propose a concise command convention.

**E6. `graph_view`.**
Mine the query shapes: broad graph query versus narrow endpoint query.
Measure whether the response carries the intended data.

**E7. Skill evolver usage.**
Pass the project id as `usage_scope` to the evolver's session turn.
Confirm the ledger records the evolver role under `/projects/{id}/usage`.
Add a test for the by-agent entry.

## Test gates

Each workstream lands with focused tests.

- `tests/attack/test_hunter_memory.py` - identity, stability, merge.
- `tests/attack/test_hunter_tools.py` - spec write contract, symbolic target.
- `tests/attack/test_hunting_agent_prompt.py` - prompt fields, stale-name absence.
- `tests/attack/pod/test_spec_reads.py` - skill list and overview.
- `tests/attack/pod/test_context.py` - no `skill_procedure` rendering.
- `tests/attack/pod/test_verification.py` - malformed fail-safe.
- `tests/attack/pipeline_sync` and `test_hunting_pipeline_sync_lifecycle.py` - blocked and timeout.
- `tests/attack/test_hunting_surfer_tick.py` - moved-on degraded session.
- `tests/app/llm/test_usage*` - evolver ledger entry.

The feedback-loop gate is:
1. run the focused test file for the change;
2. run the hunting attack suite;
3. run the pod suite;
4. run lint and typecheck.

## Order

1. A - audit and stale matrix.
2. B - identity and symbolic target.
3. C - skill procedure.
4. D - lifecycle.
5. E - run feedback and telemetry.
6. Final report and risk register.

B and C share the spec schema, so they land in one commit.
D is independent.
E splits into code (E2, E3, E7) and analysis (E1, E4, E5, E6).

## Resolved decisions

1. The identity is the value-only form `<class>__<value>__<value>`; the axis names live in the spec body and the `phase:discriminate` note.
2. The copied class excerpt is replaced by `skill_concretised_procedure`; the runner may optionally load the declared skills, and the triager diffs the concretisation.
3. A malformed body is an anomaly record, never a queue halt.
4. The work lands on one branch in four commits.
5. No live trial in this pass; merge into `hunt-enhancement-trunk` after the focused and integration suites pass.

## Delivered so far

- The identity, the nine-field concretisation, the symbolic target binding, and the prompt realignment.
- The impact map and the stale-verbatim audit: `docs/design/hunting-spec-identity-impact-map.md`.
- The attack, pod, integration, and pod-contract suites are green.
