# Hunting spec: typed applies-if predicate / sound unit-projection

Part of [#54](https://github.com/Diekgbbtt/polyphemus/issues/54) (hunting wayfinder map, Phase-2+ concretisation).
Resolves [#63](https://github.com/Diekgbbtt/polyphemus/issues/63) (enhancement, spawned from the [Q2 fault-source resolution](https://github.com/Diekgbbtt/polyphemus/issues/56)).

*Status: spec (decision record + contract), NOT implementation. This is the phase-2 map convention: one spec per graduated ticket. The engine that evaluates the predicate is owned by [#71](https://github.com/Diekgbbtt/polyphemus/issues/71) (deterministic components); the knowledge-base content that carries the predicate is owned by [#66](https://github.com/Diekgbbtt/polyphemus/issues/66) (fault KB). This spec owns the predicate CONTRACT only.*

## 0. Provenance and decision record

- The ticket is blocked-on-paper ("Not takeable until L1 typing matures").
- The blocker was verified honestly against the running code on 2026-08-03: L1 typing today already carries most typed facets the predicate needs (System `kind` vocabulary, System-edge taxonomy, spine-key presence, DataRelationship kinds, data-flow edge existence), and the soundness contract below does not require exhaustiveness of the remaining axes.
- The operator ruled the ticket TAKABLE NOW (grilling 2026-08-03), with a small precise dependency (section 3).
- The operator's rulings, in order:
  - **D-A (blocker verdict)** - land the spec now. A necessary-only default-open predicate is sound over the current typed spine; untyped facets default open. Residual L1 typing dependency: D1-D4 (section 3). "Exhaustive typing of all four axes" is not a precondition.
  - **D-B (placement)** - the typed predicate SUBSUMES the Q8 S1 symbolic pre-filter AND the Q2 fail-open enum gate into ONE deterministic necessary-only stage at the head of FaultSource selection. S1's semantics (prune services missing required systems; system-only fault directions) survive as degenerate clauses of the predicate. The enum gate retires per-entry (risk R-c).
  - **D-C (artifact home)** - KB-embedded. The typed predicate hardens the `applies-if` grammar slot of the fault-KB entries (the slot #66 keeps "typed-SHAPED" for exactly this). One artifact, one authoring seat (the out-of-band KB curation). Unhardened entries stay fail-open.
  - **D-D (verdict semantics)** - the typed stage emits a BINARY prune signal. FALSE is a deterministic `does-not-apply`, recorded with the violated clause as its witness. TRUE/UNKNOWN pass to the LLM match, which ALONE emits the three-valued `{applies, does-not-apply, insufficient-evidence}` verdict. `insufficient-evidence` is an evidence-sufficiency judgment that structure-checking cannot make.
  - **D-E (evaluation surface)** - the predicate is pure symbolic matching over typed attributes and spine-key / edge-family EXISTENCE. NL content (contracts, notes, descriptions) is never matched - it is non-deterministic, hence unreliable as a deterministic gate. TRUST BOUNDARIES are NOT structure-encoded: whether a boundary is load-bearing, or its assumption violated, is a judgment for the LLM pass, never a predicate clause. Edge EXISTENCE is structural and rangeable; edge predicate/assumption SEMANTICS are not (NM-8).

## 1. Problem statement

Phase-1 `FaultSource` selection keeps a minimal fail-open enum gate: each fault entry tags the system-kind(s) it presupposes, units not linked to such a system are pruned from that fault's match prompt, and untagged faults prune nothing.
`applies-if` is authored as natural-language preconditions, not a machine-evaluated typed predicate, because L1 typing was primarily natural language and a predicate over it would be imprecise and hard to maintain (risk R-c).
Q8 additionally pinned a deterministic S1 symbolic pre-filter (spine-type existence, NO natural language, fail-open) as a type-now seam.

Three defects follow:

1. The DD-3 soundness split is not restored at selection.
   The symbolic layer prunes only by coarse kind tags and spine presence, while the fault's real necessary preconditions (which systems must exist, which spine keys must be present, which edge families must connect the unit) stay in unevaluable NL.
2. The enum gate is imprecise and maintenance-heavy.
   Kind tags conflate distinct preconditions, and the tag set drifts from the `SYSTEM_KINDS` vocabulary.
3. Two deterministic filters occupy one stage position.
   The Q8 S1 pre-filter and the Q2 enum gate are both deterministic symbolic prefilters with two ad-hoc vocabularies, overlapping and unintegrated.

## 2. Solution

A **sound typed `applies-if` predicate** over the L1 typed spine, replacing the enum gate and subsuming the S1 pre-filter as ONE deterministic necessary-only stage at the head of `FaultSource` selection.
"Sound" is the ontology's `L1D-28` contract: the predicate can only ever show that a fault-class is *not impossible* at a locus.
It never proves applicability, and it never prunes on anything but a violated machine-checkable necessary condition.
Confirming the fault stays the probe's job.

### 2.1 Placement in the pipeline (D-B)

The deterministic stage occupies the S1 position of the Q8 walking skeleton, ahead of the LLM match and the orchestrator's in-turn reasoning gate:

```
S1 MATCH (deterministic stage - the typed applies-if predicate)
    for each fault class in the KB outer loop (Q2, fault-driven):
      for each candidate unit (Service AND System):
        1. entry carries a typed predicate?
           evaluate predicate against the unit projection (section 2.4).
           FALSE      -> deterministic does-not-apply; record (unit, fault, violated-clause witness);
                         prune. No LLM cost for this pair.
           TRUE/UNKNOWN -> pass to the LLM match.
        2. entry carries only the enum-of-system-kinds tag?
           the tag is the deterministic signal (phase-1 degrade, unchanged semantics).
        3. otherwise: pass (fail-open, high recall).
    survivors feed:
S1b LLM MATCH (unchanged, Q2 body step 3)
    per-fault matching over index-card projections of both unit kinds;
    emits the three-valued match verdict {applies, does-not-apply, insufficient-evidence};
    the yellow value raises the Q6 back-edge need (stubbed, #64).
    -> consumed by the hunt-orchestrator's in-turn hard gate as a prune signal before dispatch (Q8).
S2 RANK (unchanged) -> dispatch (unchanged, #69) -> S3-S7 (unchanged, #62)
```

**The subsumption property (D-B).** The S1 spine-existence semantics are degenerate clauses of the predicate: a fault requiring a System of kind K yields the clause "the unit is reached by / is a K-kind System", and a unit missing every required system evaluates FALSE.
The "services from system-only fault directions" check becomes the predicate's `target` declaration, consumed by candidate-minting (`implicit-coverage` rule, #69).
The enum gate is retired per-entry exactly when that entry's typed predicate lands (R-c).

### 2.2 The evaluation surface - the sound unit-projection (D-E)

The predicate ranges over EXACTLY the unit's typed facets.
The unit projection is the unit's index-card (`index_card.py:27-30,65-76`: typed spine keys lifted, edge-degree by family) plus the one-hop typed neighbour spines, fetched lazily (`dfs_down`, `index_card.py:101-115`; the System-to-Services inverse hop is the read-side addition D3).

**Rangeable facets:**

| Facet | Kind of clause | Grounding |
|---|---|---|
| System `kind` (Service-anchored via one-hop edge target; System-anchored as the unit's own kind) | equality over the validated 12-kind vocabulary | `l1_curator.py:83-101` (`SYSTEM_KINDS`) |
| One-hop typed Service->System edge families (`EXPOSED_VIA`, `AUTHENTICATED_BY`, `AUTHORIZED_BY`, `IDENTIFIED_BY`, `FRONTED_BY`, `PROTECTED_BY`, `ROUTED_BY`, `SHAPES_DATA_OF`, `ON_REQUEST_PATH`, `DEPENDS_ON`) | existence, optionally constrained by target kind / role-presence | `l1_curator.py:129-133` (`SYSTEM_EDGE_RELS`) |
| Spine-key presence on the unit (`exposure`, `service_contract` on a Service; mechanism attributes on a System) | presence; `exposure` value-equality after D1 | `index_card.py:27-30,65` |
| Data axis edge existence: `PRODUCES` / `CONSUMES` to DataItems; DataRelationship edge kinds among the unit's items | existence; kind equality over the validated 6-kind vocabulary | `l1_curator.py:109-116` (`DATA_RELATIONSHIP_KINDS`); `l1_types.py:139-173` |
| System-anchored inverse hop: Services reached back over the System-edge families, their spine presence (e.g. `exposure`) | presence | read-side addition D3 |

**Explicit NON-facets (never rangeable; all belong to the LLM pass):**

- **NL prose** - `service_contract`, `label`/`salience`, System `description`, DataItem `notes`, `assumption_rationale`, and the NL `applies-if` text itself.
  NL content is non-deterministic; a deterministic gate over it would be unreliable (D-E).
- **The technological axis** - no typed L1 handle exists; it is the external symptom-technique KB's join key `(fault-class, unit technological-axis)` per #66.
  Never a predicate facet (the #66 vocabulary non-conflation rule: the gate keys on the technical-axis System-inventory enum, the external KB keys on the technological axis).
- **Trust-boundary semantics** - whether a `CONSUMES` edge is a load-bearing boundary, and whether its assumption is violated, is a judgment, not structure (D-E).
  Edge EXISTENCE is rangeable; the assumption's meaning is not (NM-8).
- **Edge predicate strings** - `CONSUMES.assumption` and DataRelationship `predicate` are NL/unevaluable (NM-8). Existence and kind only.
- **L0 nodes** - the predicate ranges over L1 facets only. The LLM match reaches L0 through the index-card projections, as today.

**Facet absence semantics.** An absent attribute, an absent edge family, or an unvalidated value evaluates UNKNOWN for the clause (default-open), never FALSE.
Absence means not-yet-filled (the L1 convention, catalogue §4.1), so absence can never prune.

### 2.3 The predicate grammar - the hardened applies-if slot (D-C)

One typed predicate per fault entry, authored in the fault KB:

```
target:  "Service" | "System" | "Both"     # the fault direction (D-B); feeds #69 candidate-minting
clauses: AND of 1..N necessary-condition clauses.
```

Clause forms (the phase-1 closed form):

| Form | Meaning | Value-equality allowed? |
|---|---|---|
| `kind-is({K})` | the unit is a System whose kind is one of the validated kinds | yes (validated vocabulary) |
| `reachable-via(family, {kind}, role?)` | the unit has an outgoing edge of the family to a System of a listed kind | kind: yes; role: presence only (free string) |
| `spine-present(key)` | the unit carries the spine key | n/a |
| `spine-equals(key, value)` | the unit's validated value attribute equals the listed value | ONLY over validated value vocabularies (system kind, exposure after D1, DataRelationship kinds); anything else is validator-rejected |
| `serves-units-with(key)` | System-anchored inverse-hop spine presence (after D3) | n/a |
| `data-edge-exists(family)` / `data-relationship-kind({K})` | data axis existence / kind | kind: yes |

A clause may OR over a facet value set (`kind-is {WAF, CDN}`).
Composition is AND only (all clauses are necessary conditions).
No negation, no NL operands, no nested predicates - the phase-1 closed form; phase-2 abduction may deepen the grammar later, this spec forces no one-way door.

**The artifact.** The predicate is a typed data structure - the hardened form of the #66 `applies-if` grammar slot, riding the fault entry beside the NL `applies-if` text and the enum-of-system-kinds tag.
A deterministic **validator** checks it at authoring time: unknown clause forms, value clauses over unvalidated facets, or malformed structure are HARD-REJECTED (mirroring the `DATA_RELATIONSHIP_KINDS` hard-reject discipline, `l1_curator.py:109-116`) - never evaluated at runtime, never silently dropped.

**The necessary-only invariant.** Every clause encodes a machine-checkable necessary condition of the fault.
The predicate may be WEAKER than the NL `applies-if` (it encodes only the machine-checkable subset); it must never be STRONGER (no clause encodes a sufficient condition, no clause encodes an NL-only condition).
The validator enforces the grammar; the authoring discipline enforces the invariant; the #66 checklist-coverage evaluation is the review gate.

### 2.4 The deterministic matching contract

```
evaluate(predicate, unit_projection) -> {pass, does-not-apply, witness}
```

- **Clause semantics are three-valued.** TRUE - the facet matches the clause. FALSE - the facet is present and contradicts the clause. UNKNOWN - facet absent, edge family absent, or value unvalidated.
- **Composition.** The predicate is FALSE iff at least one clause is FALSE (AND of necessary conditions). A clause evaluating UNKNOWN never makes the predicate FALSE.
- **Determinism.** The same projection yields the same verdict. A pure function: no LLM, no randomness, no wall-clock dependence.
- **Fail-open.** Any evaluation error (malformed projection, reader failure) degrades to `pass` with a logged diagnostic. The stage never crashes the caller and never prunes on a bug (the fail-open invariant, `loop-constraints.md`).
- **Witness.** A deterministic `does-not-apply` carries the violated clause id - the FIRST violating clause in authoring order when several clauses are FALSE (a defined choice, so the witness is deterministic). The witness rides the `FaultSource` output's `applies-witnesses` slot (Q2 signature `f(L1) -> {(unit, fault, symptom, applies-witnesses)}`), fault-agnostic on the wire (the fault joins via `correlation_id` in the hunt store, Q6), and persists with the candidate state (#68).
- **Recursion.** None. A flat, closed, phase-1 form.

### 2.5 Verdict semantics (D-D)

The typed stage is a binary prune signal.
The three-valued match verdict stays with the LLM match, unchanged: `{applies, does-not-apply, insufficient-evidence}`, consumed by the orchestrator's in-turn hard gate (Q8 three-level model, level 1).
The yellow `insufficient-evidence` (targeted-recon back-edge, #64) can never be emitted by the deterministic stage: structure-checking cannot judge evidence sufficiency.

### 2.6 Degrade paths

- **Per-facet (authoring-time).** A clause whose facet is unavailable is omitted at authoring - authors write only over available facets, and the validator rejects clauses over unvalidated values. The predicate as authored is always evaluable.
- **Per-entry (runtime).** A fault entry without a typed predicate degrades to its enum-of-system-kinds tag (the phase-1 signal, unchanged), then to default-open (an untagged or unhardened entry prunes nothing - high recall preserved).
- **Whole-stage.** If an L1 typing dependency (D1/D3) has not landed, the corresponding clause forms are simply unavailable to authors; the stage keeps working over the rest. No global "when L1 matures" switch exists.

## 3. L1 typing dependency - precise (D-A)

This spec REQUIRES the following from the analysis context; it does not invent L1 typing:

- **D1 - exposure value proposition (analysis-context, conditional).** A single-source `EXPOSURE_VALUES` constant (`public`, `authenticated`) validated at the `l1_curator` write boundary, mirroring `SYSTEM_KINDS` (`l1_curator.py:83-101`). Needed ONLY if value clauses over `exposure` are wanted (`spine-equals(exposure, ...)`). Without it, exposure clauses are `spine-present` only. Note the raw vocabulary already exists proposer-side as `_EXPOSURE_VALUES` (`analysis/bootstrap.py:69`) - the gap is that it is not a curator-boundary constant, so curators may write unvalidated values. An analysis-context change; its own FR area + verifier per loop discipline when taken.
- **D2 - rendering/navigation attribute promotion (analysis-context, conditional).** Promote `rendering_model` / `navigation_model` from NL-in-`description` to validated typed attributes on the WebPresentation System, with single-source value constants (`RENDERING_MODELS`: CSR/SSR/SSG/StreamingSSR/HydratedSSR; `NAVIGATION_MODELS`: SPA/MPA/Hybrid; the Literals already exist proposer-side, `anatomy.py:100`). Needed ONLY if a KB fault class's strictly-necessary preconditions are rendering/navigation values (e.g. a DOM-XSS-specific class). Default: existence-only over WebPresentation (`reachable-via(EXPOSED_VIA, {WebPresentation})`), which needs NO typing change. NOT assumed a universal spine key (operator caveat, grilling Q1).
- **D3 - inverse one-hop read (read-side, no typing).** A System-to-Services inverse hop (mirror of `dfs_down`, `index_card.py:101-115`) so System-anchored clauses can range over the served services' spine presence. A read-seam addition in analysis, not a typing change.
- **D4 - spine-keys documentation.** Document `_SPINE_KEYS` superset semantics (`index_card.py:27-30`): mechanism keys appearing on a Service card indicate a mis-write to be re-homed; the `business_function` entry never matches a live prop (the real key is the managed `business_function_slug`) and may be dropped. No behaviour change.

**Explicit NON-dependencies** (recorded so the ticket is never re-blocked on them): a typed technological axis (out of predicate scope by the #66 non-conflation rule), structured trust-assumption predicates (NM-8), DataRelationship predicate evaluation (NM-8), and exhaustiveness of `SYSTEM_KINDS` (the "permanent open slot" of `evolution-paradigm.md` Foundation 2 - default-open absorbs new kinds).

## 4. Coordination - what this spec does NOT own

- **#66 (fault KB)** - owns the NL `applies-if`, the enum-of-system-kinds tag, and the KB content. This spec owns the typed predicate CONTRACT that hardens the #66 `applies-if` slot; the KB build folds the predicate in per-entry. R-c retires the enum gate per-entry.
- **#71 (deterministic components)** - owns the FaultSource prefilter ENGINE, the deterministic component that reads the predicate artifact and evaluates it per section 2.4. This spec is the engine's input contract.
- **#69 (control plane)** - the predicate's `target` declaration feeds the `implicit-coverage` rule's candidate-minting (System-strict faults mint no Service candidates).
- **#64 (yellow state)** - the LLM match's `insufficient-evidence` verdict keeps its back-edge wiring; the deterministic stage never emits yellow.
- **#68 (hunt store) / #70 (memory)** - deterministic `does-not-apply` witnesses persist with candidate state; fault-evidence records keep their unit-identity keying.
- **Not duplicated here:** the engine implementation (#71), the KB content (#66), the LLM-match/back-edge wiring (#64), the candidate-minting gate (#69).

## 5. User stories

1. As the hunt-orchestrator, I want a deterministic necessary-only prefilter over typed L1 facets, so that structurally impossible (unit, fault) pairs never reach the LLM match and burn its token budget.
2. As the LLM match, I want every candidate I judge to have passed a sound symbolic gate, so that my three-valued verdict concentrates on evidence sufficiency rather than structural impossibility.
3. As the fault-KB curator, I want one typed predicate slot per fault entry, so that applicability knowledge lives in one artifact with one authoring seat.
4. As the fault-KB curator, I want a hard validator that rejects unsupported clause forms, so that a malformed predicate is caught at authoring time, never at runtime.
5. As a hunting agent, I want deterministic `does-not-apply` witnesses persisted with the candidate, so that a pruned pair is explainable and revisable when the L1 model changes.
6. As the hunt-orchestrator, I want unhardened entries to keep their enum-tag degrade behaviour, so that the KB can harden entries incrementally without a big-bang.
7. As the candidate ranker, I want only structurally possible candidates, so that my likelihood x severity facets are not spent on impossible pairs.
8. As the phase-2 planner, I want the predicate to be a flat closed grammar with a clear deepening path, so that anatomy abduction replaces rather than rebuilds this stage.

## 6. Implementation decisions

- **D-A .. D-E** (section 0) are the load-bearing implementation decisions.
- **The seam.** The single most useful seam is the deterministic stage itself: `evaluate(predicate, unit_projection) -> {pass, does-not-apply, witness}`, a pure function with an injectable `read_fn` (the existing read seams: `index_cards`, `dfs_down`, `index_card.py:86-115`).
- **Second seam.** The authoring-time validator: pure, rejects malformed predicates and value clauses over unvalidated facets.
- **Third seam.** The unit projection reader (index-card + one-hop, both directions); existing seams are preferred, the only new read is D3.
- **Schema note.** The typed predicate is a data structure in the fault-KB entry (#66 owns the artifact; this spec owns its grammar and semantics).
- **The pipeline shape** (section 2.1), the evaluation surface (2.2), the grammar (2.3), the match contract (2.4), verdict semantics (2.5), and degrade paths (2.6) are fixed seams - the engine (#71) implements against them without further design latitude.

## 7. Testing decisions

The verification contract is the assertion catalogue in Appendix A: contract predicates at the deterministic-stage seam (integration tier), walkthroughs at the e2e tier over the Q8 walking skeleton's live L1 model.
The tests are mechanised when the components exist (#71's engine, #66's hardened entries, the D1/D3 additions) - this spec is their source of truth, and expected values are taken from this spec, never recomputed the way the code computes them.
A predicate test that never evaluates a FALSE clause is vacuous; the catalogue's outliers (unknown-facet pass, unhardened degrade, malformed-predicate reject, subsumption parity) are the sharp ones.

## 8. Out of scope

- The FaultSource prefilter engine and its execution (#71).
- The fault-KB content, NL `applies-if` authoring, and checklist-coverage evaluation (#66).
- The yellow `insufficient-evidence` to targeted-recon wiring (#64).
- The candidate-minting / `implicit-coverage` gate (#69) and the hunt store (#68) / memory (#70) internals.
- The L1 typing changes D1-D4 themselves (analysis context, own FR areas when taken).
- A typed technological axis, structured trust-assumption predicates, and DataRelationship predicate evaluation (NM-8).
- Phase-2 anatomy abduction and any deepening of the grammar beyond the phase-1 closed form.

## 9. Further notes

- This stage restores DD-3 at `FaultSource` selection: the symbolic layer reasons over the typed spine, the LLM match consumes the index-card projections, and the two are joined by a pass/fail boundary.
- The predicate's necessity is bounded by the model: a fault class whose necessary conditions are not L1-typed cannot be hardened - its entry stays unhardened and degrades to tag/open. That is the honest ceiling, recorded rather than papered over.
- `L1D-28` (the necessary-only default-open prefilter) is the ontology's name for this contract; this spec is its first full realisation at a specific stage.
- The `FaultSource` interface signature (Q2) is unchanged: `f(L1 model) -> {(unit, fault, symptom, applies-witnesses)}`. Only the body's deterministic half hardens.

---

# Appendix A - Assertion catalogue (to-assertions)

# Assertions - system "typed applies-if predicate / sound unit-projection"

**Source:** `docs/design/hunting-63-typed-applies-if-spec.md` (resolves #63)
**Seams under assertion:** the deterministic stage `evaluate(predicate, unit_projection) -> {pass, does-not-apply, witness}` (pure, injectable `read_fn`); the authoring-time predicate validator (hard-reject); the unit projection reader (index-card + one-hop both directions); the FaultSource selection entry and its pass-through to the LLM match (walkthroughs, counting mode); candidate-minting's consumption of the `target` declaration (joint seam with #69). Mechanised when #71's engine and #66's hardened entries exist; expected values are taken from this spec, never recomputed the way the code computes them.

## Contract predicates (integration)

- **C1 - Determinism and purity.** Seam: deterministic stage + projection reader. Delivery semantic: success (duplicate evaluation). Input: one fixed (predicate, unit projection) pair evaluated twice against the same fake `read_fn`. Observable: both runs yield the identical verdict and the identical witness; the injected LLM `invoke_fn` is called zero times. Yields: `tests/integration/test_fault_source_contracts.py::test_C1_determinism_purity`.
- **C2 - Necessary-only FALSE.** Seam: deterministic stage. Delivery semantic: success. Input: a hardened predicate over a projection where exactly one clause is FALSE from a present-and-contradicting typed attribute (e.g. `spine-equals(kind, ...)` against a present different kind), all other clauses TRUE. Observable: verdict `does-not-apply`; the witness names exactly the violated clause; no FALSE arises from an absent facet or an NL operand anywhere in the run. Yields: `tests/integration/test_fault_source_contracts.py::test_C2_necessary_only_false`.
- **C3 - Default-open on unknown.** Seam: deterministic stage. Delivery semantic: empty-valid (absence). Input: (a) a projection missing the facet a clause ranges over (e.g. `exposure` absent), (b) a projection whose facet value is present but unvalidated. Observable: both evaluate `pass`; UNKNOWN never prunes; the verdict is `pass`, never `does-not-apply`. Yields: `tests/integration/test_fault_source_contracts.py::test_C3_default_open_unknown`.
- **C4 - Grammar validation hard-rejects every malformed class.** Seam: authoring-time validator. Delivery semantic: malformed. Input: (a) an unsupported clause form, (b) a value clause over an unvalidated facet (`spine-equals(rendering_model, "CSR")` before D2), (c) a value clause over a non-facet (the technological axis - no L1 handle exists), (d) a non-AND composition, (e) an empty clause list, (f) an invalid `target` value, (g) a clause over an unknown edge family. Observable: every input is rejected at validation; none reaches evaluation; the stage state does not change. Yields: `tests/integration/test_fault_source_contracts.py::test_C4_validator_hard_reject`.
- **C5 - S1 subsumption parity.** Seam: deterministic stage. Delivery semantic: ordering / regression. Input: the set of (unit, fault) pairs the Q8 S1 spine-existence check would prune (the reference set reimplemented from the Q8 semantics, #62 - never the code's own filter, so the comparison is not a tautology), for faults whose predicate is hardened, over one fixture L1 model. Observable: every such pair evaluates `does-not-apply` under the predicate; the predicate's prune set is a superset of S1's - no regression in what the deterministic gate prunes. Yields: `tests/integration/test_fault_source_contracts.py::test_C5_s1_subsumption_parity`.
- **C6 - Fail-open degradation.** Seam: deterministic stage. Delivery semantic: degradation. Input: (a) a projection `read_fn` that raises, (b) a malformed-at-runtime projection (e.g. missing the `kind` field). Observable: verdict `pass` with a logged diagnostic in both cases; no exception escapes the stage; no pair is pruned by the failure. Yields: `tests/integration/test_fault_source_contracts.py::test_C6_fail_open`.
- **C7 - Witness wire shape is fault-agnostic.** Seam: deterministic stage output (the `applies-witnesses` slot). Delivery semantic: success. Input: a deterministic `does-not-apply` for two different faults on the same unit. Observable: each witness records the violated clause id; neither witness carries the other fault's identity; both join by `correlation_id` only (the Q6 rule). Yields: `tests/integration/test_fault_source_contracts.py::test_C7_witness_fault_agnostic`.
- **C8 - Per-entry degrade.** Seam: deterministic stage + KB artifact. Delivery semantic: degradation. Input: one hardened entry (typed predicate present), one unhardened entry (enum tag only), one untagged entry, each evaluated over the same unit set. Observable: the hardened entry never consults its tag (R-c retired for it); the unhardened entry's tag is the deterministic signal; the untagged entry prunes nothing. Yields: `tests/integration/test_fault_source_contracts.py::test_C8_per_entry_degrade`.
- **C9 - FALSE dominates UNKNOWN.** Seam: deterministic stage. Delivery semantic: success (mixed clause values). Input: a two-clause predicate over a projection where clause 1 is UNKNOWN (facet absent) and clause 2 is FALSE (facet present and contradicting). Observable: verdict `does-not-apply`; the witness names clause 2; the UNKNOWN clause neither masks the FALSE nor becomes the witness. Yields: `tests/integration/test_fault_source_contracts.py::test_C9_false_dominates_unknown`.
- **C10 - Output domain is the binary prune signal (D-D).** Seam: deterministic stage. Delivery semantic: success. Input: the full matrix of clause outcomes (all-TRUE, one-FALSE, all-UNKNOWN, mixed TRUE/FALSE/UNKNOWN) over representative predicates. Observable: the stage yields only `{pass, does-not-apply (+ witness)}`; `insufficient-evidence` is absent from every output - structure-checking never judges evidence sufficiency. Yields: `tests/integration/test_fault_source_contracts.py::test_C10_output_domain_binary`.
- **C11 - Multi-FALSE witness selection is deterministic.** Seam: deterministic stage. Delivery semantic: success (multiple violations). Input: a three-clause predicate over a projection where clause 1 and clause 3 are both FALSE (clause 2 TRUE). Observable: verdict `does-not-apply`; the witness names clause 1 - the FIRST violating clause in authoring order (the section 2.4 choice), never clause 3, never both; re-evaluating the same pair yields the identical witness. Yields: `tests/integration/test_fault_source_contracts.py::test_C11_multi_false_witness_order`.
- **C12 - Family-present kind-mismatch is FALSE; family-absent is UNKNOWN.** Seam: deterministic stage. Delivery semantic: success (contradiction vs absence). Input: (a) a unit carrying an outgoing `EXPOSED_VIA` edge to a RESTApi System, evaluated on `reachable-via(EXPOSED_VIA, {GraphQLApi})`; (b) a unit with NO outgoing `EXPOSED_VIA` edge at all, evaluated on the same clause. Observable: (a) FALSE - the family is present and its target-kind contradicts the clause; (b) UNKNOWN -> `pass` - the family is absent, i.e. not-yet-filled, so default-open. This pins the D-E distinction: absence of the whole family defaults open; presence with a wrong kind is a machine-checkable contradiction. Yields: `tests/integration/test_fault_source_contracts.py::test_C12_family_present_kind_mismatch`.

## Walkthrough predicates (end-to-end)

- **E1 - A hardened fault prunes only the structurally impossible, and the match sees only passers.** Grounds: user stories 1, 2, 7. Entry seam: the `FaultSource` selection entry, walking-skeleton L1 model. Input: the fault class "GraphQL introspection" carrying the typed predicate `target: Both; AND(reachable-via(EXPOSED_VIA, {GraphQLApi}))`, over a project whose L1 has one GraphQLApi System (G) reached by services S1 and S2 and one RESTApi-only service S3. Live edge: the LLM match, running in pass-through COUNTING mode - a declared substitution (its verdicts are #71/#64 scope, not this spec's), asserting only its invocation count; the substitution lifts when the match lands. Path: S1 and S2 evaluate TRUE on the clause (each `EXPOSED_VIA` a GraphQLApi); S3 evaluates FALSE (`EXPOSED_VIA` only RESTApi); the System unit G evaluates UNKNOWN (a System carries no outgoing `EXPOSED_VIA` - the family's direction is Service->System - so the facet is absent and passes); the stage emits `does-not-apply` with the `reachable-via(EXPOSED_VIA, {GraphQLApi})` witness for (S3, fault); S1, S2 and G pass to the match. Terminal: exactly 3 of 4 units pass (S1, S2, G); exactly 1 deterministic `does-not-apply` recorded with the clause-id witness; the match is invoked exactly 3 times (once per passer); the output set contains no `insufficient-evidence`. Observed: the stage's evaluation log read back (4 evaluations: 3 pass, 1 `does-not-apply`); the match invocation counter read back (3). Yields: `tests/e2e/test_fault_source_walkthrough.py::test_E1_hardened_prune_and_match_survivors`.
- **E2 - Unknown-facet default-open in the live model.** Grounds: user story 6; C3 in the live tier. Entry seam: same. Input: a hardened fault with `target: Service` whose predicate clause is `spine-present(exposure)` over a project where service S4 carries `exposure` and S5 omits it (the not-yet-filled convention). Path: S4 evaluates TRUE; S5's absent facet evaluates UNKNOWN, which passes; both reach the match. Terminal: 2 of 2 pass, 0 pruned, 0 witnesses, match invoked exactly 2 times. Observed: evaluation log (2 pass) and the match counter (2). Yields: `tests/e2e/test_fault_source_walkthrough.py::test_E2_unknown_facet_default_open`.
- **E3 - Unhardened entry degrade in the live model.** Grounds: user story 6; C8 in the live tier. Entry seam: same. Input: an unhardened fault entry carrying only `enum-of-system-kinds: {WAF}` over a project with one WAF-fronted service S6 and one non-fronted service S7. Path: S6 passes the tag signal; S7 is pruned by the tag; the typed stage is inert for the entry. Terminal: 1 pass, 1 pruned by the enum tag, 0 typed predicates evaluated, match invoked exactly 1 time (S6 only). Observed: the tag-prune record; the evaluation log is empty for the entry; the match counter (1). Yields: `tests/e2e/test_fault_source_walkthrough.py::test_E3_unhardened_entry_degrade`.
- **E4 - System-strict faults mint no Service candidates.** Grounds: user story 8; D-B. Entry seam: candidate-minting (consumes the predicate's `target` declaration; joint seam with #69). Input: a fault with `target: System` (e.g. a WAF-bypass class) over a project with 2 WAF-kind Systems and 4 services. Path: minting reads the `target` declaration; System-strict faults mint no Service candidates; the WAF Systems are minted and evaluated. Terminal: 0 Service candidates for the fault (none minted, so none evaluated); exactly 2 System candidates (the project's WAF-kind Systems, absent the implicit-coverage carve-out of #69). Observed: the candidate set read back from the minting seam. Yields: `tests/e2e/test_fault_source_walkthrough.py::test_E4_system_strict_mints_no_services`.
- **E5 - S1-subsumption parity live.** Grounds: D-B; C5 in the live tier. Entry seam: same. Input: the walking-skeleton L1 model and the skeleton's fault set with hardened predicates. Path: the deterministic stage prunes its set; the S1 spine-existence check (reimplemented from the Q8 semantics as the walkthrough's oracle, never the code's own filter) prunes its reference set; the two are compared. Terminal: the predicate's prune set is a superset of S1's; the S1-only pruned count is exactly 0 (every S1 prune is reproduced by a predicate clause). Observed: both prune-set sizes read back and diffed. Yields: `tests/e2e/test_fault_source_walkthrough.py::test_E5_s1_subsumption_parity_live`.
- **E6 - FALSE dominates UNKNOWN in the live model.** Grounds: section 2.4 composition; C9 in the live tier. Entry seam: same. Input: a hardened fault with `target: Service` carrying `AND(spine-present(exposure), reachable-via(EXPOSED_VIA, {RESTApi}))`, over a service S8 that omits `exposure` (UNKNOWN on clause 1) and is exposed only via a WebPresentation System (FALSE on clause 2). Path: clause 1 is UNKNOWN (passes), clause 2 is FALSE; the stage emits `does-not-apply`; the witness names clause 2. Terminal: 1 of 1 `does-not-apply` with the `reachable-via(EXPOSED_VIA, {RESTApi})` witness; 0 pass; 0 match invocations. Observed: the evaluation log (1 `does-not-apply`) and the match counter (0). Yields: `tests/e2e/test_fault_source_walkthrough.py::test_E6_false_dominates_unknown_live`.

---

*Glossary impact: the terms crystallised by this spec (typed applies-if predicate, sound unit-projection, deterministic clause semantics, necessary-only invariant, predicate validator, target declaration) land in `src/polymerhus/attack/hunting/CONTEXT.md` in the same change.*
