# Hunting store write contract: derived symbols and the value/attribute boundary

Status: **ratified 2026-10-01** (operator), resolving the write-seam defect surfaced after #294.
This record supersedes the write-seam clauses of the #294 agent-sole-write decision (see section 7).
It is the authority for how every agent-facing store write in the hunting module derives its symbols.

## 1. The failure this resolves

A delivered produced config `_CWE-1220_.yaml` carried `fault_class`, `hunt_id`, `prompt_template`, `status: ratified`, and `surface_context`, but no `unit_id` and no `vulnerability_class`.

`HuntStore.write_config` (`hunt_store.py:262-294`) derived the file name from `data.get("unit_id" / "fault_class" / "vulnerability_class")` with no validation and silently acknowledged the write, so the degenerate `_CWE-1220_.yaml` landed.

Validation ran only on the read path (`surfer.py:315-323`, `hunt_orchestrator.py:1282-1291`), so `_config_dispatch` returned `None`, the mover retried forever, and `run_work_remaining` still saw `status: ratified` - the surfer never quiesced.

The root is a boundary violation: the #294 agent-sole-write model made the LLM author the identity **symbols** the symbolic layer must own, and left the write seam unvalidated.

## 2. The principle: values vs symbols

A config attribute is one of two kinds.

- A **value** is semantic content only the reasoning agent can produce (a rationale, a vulnerability-class naming, a note body, a precondition).
- A **programmable symbol** is identity, naming, path, key, or provenance that the symbolic layer already holds or can build deterministically (the file name, the semantic key, the hunt id, the unit identity).

The symbolic layer owns symbol generation.
The agent owns values.
The #201 `surface_context` carve-out already established this for one field ("a deterministic typed assembly OWNED BY THE HARNESS; the agent never authors it", `hunting-memory-system-spec.md:61-66`); this record generalizes the same principle to every derived symbol.

The file name is a symbol.
It is derived from the config's identity attributes and chained by the naming convention.
It is never an attribute of the request contract.

## 3. The derived-symbol store contract (the pattern)

Every agent-facing store write in the hunting module obeys three rules.

- **Rule 1 - values only in the payload.** The write payload carries domain attributes and values only. Any symbol the store needs (file name, folder key, note key, derived id) is computed by the store from validated attributes, never accepted as its own request field.
- **Rule 2 - validate the derivation inputs.** The store validates exactly the attributes required to derive the symbol. A missing or malformed attribute is a contract violation: the store raises a typed error and the tool returns a coded, field-naming rejection the agent self-corrects on. A silent degenerate symbol (a degenerate file name) must be impossible.
- **Rule 3 - harness-bound identity is bound, not asked.** Identity the harness already holds (for example a hunter's own parent config key) is bound at tool construction, never requested from the model.

The failure mode this pattern forbids is the one in section 1: composing a symbol from an unchecked payload.

## 4. Per-seam dispositions

### 4.1 hunt-orchestrator `hunts_store`

The write payload (`OrchestratorHuntsStoreArgs.hunt_config`) carries the values and the identity attributes.

- Required identity attributes: `unit_id`, `fault_class`, `vulnerability_class`.
- Values: `status`, `rationale`, `research_direction` (top-level since the 2026-10-04 flatten, section 9), `preconditions`, `observed_defences`.
- The store derives the file name `<unit_id>_<fault_class>_<vulnerability_class>.yaml`, the semantic key, and `hunt_id` (section 5) from the validated identity; a missing identity attribute is a coded rejection.
- Orchestrator-owned fields (`surface_context`, `prior_hunt_insights`) are applied by the symbolic layer on the write seam, per the #201 carve-out extended.

### 4.2 hunting agent `hunts_store` and `notes`

- `fault_key` (the hunter's OWN parent config key) is BOUND at tool construction (Rule 3, operator-ratified 2026-10-01). The harness already holds it - the hunter is dispatched with its `HuntConfig` - so it is derived as `semantic_key(unit_id, fault_class, vulnerability_class)` and removed from the request contract; the #199 request-field gate is superseded because there is no longer a request key to validate. The tools degrade with a coded `invalid_args` if no key is bound (a harness wiring defect).
- `fault_keyword` / `strategy_keyword` are AGENT-OWNED identity attributes (operator-ratified 2026-10-01), exactly like `vulnerability_class`: the reasoning model authors them, and it is the store that derives and sanitises the produced spec file name `<fault_keyword>_<strategy_keyword>.yaml` from them. As of the single-payload convergence (2026-10-04, section 8) they ride INSIDE the ONE `spec` write payload, never as separate top-level request fields; the store rejects an empty keyword with a coded, field-naming `hunts_store_write_rejected`, never forming a degenerate name.
- `notes` derives both its destination and the hunt's config key from the caller-bound handle (never a request field); it is conformant.

### 4.3 test-executor pod `note`

- `spec_id` is already bound at construction (Rule 3 conformant).
- `order` is the variant ordinal - a domain value the agent owns, not a derived naming symbol; it stays.
- No file-name symbol is requested; the pod seam is conformant except for the shared rejection discipline, which it already rides.

## 5. `HuntConfig` field dispositions

- `unit_id`, `fault_class` - identity attributes; contract-required on the write, then validated and consumed by the symbolic layer.
- `vulnerability_class` - agent-authored (the elicited identity axis); an empty class is the legitimate carried-bare degrade.
- `hunt_id` - derived deterministically from `(unit_id, fault_class, vulnerability_class)`; the former `uuid4` base plus `-i` fan-out order element is removed (it added a cross-run collision surface while carrying no information beyond the identity).
- `prompt_template.l0_evidence` - **REMOVED**. It was the candidate applies-witness (a two-string deterministic+LLM witness belonging to the fault-match), which overlapped with the unit surface evidence; the witness is folded into the orchestrator-owned `surface_context`.
- `rationale`, `research_direction` - values, agent-authored; TOP-LEVEL fields since the 2026-10-04 flatten (section 9). The `prompt_template` wrapper is **REMOVED**.
- `surface_context` - orchestrator-owned deterministic assembly (#201); now also carries the folded applies-witness.
- `preconditions`, `observed_defences` - values, ratify-filled.
- `sub_fault_ids` - **REMOVED**. It carried bare folded CWE ids that the hunter has no tool to resolve (`kb_query` is the methodology KB, not the fault catalogue), so it was noise for test-implementation authoring; the fold material stays in the orchestrator's materialisation facet.
- `prior_hunt_insights` - kept; orchestrator-owned. It has no in-config overlap (no other field carries the downstream specs/verdicts); the earlier "overlap" with `hunts_store(read)` was a category error (a tool call is not a config entity).

## 6. Failure semantics

- The store raises a typed refusal when the attributes required to derive the symbol are absent or malformed.
- The tool translates that refusal into a coded, field-naming rejection (the `tool_contract.coded_teaching_rejection` pattern): the orchestrator `hunts_store` returns `{"error": "hunts_store_write_rejected", "fields": [...missing...], "detail": ...}` - a machine code plus the field names - so the agent sees a contract violation it can correct, not a silent success and not a bare pydantic error.
- A write that cannot form a valid config is never persisted.
- The symbols the store owns are additionally ENFORCED at the write: `hunt_id` is overwritten with the deterministic derivation (`semantic_key(unit_id, fault_class, vulnerability_class)`) so a prompt-compliant payload that omits it (the agent contract says the harness derives it) can never persist a config the surfer's `HuntConfig` validation would later refuse.

## 7. Superseded decisions

- #294 "the agent's store tool calls are the sole initiator of config/note persistence" stands, EXCEPT that the identity symbols (file name, semantic key, hunt id) are derived by the symbolic layer from validated contract attributes rather than authored blindly by the agent.
- `hunting-memory-system-spec.md` section 6.1 "internal schema validation never rejects on missing attributes" is superseded: the identity attributes are now required and validated.
- `hunting-orchestrator-candidates-rewrite-spec.md` section 3.5's `l0_evidence` and `sub_fault_ids` slots are removed; `hunt_id` derivation changes from a `uuid4` base plus `-i` to a deterministic function of the identity triple.
- The `#199` request-field `fault_key` gate is SUPERSEDED (section 4.2): the hunter's `fault_key` is harness-bound, so there is no model-emitted key to gate. Amended in `hunting-164-state-graph-spec.md` (the `fault_key` contract), `hunting-pipeline-wiring-adr.md` (the model-facing `fault_key` contract), and `hunting-164-assertion-catalogue.md` (C23/C24).
- The pod `note` seam is CONFORMANT and unchanged: `spec_id` is bound at construction, `order` is a domain value, and no file-name symbol is requested (section 4.3).

## 8. Single-payload convergence (2026-10-04)

The write seam surfaced a second defect of the same boundary kind as section 1, this time on the hunter's `hunts_store`. The tool's JSON schema - what the model sees - declared `fault_keyword` / `strategy_keyword` / `mode` with defaults (`required: ["command"]` only), while `HuntsStoreTool._write` REQUIRED both keywords. A model that followed the schema and omitted a keyword got an `invalid_args` rejection (the run-`2d4a5bf9` defect: the first spec write omitted `strategy_keyword`). The requiredness was spread across the schema (optional) and the code (required), so the surface and the contract disagreed.

The fix generalises Rule 1 to the payload SHAPE: a store write takes ONE payload object, never a spread of sibling request fields whose requiredness the schema can only under-state.

- The hunter's `hunts_store` write payload is the single `spec` object; `fault_keyword`, `strategy_keyword`, and the write mode ride INSIDE it (the mode is derived from `status`: `hypothesised` creates, every other state updates). This is exactly the orchestrator's `hunt_config` pattern, so the two `hunts_store` surfaces converge.
- A payload missing a derivation input is a coded, field-naming `hunts_store_write_rejected` (`fields` + `detail`), the same discipline section 6 pins for the orchestrator.
- The symbolic layer still owns the file name: `<fault_keyword>_<strategy_keyword>.yaml`, sanitised and derived from the payload's attributes.

This supersedes the "they stay in the request contract" clause of section 4.2 (the attributes stay agent-authored, but they are payload members, not request fields).

## 9. The `prompt_template` flatten (2026-10-04)

A third instance of the same boundary failure surfaced live. The orchestrator's ratify write overwrote the minted draft with a payload that omitted `prompt_template`; the store persisted the body unvalidated, and the surfer's `HuntConfig.model_validate` refused it every tick while `run_work_remaining` still counted `status: ratified` as work - the section-1 deadlock, one field over.

The root: `HuntPromptTemplate` was a container wrapping exactly two plain strings (`rationale`, `research_direction`). It carried no structure worth owning, yet the #294 agent-sole-write model made the model re-supply the CONTAINER on every write - a symbol/assembly the harness already held (the mint builds it from the direction).

The fix removes the container rather than adding another injection seam.

- `HuntPromptTemplate` is **REMOVED**; `rationale` and `research_direction` are TOP-LEVEL `HuntConfig` fields.
- The hypothesise write carries the seeds as top-level attributes (the minted draft's canonical content).
- The ratify write is the one write where the model may omit them: the write seam (`SurfaceContextStore`) fills a MISSING/EMPTY `rationale` / `research_direction` from the pair's minted draft (threaded via `set_projection(seed=...)`), so a ratify payload can never lose the pair's canonical seeds. A model-authored value is kept (the seed fills, never overwrites).
- `_HUNTS_STORE_DESCRIPTION`, `OrchestratorHuntsStoreArgs.hunt_config`, the gate/ratify prompts, and the hunter render are updated to the top-level shape.
- **The dispatch predicate and the work predicate are unified.** `surfer._ratified_config` is the ONE validity predicate: a config is dispatchable work only when `status == "ratified"` AND it parses as a `HuntConfig`. `run_work_remaining` and `build_run_dispatch` both use it, so a malformed `ratified` body is refused, stays produced (at-least-once), is logged once, and can neither hot-loop the mover nor wedge the quiesce. Before this, the two predicates disagreed (work = status alone; dispatch = status + validation) - the docstring's "never disagree" claim was false.

The rule this confirms: a harness-held assembly is either INJECTED on the write seam (like `surface_context`, `prior_hunt_insights`, the pair's seeds) or FLATTENED into plain values; it is never left as a container the model must re-author. And whatever the write seam validates, the read/dispatch seam must validate with the SAME predicate.

## 10. The persisted schema per status (the status-lifecycle contract, #313)

Status: **confirmed intended, documented** (2026-10-08, ticket #313 / eval-bug EV-9). The ticket asked whether the hunt-config/spec shape varying by status is a defect; it is not, and this section pins the contract so a consumer can never read the wrong shape.

The two hunting memory stores carry a **status-varying schema by design**, because the status lifecycle IS the fault-processing tracker (`hunting-164-state-graph-spec.md` section 6; `hunting-memory-system-spec.md` section 5). The variation is progressive enrichment, never an untyped ambiguity.

- **Hunt config** (`HuntStore`): the body is always ONE typed `HuntConfig` field set; only its content varies with `status`. `hypothesised` carries the seeds (`rationale` / `research_direction`) with the ratification fields empty; `ratified` fills `preconditions` / `observed_defences`; `dropped` is the orphaned draft (still the same field set, marked `dropped`, never deleted, G6). A partial on-disk body is valid: every consumer that trusts fields MUST `HuntConfig.model_validate` it first (defaults fill the absent slots).
- **Hunter spec** (`HunterMemoryStore`): while the status is `hypothesised | verified | dropped` the body is a hypothesis-only `FaultItem` draft (`fault_id` / `mechanism` / `supports` / `conflicts` / `test`); once `specified` the body is the typed `TestImplementationSpec` base (`target_identity` / `verification_symptoms` / `testing_pattern` / `assumptions` / `payload_vector_space`, plus the two NL fields) - the same D4 shape the pod's `validate_spec` consumes (`hunting-agent.md`'s SPEC-WRITE example).
- **The spec identity is the file-name stem** `<fault_keyword>_<strategy_keyword>` (the ADR #169 Q13 semantic `spec_id`, the pod session discriminator, the `pod-export:<spec_id>` note key). It is a DERIVED symbol (Rule 1 / #298): a typed `specified` payload carries no `spec_id` field, so any consumer needing the identity derives it from the file name (or the payload's `fault_keyword` / `strategy_keyword`), never reads a payload `spec_id`.

The consumer rule this pins:

- **Dispatch and work gate on the persisted `status`.** Only a `ratified` config and a `specified` spec are dispatchable work (`surfer._ratified_config` / `run_work_remaining` / `build_run_dispatch`); a hypothesised/dropped leftover is NOT work and never holds the quiesce.
- **A consumer must read the shape the status pins, never the other one.** The pod only ever receives a `specified` spec (the typed base); the prior-hunt-insight read surfaces only the completed `specified` specs (`HuntStore.read_hunter_specs`, I3) and never a hypothesis-only draft - a dropped/hypothesised/verified draft is not a `TestImplementationSpec` and must not be laundered into a completed downstream insight. The in-memory graph `SpecItem` derives its semantic identity from the typed payload's `fault_keyword` / `strategy_keyword` (`hunter_state._with_specified`), so distinct ratified specs keep distinct identities and never collide under an empty `spec_id`.

Regression pins: `tests/attack/test_hunt_store.py::test_read_hunter_specs_surfaces_the_typed_specified_spec_only` (the persisted-schema consumer) and `tests/attack/test_hunter_state.py` (the payload-shape consumer).
