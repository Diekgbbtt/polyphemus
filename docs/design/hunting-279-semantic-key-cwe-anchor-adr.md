# ADR: CWE-anchored semantic-key split + the singleton identity surface (#279)

Status: decided 2026-10-05 (operator ticket #279). The CWE-anchor code fix landed on `dev` at `2dccc5c`; this ADR and its follow-up decision are uncommitted on a worktree off `dev` at `198d3b9`.
Ticket: #279.
Owning design: `hunting-memory-system-spec.md` section 4 (config identity); the store pattern lives in `hunting-store-write-decisions.md`.
Code: `src/polymerhus/attack/hunting/hunt_store.py` (`split_semantic_key`), consumed by `hunter_memory.py`; the follow-up touches `fault_source.py`, `unit_projection.py`, `llm.py`, `index_card.py`, and `hunt_orchestrator.py`.

## Context

A config's canonical identity is the semantic key `<unit_id>::<CWE_ID>::<vulnerability_class>` (`hunt_store.semantic_key`).
A testable unit is a kind-qualified identity (`HUNTING/CONTEXT.md`, "testable unit").
A System unit id therefore contains `::` itself, for example `System:AuthorizationSystem::__singleton__`.
Its semantic key then carries more than three `::` segments: `System:AuthorizationSystem::__singleton__::CWE-1220::BFLA`.

Four call sites recovered the key parts with a naive `key.split("::")`:

- `HuntStore.consume_config` raised, so the inbox-surfer mover never moved produced -> consumed.
- `HuntStore._fault_key_to_config_key` mis-normalised the same shapes.
- `HunterMemoryStore.config_key_from_fault_key` mis-normalised the same shapes.
- `HunterMemoryStore._validate_fault_key` refused the same shapes.

Live symptom (hunting run `84741da5`, project `12da8565`, comfyui-trial-1): 4 configs produced, 0 consumed, the mover logging the refusal every tick, the run hanging in `running`.

## Decision

Parse the semantic key with ONE shared helper, `hunt_store.split_semantic_key`, and route all four call sites through it.

- **Anchor on the CWE token**: the regex `::(CWE-\d+)::` locates the fault segment, so a unit id containing `::` round-trips with any number of segments.
- **Fall back to the plain 3-part split** for a non-CWE fault token (`len(parts) == 3`, non-empty unit and fault).
- **Refuse a 3-part key whose last segment is a CWE token**: that shape is an ambiguous `::`-bearing revival key (`<unit>::<fault_class>` where the unit itself contains `::`), never a config identity.
- **Keep `parse_config_file_name` as the independent `_`-join parse**: the file-name convention still anchors on its own CWE token.

The 2-part revival key stays a refused config identity at every site: it is a prefix, not an identity.

## Consequences

- A `::`-bearing unit round-trips write -> read -> consume; the mover drains and the run quiesces.
- The revival key remains refused, including the ambiguous `::`-bearing 3-segment form.
- The plain fallback stays ambiguous for a non-CWE fault token on a `::`-bearing unit (a 3-segment revival key reads as a semantic key).
  This is accepted because a config identity always carries a CWE fault token (`_CONFIG_FILE_RE`), and the fallback preserves the historical non-CWE behaviour.
- If another identity grammar is ever added, it must reuse `split_semantic_key` rather than reintroduce a local split.

## Verification

- `tests/attack/test_hunt_store.py::test_semantic_key_round_trips_a_system_unit_containing_double_colon` drives write -> read -> consume with `System:AuthorizationSystem::__singleton__` (a legacy/foreign key the parser must still handle).
- `tests/attack/test_hunt_store.py::test_consume_config_still_refuses_a_two_part_revival_key` pins the refusal.
- `tests/attack/test_hunt_store.py::test_fault_key_to_config_key_accepts_a_system_unit_folder` pins the folder normalisation.
- `tests/attack/test_hunter_memory.py::test_config_key_from_fault_key_accepts_a_system_unit_with_double_colon` pins the key normalisation and `_validate_fault_key`.

---

# Follow-up (#279, 2026-10-05): remove the `__singleton__` literal from the orchestrator-facing identity

## Context and the operator's argument

The CWE anchor above keeps the semantic-key grammar stable, but it leaves the literal `__singleton__` inside the key the orchestrator reads (`AuthorizationSystem::__singleton__::CWE-...::...`).
The prior implementer kept that literal because replacing it "would reach into graph identity minting, not just the store - out of the fix's blast radius".
The operator accepts that risk assessment as valid but rejects its weight: the literal is ambiguous and confusing, and a typed-surface identity can remove it with a small diff.

The operator named two candidate replacements for the WebPresentation System entity: the SHA-1 of the System description, or the endpoint attribute.
This section records the rationale, the blast radius, the evaluation of every candidate, and the chosen replacement.

## The rationale (extracted, with citations)

The System identity key is `(project_id, kind, discriminator)` and the discriminator MUST be a non-null string.
A null discriminator is never equal to itself under Neo4j `IS UNIQUE`, so two `MERGE`s of a null-keyed singleton create two nodes - the `L1R-2` trap.

- `docs/design/L1-MVP-plan.md` D2: "System `(project_id, system_kind, discriminator)` with `discriminator` a literal non-null string defaulting to `\"__singleton__\"` ... No nullable-key precedent exists, so the sentinel must be a real string (a `null` discriminator MERGE'd twice creates two nodes - the `L1R-2` trap)."
- `docs/design/L1-MVP-plan.md` global constraint: "`__singleton__` is a literal non-null string (`L1D-9`/`L1R-2`), never SQL/Cypher `null`."
- `docs/design/service-system-model-L1-implementation-bridge.md` Q7: "**No nullable-key precedent** - every L0 key component is non-null, so the `__singleton__` sentinel (L1D-9) has no existing analogue and must be a real non-null string."
- `docs/design/service-system-model-L1-implementation-bridge.md` L1D-9: "`$d` defaulting to the literal string `\"__singleton__\"` (never null - dodges Neo4j's null-uniqueness trap, `NM-6`/`L1R-2`)".
- `docs/design/l1-domain-model-catalogue.md:151-155`: "**Identity:** `(project_id, kind, discriminator)`; `discriminator` defaults to the non-null sentinel `\"__singleton__\"` (`L1D-9`)." and "`discriminator` (identity) - `__singleton__` unless the target genuinely has multiple instances of the kind".
- `CODING_STANDARD.md:236,241`: "A System on `(project_id, kind, discriminator)` with the non-null `__singleton__` sentinel so a null discriminator cannot silently duplicate a singleton (`L1D-9`)." and "`discriminator` defaults to the literal `\"__singleton__\"`, never null."
- `loop-constraints.md:24`: "`discriminator` defaults to the literal non-null string `\"__singleton__\"` (`L1D-9`/`L1R-2`), never null."
- `src/polymerhus/analysis/mechanism_typist.py:118-163` (#53): "a WebPresentation is ALWAYS per (service, cluster), so a `__singleton__` WebPresentation is never a legitimate node when a discriminated one exists."

In one line: any replacement MUST stay non-null, unique per distinct System, deterministic (MERGE-idempotent), and readable in the semantic key.
The graph identity itself cannot become nullable, and `loop-constraints.md` is the binding authority for the sentinel - so a fix that removes the discriminator from the graph key would require an operator-ratified invariant change, which is out of scope.

## Blast radius of the literal

The literal is single-sourced in `analysis/l1_types.py::L1_SINGLETON` (`__singleton__`), with local copies in `mechanism_typist.py::_SINGLETON` and `recon/domain/graph_read.py::_L1_SINGLETON`.
The table separates the graph-identity producers (which must keep the non-null sentinel) from the surface consumers (which can elide it).

| Layer | File:site | Role | Touched by this follow-up? |
|---|---|---|---|
| analysis (identity) | `l1_types.py:36,88,185` | canonical `L1_SINGLETON` + `SystemDelta`/`SystemEdgeDelta` defaults | no (graph identity kept) |
| analysis (display) | `l1_types.py:39-48` | the ONE shared `elide_singleton` display rule | **yes - added** |
| analysis (identity) | `analyser_types.py:49,118` | proposer defaults | no |
| analysis (identity) | `l1_curator.py:257-262,579-601,837` | blank coercion + `MERGE (kind, discriminator)` | no |
| analysis (identity) | `bootstrap.py:230,366,385-387` | shell default + linchpin coercion | no |
| analysis (identity) | `curation_types.py:128-132` | bare-key parse -> sentinel | no |
| analysis (identity) | `mechanism_typist.py:42,141-159` | `_SINGLETON` + WebPresentation reconcile | no (kept) |
| analysis (display) | `l1_inventory.py:45` | `_render_system` elides the singleton | **yes - reuses `elide_singleton`** |
| analysis (display/surface) | `index_card.py:61-70` | the card key carried the raw sentinel into every card consumer (the orchestrator prompt, the persisted `surface_context`) | **yes - elides the sentinel at source** |
| analysis (WebPresentation) | `anatomy.py:289-297` | per-service discriminator (never singleton) | no |
| recon (display) | `graph_read.py:61-73` | `node_name` elides the singleton | **yes - reuses `elide_singleton`** |
| attack (unit-id producer) | `fault_source.py:346-365` | re-attached the sentinel into the unit id | **yes - stops re-attaching** |
| attack (unit-id reader) | `unit_projection.py:184-206` | required `kind:key` | **yes - bare kind -> singleton** |
| attack (prompt render) | `llm.py:210-231` | rendered `discriminator=__singleton__` | **yes - elides the sentinel** |
| attack (surface matcher) | `hunt_orchestrator.py:712-736` | matched `unit_id == "<kind>:<disc>"` only, so a bare-kind singleton silently skipped its card expansion | **yes - accepts the bare kind** |
| attack (key grammar) | `hunt_store.py:131-152`, `hunter_memory.py` | CWE-anchored parse | no (still needed for discriminated keys) |
| tests | `test_fault_source.py`, `test_hunting_runtime.py`, `hunting_fixtures.py` | fixture/expectation unit ids | **yes** |
| tests | `test_unit_projection.py`, `test_hunting_llm.py`, `test_hunt_store.py`, `test_hunt_orchestrator.py` | new coverage | **yes (additive)** |
| docs | `hunting-memory-system-spec.md`, `attack/hunting/CONTEXT.md`, this ADR | the key examples | **yes** |

Quantified: 12 source files reference the sentinel, but FIVE are on the orchestrator-facing surface (`fault_source`, `unit_projection`, `llm`, `index_card`, `hunt_orchestrator`); the rest are graph-identity or display that routes through the shared `elide_singleton`.
The identity minting, the Neo4j constraints, and the sole-writer are untouched.

## Candidate evaluation

### (a) SHA-1 of the System description - REJECTED

The System `description` is a prop, and the mechanism-typist COMPOUNDS it on extension (`attack/hunting/CONTEXT.md`, "System description (discriminative attribute)").
If the discriminator were a hash of the description, then an extension would change the discriminator, which changes the identity key, so the `MERGE` would CREATE a second node instead of amending the first - MERGE-idempotency is broken.
The description is also LLM-authored, so the hash is not deterministic across runs, and a hash is not readable in the semantic key.
This violates three of the four invariants (deterministic, MERGE-idempotent, readable).

### (b) the endpoint attribute - REJECTED

Per #53 a WebPresentation is per (service, rendered-page CLUSTER), and the cluster's member page paths ride the `pages` prop (`attack/hunting/CONTEXT.md`, "WebPresentation").
The `pages` (endpoint) set is the unit's MEMBER set, so keying the identity on it violates `identity ⊥ membership` (`L1D-11`).
It is also not unique per distinct System in general, and it does not generalise to non-WebPresentation singleton kinds (`AuthorizationSystem`, `WAF`, `RESTApi`).

### (c) the bare kind as the singleton's typed-surface identity - CHOSEN

A singleton System has exactly one instance per kind, so the kind alone IS its unique, deterministic, readable identity.
The graph keeps `(project_id, kind, discriminator="__singleton__")` unchanged; only the orchestrator-facing render elides the internal sentinel.
This is the identity surface the codebase ALREADY uses for display (`l1_inventory._render_system`, `graph_read.node_name`, the analyser prompts "kind[:discriminator]").
The projection reader resolves a bare kind back to `(kind, L1_SINGLETON)`, so the read hits the same node.

Invariant check:

- **non-null**: the graph discriminator stays the literal `__singleton__`; nothing becomes null.
- **unique per distinct System**: singleton -> bare kind (one node per kind); multi-instance -> `<kind>:<discriminator>`; the map is bijective.
- **deterministic / MERGE-idempotent**: the identity key is unchanged, so re-runs converge exactly as before.
- **readable in the semantic key**: a singleton key is a clean 3-part `AuthorizationSystem::CWE-...::...`; the ambiguous literal is gone.

## Decision

Elide the internal `__singleton__` sentinel from the orchestrator-facing identity surface, and resolve a bare kind back to the singleton on read.

- `fault_source._project_unit_ids` emits the inventory's already-elided render (`<kind>` for a singleton, `<kind>:<disc>` otherwise) instead of re-attaching `L1_SINGLETON`.
- `unit_projection._split_unit_id` resolves a bare id to `(kind, L1_SINGLETON)` and refuses a bare id that does not name a known System kind.
- `index_card._card_from_row` elides the sentinel from the System card KEY at source, so no card consumer (the orchestrator prompt's raw surface render, the persisted `surface_context`, the curation prompt) ever sees the literal.
- `llm._system_render` elides a `discriminator == L1_SINGLETON`; the elision rule is the ONE shared `l1_types.elide_singleton`, reused by the L1 inventory render, the frontend node formatter, and the prompt render.
- `hunt_orchestrator._unit_matches_card` accepts the bare-kind singleton form (and `kind:disc` for a multi-instance), so the surface-context expansion still fires for a singleton target.
- The CWE anchor in `hunt_store.split_semantic_key` REMAINS: a discriminated System still carries `::` (`WebPresentation:<service>::<cluster>`), so `::` is still not a unique separator.
- The graph identity, the Neo4j constraints, and `loop-constraints.md` are unchanged.

## Consequences

- A singleton config's semantic key, unit id, index-card key, and prompt render never contain `__singleton__`; the orchestrator reads a bare kind end to end.
- A discriminated System (`WebPresentation:<service>::<cluster>`) keeps its `::`-bearing key, so the CWE anchor stays load-bearing.
- A legacy/foreign config keyed with `AuthorizationSystem:__singleton__` still parses and consumes (the parser is unchanged).
- Residual risk: a singleton WebPresentation (the LLM under-clustered and no discriminated node exists) now reads as bare `WebPresentation`; it is still an under-clustering artifact (#53, an A.2 concern the mechanism-typist deliberately leaves untouched), not an identity defect.
- If a later change wants the sentinel out of the GRAPH too, it must amend the binding `loop-constraints.md` invariant with operator ratification; this follow-up deliberately does not.

## Verification

- `tests/attack/test_fault_source.py::test_materialize_candidates_empty_batch_selects_over_the_live_l1` pins the bare-kind platform selection.
- `tests/attack/test_hunting_runtime.py::test_empty_candidate_launch_reasons_over_platform_selection` and `...::test_empty_candidate_launch_reasons_through_the_real_pass` pin the end-to-end bare-kind configs.
- `tests/attack/test_unit_projection.py::test_build_projection_bare_kind_resolves_the_singleton` pins the read resolution, and `...::test_build_projection_rejects_a_malformed_bare_unit_id` pins the restored malformed-id refusal.
- `tests/attack/test_hunting_llm.py::test_system_render_elides_the_singleton_sentinel` pins the SystemInfo render, and `...::test_compose_gate_prompt_over_a_singleton_card_has_no_sentinel` pins that the composed hypothesise prompt over a singleton card carries no literal.
- `tests/attack/test_hunt_orchestrator.py::test_unit_matches_card_accepts_the_bare_kind_singleton` pins the surface-context matcher for a singleton and a multi-instance System.
- `tests/attack/test_hunt_store.py::test_singleton_unit_id_has_no_sentinel_and_a_clean_three_part_key` pins the clean 3-part key and the produce -> consume move.
