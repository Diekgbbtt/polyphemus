# DataPlane Analyser (A.1) - agent specification and decision record

Status: RATIFIED by the operator, 2026-07-30, through a direct grilling pass (not the drafting agent's own judgment - every DPL-DEC below and the open questions in section 17 were put to the operator individually or in a bounded batch and answered; several corrected the drafting pass's own claims).
Ticket: #10 (`Agent spec: DataPlane Analyser`), executed together with #42 (the 2b schedule flip).
Base: `feat/dataplane-analyser`, branched off `dev` at 5c1fed4 (which carries the mechanism-typist work).

Scope: A.1 is specified in full and is the build target.
A.2 is SCAFFOLDED ONLY, by an inert phase guard, and is marked `designed-not-built` per `CODING_STANDARD.md` section 12.
Reusability across A.1 and A.2 is explicitly NOT a design priority; section 12 states precisely which components and data survive the adaptation, and which do not.

This record does not restate what T1 (#2), T2 (#3), T3 (#4) and T4b (#6) already fixed.
It resolves the grey points #10's resolution comment left open, records what the code contradicts, and specifies the agent along the operator's nine-leg agent-definition schema.

Conventions: plain dash only; one full sentence per physical line; ubiquitous language taken verbatim from `src/polymerhus/analysis/CONTEXT.md`.
Every decision below carries its claim, the evidence in the repo that licenses it, and the strongest alternative it rejects.
A judgment with no evidence citation is not recorded as a decision here; it is an open question in section 14.

---

## 1. The DataPlane Analyser's responsibility, restated

The DataPlane Analyser (the `data_modeller` proposer role) has sole ownership of the Tier-1 trust substrate.
Given a chunk of streamed surface, it lifts the logical `DataItem`s the surface evidences, binds each to the concrete L0 sites where it appears via `SURFACES_AT`, and maps the `PRODUCES` / `CONSUMES` flows that connect those items to the settled Service model, plus the baseline surface-observable `DataItem` to `DataItem` dependencies.

It does not classify Endpoints into Services (the Assigner), it does not type mechanisms (the mechanism-typist), and it does not mint Services.
It emits `L1DeltaBatch{data_items, surfaces_at, data_flows, data_relationships}` and nothing else.

The three "no edge is written" mechanisms named in `assigner-A1-decisions.md` section 2 apply here with one substitution.

**Gate** (input side): the per-role admission set narrows the stream to `Parameter` and `Header` (`chunking.py:64-68`), and the httpx profile gate applies to `Parameter` (`chunking.py:44`).

**Narrow** (output side, structural): the agent may not emit a class of delta at all, whatever the model returned.
Realised by `narrow_to_data`.

**Ground** (output side, epistemic): the agent looked, formed a judgment, and declines to commit it because the judgment is not anchored to observed surface.
This is the data plane's substitute for the Assigner's **Withhold**, and the substitution is forced rather than chosen.
The four data proposal shapes carry no `confidence` field at all (`analyser_types.py:67-101`), because the judgment envelope is reserved for `AGGREGATES` alone - "the deliberate envelope asymmetry" (`CONTEXT.md`, *Judgment envelope*).
There is therefore no bar to calibrate against and no percentage-scale defect class to repair; the epistemic control on this path is groundedness in observed surface, not a confidence threshold.

---

## 2. Leg 1 - role

The sole home for the Tier-1 data substrate, in the analysis bounded context, as a supervised A.1 proposer.

It is a proposer, never a writer: every write reaches the graph through `l1_curator` (`loop-constraints.md`, sole-writer), it emits no Cypher, and it never sets provenance or identity keys (`analyser_types.enrichment_proposals_to_deltas` stamps provenance at the curate boundary).
It is fail-open throughout, and every fail-open path is counted (section 8).
Every collaborator is injected with a lazily-resolved production default, so the unit tier touches neither a database nor a live LLM (`docs/design/testing-strategy.md` section 2, enforced by `tests/conftest.py`).

Home: a new standalone module `src/polymerhus/analysis/data_modeller.py`, the peer of `assigner.py` and `mechanism_typist.py`.

## 3. Leg 2 - workflow

Per dispatch, over one chunk, in this order.

1. Guard the phase: `dispatch.phase != "A1"` returns `None` (hollow), the inert A.2 seam.
2. Narrow the chunk to the admitted types via `admit_for_role(chunk, "data_modeller")`, yielding the streamed `Parameter` and `Header` assets.
   An empty admitted set returns an empty batch without an LLM call (valid empty).
3. Re-derive the LIVE context at dispatch time (never from the chunk): the L1 inventory, and the Service to L0 aggregation view.
4. Derive the candidate owning Services for each admitted asset by joining the aggregation view against the asset's identity (section 6).
5. Call 1, REFLECTION (free prose): work the seven-step scaffold of section 7 out loud over the admitted surface, its origin-scoped adversarial observation insight, and the currently-known DataItems with their observed fields and notes.
   Exhaustion of `bounded_retry` fails the step CLOSED to an empty batch, and is counted.
6. Call 2, EXTRACTION (structured): turn the prose into the four data lists in ONE call.
   Exhaustion yields an empty batch, and is counted.
7. Apply the six ordered shaping gates of section 5 to the raw batch, producing the shaped batch, the backlog, and the per-chunk census.
8. Log one structured line naming every gate's count, and return the shaped batch to the supervisor wrapper.

The supervisor writes it: `proposer -> auditor -> curator`, with the curator's `write_fn` routing the data deltas through `enrichment_proposals_to_deltas` into `l1_curator.enrich`.

**Ordering within the chunk.**
The schedule is chunk-major over three roles: per chunk, `assigner`, then `mechanism_typist`, then `data_modeller` (`supervisor.build_schedule`, extended per section 11).
The data_modeller runs LAST on purpose, and the reason is structural rather than aesthetic.
A `Parameter`'s identity carries `endpoint_path` and `baseurl` (`l0_stream.L0_IDENTITY_KEYS:35`), and a `data_flow` needs a `service_slug`; the only bridge between them is the `AGGREGATES` edge the Assigner writes for the Endpoint at that path.
Because a chunk carries every streamed asset type and the Assigner admits the Endpoints of that same chunk (`chunking.chunks_for_job`), running the data_modeller after the Assigner on the same chunk means the join has a live answer for the very parameters in front of it.
Reordering the roles would leave the data plane deriving flows against an inventory that does not yet know who owns the endpoints its parameters hang off.

## 4. Leg 3 - goal

Answer L1R-7: a non-empty, grounded Tier-1 data substrate, so that the L1 abstraction delivers the trust layer the whole model is for.
T1 (#2) section 2 states the deliverable predicate: `count(:L1DataItem) >= 1`, each with at least one `SURFACES_AT` to a real L0 site AND at least one `PRODUCES` / `CONSUMES` flow.
An empty data layer means the whole abstraction under-delivers, so this agent is load-bearing rather than an enrichment nicety.

Precision-first at A.1, in the same sense as the Assigner: an ungrounded DataItem is worse than an absent one, because it looks answered and every later phase inherits it without a signal that it happened.
Two measured failure directions bound the goal.

- The legacy single data call returned ZERO `data_items` under assignment load, and again when the prompt was framed negatively - the positive-recipe repair is recorded in `pod.py:330-335` and in the `analyser-two-pass-weak-model` memory note.
- `fields` speculation is named a specification failure by T1 section 3 ("`fields` names ONLY observed fields; speculation is a failure") and by the catalogue section 4.3 ("evidence-bound only; speculative fields are forbidden").

So the goal has a floor and a ceiling: an all-empty batch over real parameter surface is a wrong answer, and a plausible-but-unobserved field is a wrong answer.
Both are defended in CODE, not in prose alone (section 7.4).

## 5. Leg 4 and the shaping-gate design - the ordered pipeline

`shape_proposal(raw, *, sites, existing_slugs, known_items, observed_names, existing_fields) -> DataPlaneOutcome`.

Every gate is a pure function of value in, narrowed value out, with no I/O, exactly as `assigner.shape_proposal` and `mechanism_typist.narrow_to_typing` are.

| # | Gate | What it does | Why it sits here |
|---|---|---|---|
| 1 | `narrow_to_data` | keeps the four data lists, empties `services`, `systems`, `aggregates`, `system_edges` | FIRST, because every count downstream is a count of data deltas, and because a stray `services` or `aggregates` list reaching the curator would restore Service minting (#34 D4) and double-write assignment |
| 2 | `drop_unknown_relationship_kinds` | keeps `data_relationships` whose `kind` is in `DATA_RELATIONSHIP_KINDS` | before any per-kind accounting; the writer hard-rejects an unknown kind anyway (`l1_curator.py:539-545`), so shaping it out here means the proposer emits only what the writer accepts rather than relying on the guard (the `mechanism_typist.drop_unknown_vocabulary` discipline) |
| 3 | `resolve_surface_refs` | canonicalises each `surfaces_at.l0` to the exact L0 identity shape (Parameter/Header/Secret) and DROPS any naming no admitted site | before groundedness, because a surface ref is what makes an item grounded; see section 5.1 |
| 4 | `drop_out_of_inventory_services` | drops `data_flows` whose `service_slug` is not a live L1 Service, collecting one backlog description per missing slug | before groundedness, because a flow to a Service that does not exist is a reference to nothing rather than weak evidence of grounding; see section 5.2 |
| 5 | `bind_fields_to_observed` | intersects each item's proposed `fields` with the observed vocabulary, unions with the live persisted set, and omits the key when the result is empty | before groundedness, so a fields-only item is not mistaken for a grounded one; see section 5.3 |
| 6 | `enforce_groundedness` | drops every NEW `data_item` with no surviving `surfaces_at` (operator ruling 2026-07-30: a path noun alone never grounds a lift, so the surface site is REQUIRED, not one of two options), and every `data_relationship` whose endpoints are not in (surviving items union the live inventory) | LAST, because it is a function of what survived every earlier gate; see section 5.4 |

**Why the order is load-bearing.**
Gate 6 must run last, and this is the data plane's analogue of the Assigner's "normalisation must precede withholding" (`assigner.py:250-252`).
Gates 3 and 4 are the gates that REMOVE the anchors gate 6 tests for.
Run groundedness before the reference gate and it passes on a `surfaces_at` entry that names a site the chunk never carried, so an item is certified grounded by a reference to nothing - a gate that is vacuous because a prior normalisation did not run, which is exactly the failure class the confidence-rescaling defect belonged to.
Gate 1 must run first for the same reason from the other end: gate 6 counts survivors, and a batch that still carries `aggregates` would have the wrong denominator and would additionally reach a writer that mints.

### 5.1 The reference gate, and the counted-but-false write it defends against

`build_surfaces_at_cypher` opens with `MATCH (l0:<Label> {<identity>, project_id})` (`l1_curator.py:478-496`, via `_l0_match_clause:446`).
A MATCH that finds nothing produces no rows, so the subsequent MERGE never executes and nothing is written.
It also does not raise, so `_write_each` (`l1_curator.py:608-624`) increments `written` regardless.

Two consequences, both material.

First, a `surfaces_at` proposal whose identity the model shaped its own way is silently discarded, and `enrich()` REPORTS it as written.
This is the same defect class as the `l0.label` failure that wrote zero of 114 sound assignments (`assigner.py:171-186`) - correctness must not depend on the model's formatting - so it gets the same treatment: repaired in the shaping seam, not instructed and hoped for.
The gate rewrites each ref into the exact shape from `l0_stream.L0_IDENTITY_KEYS` (`Parameter{name, position, endpoint_path, baseurl}`, `Header{name, value, baseurl}`) by matching against the assets the chunk actually streamed, keyed on the parts a model reliably gets right (the parameter or header `name`, then the `endpoint_path` or `baseurl`), and drops what it cannot place.

Second, the `enrich()` return value is not a trustworthy count of `surfaces_at` writes, and therefore not a trustworthy input to `WriteCounts.enrichment` or to `PassCensus`.
The authoritative count of what this agent produced is its own census (section 8), which counts what it KEPT after the reference gate resolved every ref to a site it had seen.
The `_write_each` over-count is a defect in the sole-writer that this spec does not fix (open question 5).

### 5.2 The validation gate, and why the data path could restore minting

`build_data_flow_cypher` opens `MERGE (s:L1TestableUnit:L1Service {business_function_slug: $slug, project_id: $project_id}) ON CREATE SET s.prov_job = ...` (`l1_curator.py:512-514`).
It MERGEs the Service, with provenance-on-mint.
So a `data_flow` naming a slug that does not exist CREATES a Service.

#34 D4 retired Service minting from the Assigner because a chunk-local mint competes with the Bootstrapper's whole-architecture read and is the measured origin of cross-run identity drift (AMV-12).
Dispatching a data_modeller that does not validate `service_slug` would restore exactly that minting through the data path, one increment after it was removed, and `supervisor._aggregates_write_fn`'s stated care ("a writer that could create Services would quietly restore the minting path the ticket removed", `supervisor.py:620-625`) would be defeated on the very next role.
So the validation gate is not a parity nicety; it is what keeps #34 D4 true.

Its shape mirrors `assigner.drop_out_of_inventory` verbatim: drop the delta, keep the reach as ONE short backlog sentence naming the candidate slug inline.
`build_data_relationship_cypher` (`l1_curator.py:552-556`) MERGEs both DataItems the same way, which is why gate 6 covers relationship endpoints too.

### 5.3 The observed-only `fields` gate

The observed vocabulary for a chunk is the set of names the agent could actually have observed: the `name` of every admitted `Parameter` and `Header`, plus any non-identity keys those assets carry in `props`.
`bind_fields_to_observed` intersects each proposed `fields` list with that set, then UNIONS the result with the item's already-persisted `fields`, and omits the `fields` key entirely when nothing survives.
Every dropped name is counted.

The union half is not defensive, it is required.
`build_dataitem_cypher` writes `SET d += $props` (`l1_curator.py:471`), which replaces the `fields` key wholesale.
Under streamed, chunk-by-chunk analysis, an item that gained `["ProductId"]` from chunk 1 and is re-proposed from chunk 5 with `["quantity"]` would LOSE `ProductId`, so the observed field set would shrink as the run progressed and the graph would end up recording less than was observed.
Reading the persisted set live and emitting the superset is the same compounding discipline the mechanism-typist applies to a System `description` (`CONTEXT.md`, *System description*), and for the same reason: this agent is the sole incremental author of the attribute, so compounding is correct and clobbering is a bug.

The prompt also instructs observed-only (section 7), and both are needed: the gate makes it a contract, the prose makes the model produce something worth gating.
This is the "enforced, not merely instructed" leg #10's required edit 3 asks for, discharged.

### 5.4 Groundedness: a surface site is the per-chunk bar; the flow is a graph-level predicate

Ratified 2026-07-30, correcting this document's original draft (which proposed surface-OR-flow).
The operator's argument: a path noun (`/api/BasketItems`) tells you an endpoint is ABOUT a record, but a path is the address you interrogate, never a place data appears - `SURFACES_AT` is defined as where a logical item is OBSERVED on the surface, so a flow with no observed datum backing it is an inference wearing the shape of evidence.
So the per-chunk gate requires at least one surviving `surfaces_at` for every NEW item; there is no flow-only path to survival.
An item already in the live inventory is not re-tested, because it was grounded when it was written.

T1's requirement is the strict conjunction (`>= 1 SURFACES_AT` AND `>= 1` flow).
Enforcing the flow half per chunk would be wrong under streaming for the reason the original draft gave: an item's surface site and its producing Service can legitimately arrive in different chunks, because the Service side depends on the Assigner having settled ownership, which it may WITHHOLD by design.
So the flow half of the conjunction is a GRAPH-LEVEL acceptance predicate, checked by the assertion catalogue and later by the Auditor and A.2; the surface-site half is enforced per chunk because it is the one epistemically REQUIRED half - the datum a tester can act on - while the flow half is enforced weakly (deferred) because ownership settling is out of this agent's control and asynchronous with its own pass.

## 6. Leg 5 - context (the live reads)

Every read happens at DISPATCH time and nothing is frozen onto the chunk.
The chunk carries the immutable L0 delta and no L1 context (`chunking.Chunk` docstring), so a frozen read would mean chunk N+1 could not see what chunk N wrote - the stale-context defect that rotted curation (#13 section 4).

| Read | Source | Used for |
|---|---|---|
| L1 inventory | `l1_inventory.read_l1_inventory(project_id)` | the un-truncated identities block (`data_items` for reuse-first identity), the `services` validation set for gate 4, the known-items set for gate 6 |
| DataItem observed fields | the SAME read, extended additively with `data_item_fields: {item_key: [field, ...]}` | the union half of gate 5 |
| DataItem notes | the SAME read, extended additively with `data_item_notes: {item_key: notes}` | the reuse-or-coin decision in the reflection prompt |
| Service to L0 aggregations | `l1_read.read_service_aggregations(project_id)` | the candidate owning Services per admitted asset |
| Admitted assets | `chunking.admit_for_role(chunk, "data_modeller")` over `ROLE_ADMITS["data_modeller"] = {Parameter, Header, Secret}` | the surface itself, the reference-gate site index, the observed vocabulary |
| Observations | `chunk.observations`, attached by ORIGIN | the adversarial insight block |

**Admission widened to include `Secret` (ratified 2026-07-30).**
#10's own responsibility statement names "parameters/headers/secrets/HTML" as the lift surface; the pre-grilling draft of this document admitted only `{Parameter, Header}`.
A jsluice-mined `Secret` (identity `{value_hash}`, props `{kind, source, redacted: True}`) is Tier-1 trust substrate - a hardcoded credential is exactly the kind of record this agent exists to surface.
`l0_stream.L0_IDENTITY_KEYS` gains `"Secret": ("value_hash",)` so the reference gate can canonicalise a `surfaces_at` targeting one, mirroring the existing `Parameter`/`Header` rows.
HTML form fields carry no separate L0 label - they arrive as ordinary `Parameter` nodes through the crawl path - so the prompt names this explicitly rather than the admission table changing again.

**The httpx-profile gate is DROPPED, not consumed (ratified 2026-07-30, reverses this document's original DPL-DEC-19/section-8 framing of `Chunk.flagged` as something to consume).**
The operator's argument, verified against the code: `#34 D1` already dropped this identical gate for `Endpoint`, on the grounds that withholding un-profiled surface makes a never-profiled target indistinguishable from an empty one (AMV-14); the same argument applies to `Parameter` and was never mirrored onto it.
Separately, and independently: `#28` (per-endpoint profiling) made `Endpoint.profile` the authoritative per-endpoint signal and demoted `BaseURL.profile` to "exists only for backward compatibility" (`docs/design/per-endpoint-profiling-spec.md`) - but `#28`'s code never reached `dev` (filed as `#47`), so the ONLY profile signal live in this codebase today is the coarse, sometimes-wrong `BaseURL.profile` mirror the gate was already reading.
So the gate is dropped entirely rather than repaired: `chunking._gate`, `chunking._GATED_TYPES`, `chunking.profiled_origins`, `chunking._HAS_PROFILE`, the `barrier` parameter threading through `chunks_for_job`/`analyse_chunked`, and the `Chunk.flagged` field are ALL removed as part of this ticket, because with both gated types (`Endpoint` via `#34 D1`, `Parameter` via this decision) gone, `_GATED_TYPES` is empty and the whole apparatus is permanently unreachable - a dormant seam with no plausible future caller, which `CODING_STANDARD.md` section 12 says should not be left to rot silently.
This does NOT touch `ROLE_ADMITS`/`admit_for_role` - the per-agent type-narrowing mechanism is a separate, later stage over an already-built chunk, and is unaffected.
Profile classification is consequently absent from this agent's prompt context entirely; the candidate-owning-Service join (below) is the sole interpretive signal a Parameter's origin gets.

The inventory extension follows the ratified additive pattern twice already used: `service_contracts` for #29 and `system_descriptions` for #9 (`l1_inventory.py:53-66`).
The flat `data_items` list is unchanged, so no existing consumer of the inventory sees a difference.

**Candidate owning Services.**
A new pure helper `owning_services(admitted, aggregations) -> dict[asset_ref, list[slug]]` joins each admitted asset to the Services that aggregate the Endpoint it hangs off.

- A `Parameter` joins on `identity["endpoint_path"] == row.props["path"]` and `identity["baseurl"] == row.props["baseurl"]`, over the rows whose L0 labels include `Endpoint`.
- A `Header` has no endpoint in its identity (`{name, value, baseurl}`), so it joins on `baseurl` alone and yields every Service owning any Endpoint on that origin.

The header join is deliberately coarse and is stated as such in the prompt, because a response header IS origin-scoped rather than endpoint-scoped; pretending otherwise would manufacture precision the surface does not carry.
The prompt presents these candidates as the ONLY permitted values for `data_flows.service_slug`, and gate 4 enforces membership in the live inventory regardless of what the model returns.

**Observations attach by origin, not by exact identity.**
`curator.ANCHOR_ALLOWLIST = {Domain, Subdomain, BaseURL, IP, Service}` (`recon/domain/curator.py:41`), so a triager `Observation` is NEVER anchored to a `Parameter`, `Header` or `Endpoint` - the triager re-anchors a finding UP to the owning broad asset by design.
`chunking._observations_for` matches an observation's anchor against the chunk's asset keys by exact `(type, identity)` (`chunking.py:167-176`).
It follows that an observation can never pair with a `Parameter` or a `Header` by exact identity, so the per-asset pairing render the mechanism-typist uses (`mechanism_typist._asset_observation_paragraphs`) cannot attach insight to a narrow asset at all.
The data_modeller therefore renders observations as an ORIGIN-scoped context block: the insights anchored to a chunk's BaseURL, Domain, Subdomain, IP or Service assets are presented as context for every admitted asset on that origin.
The typist's per-asset pairing being near-vacuous by construction is a separate defect, reported rather than fixed here (open question 6).

## 7. Leg 6, the output template, and the prompt design

### 7.1 The typed output

`L1DeltaBatch{data_items, surfaces_at, data_flows, data_relationships}`, with `services`, `systems`, `aggregates` and `system_edges` structurally empty.
The four proposal shapes are reused UNCHANGED from `analyser_types.py:67-101`; this ticket adds no proposal type and no writer.
The batch reaches the graph through `enrichment_proposals_to_deltas` then `l1_curator.enrich`, which is #10's required edit 6 discharged: no new writer, no catalogue seeding (the `DataRelationshipKind` catalogue was removed by the 2026-07-20 operator correction).

The body returns `DataPlaneOutcome{batch, backlog, stats}` internally, and the supervisor adapter returns `outcome.batch`, mirroring `assigner.AssignmentOutcome` and `make_assigner_body`.

### 7.2 The two-layer system message

Layer 1, in code, `_ROLE_VERBATIM`: the WHAT.
Identity, the four-list output contract, the reference shape for a `surfaces_at` target, the permitted relationship kinds, and the rule that `service_slug` is copied verbatim from the candidate list.
It must hold with no skills mount at all.

Layer 2, from the filesystem, `skills/analysis/data-plane/SKILL.md`: the HOW.
Its frontmatter names the same synthesis the typist's does, verbatim in form: *"Synthesises `overthink` (staged deliberate reasoning), `critical-thinking-logical-reasoning` (claims/evidence/assumptions/fallacies), and `define-hypothesis`/`debug-hypothesis` (frame a business-record hypothesis, then verify it) for the task of lifting the Tier-1 logical DataItems a streamed surface evidences and grounding their flows onto the settled Service model."*
The file's body is section 7.3's six-step scaffold plus section 7.3a's critical-judgment discipline plus section 7.5's worked examples, in that order - the same three-part shape (reason-by-hypothesis, judge-critically, worked-examples) as `skills/analysis/technical-system/SKILL.md`.
Loaded through `skill_for("analysis/data-plane", fallback=_DATA_PLANE_SKILL_FALLBACK)`, single-sourced, YAML frontmatter stripped, cached in process, never an inline prompt constant - the #30 per-role retirement, on the Assigner's and Bootstrapper's precedent (`assigner.py:403-445`).
The in-process cache is what preserves the provider prompt-cache prefix: the file is read once per process, so the system message is byte-identical for every chunk of a run.

The fallback is a degraded stand-in used only when the mount is unavailable, and it must not degrade to silence.
It carries the load-bearing core: a business record is not a parameter, `fields` name only what was observed, reuse an existing `item_key` before coining one, and a parameter that witnesses no record is correctly left alone.
Every HARD invariant survives a missing mount regardless, because narrow, resolve, validate, bind and ground are code.

**Volatility split.**
The system message is stable across the whole run.
The volatile material rides the human message of each call: the un-truncated identities block FIRST (the FR-INVENTORY discipline, `pod._inventory_block`), then the candidate-owner list, then the rendered surface, then the origin-scoped observation block.
The inventory stays on the volatile side deliberately, because it mutates as the run proceeds, so hoisting it into the cacheable prefix would invalidate that prefix at every step and buy nothing (`assigner.py:487-494`).

### 7.3 The reasoning scaffold (call 1, free prose) - hypothesis-driven, redesigned 2026-07-30

**This section was rewritten after the operator identified that the original 7-step scaffold was a linear checklist, not a hypothesis-driven reasoning chain, and did not integrate `overthink`/`debug-hypothesis` primitives the way the mechanism-typist's does.**
The typist's `SKILL.md` names its synthesis explicitly - `overthink` (staged deliberate reasoning) + `critical-thinking-logical-reasoning` (claim/evidence/assumption separation) + `define-hypothesis`/`debug-hypothesis` (frame a hypothesis, then falsify it) - and its shape is: hold MULTIPLE competing hypotheses, falsify against evidence, then integrate the survivor, with a SEPARATE "judge critically" section outside the staged reflection (`skills/analysis/technical-system/SKILL.md`).
The original draft here never asked the model to hold competing candidate records for one ambiguous name, never stated the null hypothesis ("this witnesses no business record at all") as a first-class candidate rather than a late fallback, and never separated a claim from its evidentiary support the way the typist's step 3 does - it is the identical gap `debug-hypothesis`'s Phase 2 names against "I only have one theory" ("You have one *favorite* theory. Think harder.").

Rendered with `proposer_reasoning.role_header` and `proposer_reasoning.cot_scaffold`, the shared fragments the pattern exists to supply.

1. **ORIENT.** Read each admitted Parameter and Header together with the endpoint path it hangs off and the adversarial insight for its origin; say what the surface alone tells you before you look at the known items.
2. **HYPOTHESISE** (`define-hypothesis`). For each admitted name, state candidate hypotheses of the form *"this name witnesses business record R"*. For an ambiguous name (`id`, `token`, `ref`), hold MORE THAN ONE candidate record before committing - and state *"this witnesses no business record"* as one candidate among them, explicitly, never an unstated default reached only if nothing else fits.
3. **VERIFY / FALSIFY** (`debug-hypothesis` + critical-thinking). Test each hypothesis against the evidence actually present. Separate the claim ("this parameter witnesses record R") from its support (the exact name, the exact path, the exact endpoint it hangs off). A name that merely sounds like a record with no path or field corroboration is topical proximity, not evidence - reject it, the same discriminating-evidence-vs-topical-proximity test the Assigner's skill already teaches for ownership. Decide REUSE-vs-COIN here, against the currently-known DataItems, their observed fields and their notes: identity-matching against known items is part of verification, not a separate step, and an existing `item_key` with matching notes/fields wins over minting a synonym (the same "read what exists before you commit" ordering the Assigner's skill enforces for a different reason - `skills/analysis/assigner/SKILL.md:24-25` - applied verbatim to item keys).
4. **INTEGRATE.** Fold the origin's adversarial insight into the surviving record's `notes` - what it is, whose trust it carries, what breaks (the adversarial-characterisation-only scope ratified in DPL-DEC-09: no named payload, no named vector).
5. **SHAPE.** For each verified record, three sub-judgments, each a low-risk transcription of what verification already settled rather than a fresh hypothesis to test - folded into one step deliberately, on the operator's 2026-07-30 compression of an earlier 8-step draft:
   - *Ground:* name the exact surface site(s) it appears at, and which Service produces it and which consumes it, choosing service slugs only from the candidate list you were given.
   - *Trust:* for a `consumes` whose producing Service differs from the consuming Service, state the falsifiable predicate the consumer holds about that data, in one surface-readable sentence.
   - *Relate:* only where the surface itself shows it, state a record-to-record dependency using one of the allowed kinds, with a shallow predicate.
6. **EMIT / WITHHOLD.** Report the verified records. Name what you FALSIFIED and why - a pagination cursor, a CSRF token, a framework header - so withholding is the loop's demonstrated conclusion, not an assumed default. This exists because the measured over-assignment prior says a model does not withhold unprompted, and the data plane's equivalent of over-assignment is lifting technical parameters as though they were business records.

### 7.3a Judge each proposal critically (separate from the staged reflection, mirrors the typist's SKILL.md structure)

Added 2026-07-30, on the same precedent: the typist's skill keeps this OUTSIDE its five-step reflection, as a standing discipline the model applies throughout rather than a step it passes once.

- **Evidence sufficiency.** Would this name fit two or three other candidate records equally well? Non-discriminating evidence is a reason to withhold, not to guess.
- **Surface hidden assumptions.** What must hold for this record to genuinely be produced by one Service and consumed by another? If unverified, say so rather than asserting the flow.
- **No unsupported leaps.** One observed field name does not license an inferred schema of fields you have not seen; do not assume a flow direction the surface does not evidence.
- **Compounding, not clobbering.** When a record is REUSED, its `notes` and `fields` both GROW - fold new insight in, never blank or merely restate what is already known (mirrors the typist's System-`description` discipline and is enforced in code for `fields` by gate 5's live union, DPL-DEC-07/08; `notes` compounding is prose-only, table 7.4).

### 7.4 Which invariants are code and which are prose

This table is the honest statement of where the design relies on instruction, and it is the answer to "an instruction relied upon where code could enforce the invariant instead".

| Invariant | Enforced by | Note |
|---|---|---|
| output carries the four data lists only | CODE, `narrow_to_data` | |
| relationship `kind` is allowlisted | CODE, gate 2, plus the writer's hard reject | |
| a `surfaces_at` target is a site the agent was actually shown | CODE, gate 3 | |
| a `data_flow` names a live Service | CODE, gate 4 | keeps #34 D4 true |
| `fields` are observed-only | CODE, gate 5 | #10 required edit 3 |
| `fields` never shrink across chunks | CODE, gate 5's live union | |
| every emitted item is grounded | CODE, gate 6 | weak per batch, strict per graph |
| provenance and identity keys | CODE, `enrichment_proposals_to_deltas` and `l1_curator` | structurally forbidden to the proposer |
| an existing `item_key` is REUSED rather than paraphrased | PROSE ONLY | DP-1 is deliberately open: no normalising key rule, cross-service same-logical-item merge is the Anti-cluttering cleaner's ratified job (#11, T2 D5) |
| trust assumptions stay SHALLOW and surface-readable | PROSE ONLY | DP-2; verified predicates are Phase B |
| a DataRelationship predicate stays shallow | PROSE ONLY | DP-3; hardened invariants are Phase B |
| a business record is distinguished from a technical parameter | PROSE ONLY | irreducibly a judgment; this is what the worked examples teach |

### 7.5 Worked examples - rewritten 2026-07-30 to demonstrate the hypothesis loop itself

At least six, in divergent domains, each showing the ORIENT-HYPOTHESISE-VERIFY/FALSIFY shape rather than a domain answer, on the mechanism-typist's discipline ("imitate the REASONING SHAPE, never the domain").
The example keys are deliberately unlike anything a real inventory holds, because an example sharing a key with a live identity invites the model to echo the example's answer as a judgment (`assigner.py:376-378`).
Every example now names its HELD hypotheses explicitly, not only its final answer, on the typist's `Example 3` precedent (hold CDN and WAF, then let evidence pick) - a worked example that shows only the winning answer teaches pattern-matching, not the loop.

1. **Ambiguous name, multiple candidates, evidence decides (the load-bearing one - this is what the redesign exists to teach).** Parameter `ref` on `POST /api/checkout/apply`. Hypothesise: candidate A - witnesses a `coupon_code` record (checkout context supports it); candidate B - witnesses an `order_reference` record (equally plausible from the name alone); candidate C - witnesses no business record (a generic tracking token). Verify: the endpoint path `apply` and the sibling parameter `discount_amount` in the same call corroborate A specifically; nothing corroborates B beyond the name; C is now the weakest reading. -> lift ONE item, `coupon`, with the rejected hypotheses B and C stated as falsified, not silently dropped.
2. **The explicit null hypothesis, upheld.** Parameter `_csrf` on every POST body. Hypothesise: candidate A - witnesses a business record; candidate B (the null hypothesis, stated up front) - witnesses no business record, a framework anti-forgery token. Verify: no path, no sibling field, no observation corroborates A; the name and its presence on every mutating endpoint are exactly the CSRF-token signature. -> B wins; nothing is lifted; this is stated as a falsified hypothesis, not an unexamined skip.
3. **Grounding, trust and a shallow relate, in one SHAPE step.** Verified record `shopping_basket`, surfacing at `Parameter{quantity, /api/basket}` and `Parameter{productId, /api/basket}`, candidate owners `{cart, catalogue}`. Ground: `cart` produces it (owns `/api/basket`); `catalogue` consumes it (owns `/api/products/{id}` which the basket references). Trust: `catalogue` holds the assumption "the referenced productId is a catalogue item cart does not itself validate". Relate: `shopping_basket` `derived_from` `product_listing`, predicate "line item derived from a listed product", because the surface itself shows the productId reference.
4. **A HEADER-sourced item (DP-4), contrasted with a fingerprint-only header.** `Header{Authorization, /api/*}` carries a bearer value. Hypothesise: candidate A - witnesses a `session_principal` record; candidate B - witnesses no record, a mechanism-typist concern (evidence of an auth MECHANISM, not a business record). Verify: the header's VALUE is the principal's own credential, present on every authenticated call - A is supported; the mechanism itself (which scheme, which realm) is out of scope for this role and stays the typist's via `EVIDENCED_BY`. -> lift `session_principal`, surfacing at the Header; do not attempt to characterise the auth mechanism.
5. **Reuse over paraphrase, against a known-items block.** Known items include `shopping_basket :: client-supplied quantity and product reference; server may trust submitted quantity without revalidation`. New surface this chunk: `Parameter{qty, /api/cart/items}`. Hypothesise: candidate A - a NEW record (different endpoint, different field name); candidate B - the SAME record as the known `shopping_basket`, reached via a second endpoint. Verify: `qty` and `quantity` are the same field under a different name, and `/api/cart/items` and `/api/basket` plausibly serve the same function - reuse `shopping_basket`'s exact `item_key`, compound its `fields` and `notes` rather than minting `cart_item` as a paraphrase.
6. **Observed-only `fields`, an obviously-plausible field OMITTED.** Verified record `product_listing`, observed fields `{productId, name}` from the surface actually shown. A third field, `price`, is highly plausible for a product listing but was not observed anywhere in this chunk. -> `fields: [productId, name]`; `price` is not written, and the reason is stated: plausibility is not observation.

Examples 1 and 2 are the load-bearing ones: they demonstrate the multi-hypothesis and null-hypothesis moments the redesign exists to teach, and neither can be taught by a prohibition or by showing only a final answer.

### 7.6 Positive framing, and why there is no leave-empty litany

The prompt states what to FILL and that an empty answer is wrong when the reflection named a record.
It does NOT carry a "leave services, systems, aggregates and system_edges EMPTY" litany.

The evidence is twice-recorded and points the same way: the legacy data prompt's negative framing made a weaker analyser anchor on the empties and return zero `data_items` (`pod.py:330-335`), and the typist's extraction call reproduced the identical failure until it was reframed positively (`mechanism_typist.py:227-230`, "reflection named 5 mechanisms, extraction returned 0 systems").
Because gate 1 structurally removes the other lists, the prohibition buys nothing and costs the failure mode.
This is the code-enforces-so-prose-need-not-prohibit split, applied deliberately.

## 8. Leg 7, produced outcome, and Leg 8's foundation - the per-chunk census

### 8.1 Produced outcome

In the graph, per chunk: `:L1DataItem` nodes MERGEd on `(project_id, item_key)`; `SURFACES_AT` edges from those items down to L0 `Parameter` and `Header` nodes, MATCHed never MERGEd (the anti-corruption boundary); `PRODUCES` and `CONSUMES` edges from live `:L1Service` nodes to those items, a `CONSUMES` optionally carrying `assumption` and `assumption_rationale`; and typed `DataItem` to `DataItem` edges whose type is the uppercased allowlisted kind.

In the run: a `StepReceipt` with real `WriteCounts.enrichment`, and the census below.

### 8.2 `DataPlaneStats`

A frozen model, one instance per chunk, and the direct analogue of `AssignmentStats` whose docstring states the rationale: "a run proposed 114 sound assignments and wrote zero, and NOTHING in the system said so ... without a count per gate an empty result is indistinguishable between the model found nothing and every judgment was discarded on the way out" (`assigner.py:54-59`).
Every gate in section 5 is fail-open, so every one of them needs its own counter.
The mechanism-typist has NO census, and its `drop_unknown_vocabulary` is a silent fail-open drop; that divergence is a gap in the sibling, not a precedent to copy (section 10).

Input side:

- `admitted_parameters`, `admitted_headers` - what this role was given.
- `flagged_chunk` - the barrier fail-open flag was set on this chunk.
- `observations_attached` - origin-scoped insights rendered.
- `candidate_services` - distinct slugs offered as flow targets.

Generation side:

- `reflection_exhausted` - the fail-CLOSED marker; a true here explains a zero result entirely.
- `extraction_exhausted` - the second call produced no parseable output.
- `proposed_items`, `proposed_surfaces`, `proposed_flows`, `proposed_relationships`.

Gate side, one counter per fail-open drop:

- `unknown_kind_dropped` (gate 2).
- `unresolvable_surfaces` (gate 3) - named no site this chunk carried.
- `out_of_inventory_flows` (gate 4) - named no live Service.
- `fields_proposed`, `fields_unobserved_dropped`, `fields_carried_forward` (gate 5).
- `ungrounded_items_dropped`, `orphan_relationships_dropped` (gate 6).

Output side:

- `kept_items`, `kept_surfaces`, `kept_flows`, `kept_relationships`.
- `reused_item_keys`, `new_item_keys` - the identity-drift signal DP-1 leaves to prompt and cleaner, made observable so the openness is measurable rather than merely declared.
- `backlog` - carried, not transported (#34 D6 parity: `ProposalEnvelope` still has no field for it).

One structured log line per chunk, in the Assigner's exact style, so a zero-kept step names its cause instead of looking identical to a model that found nothing.

`supervisor.PassCensus` gains `data_items_written`, alongside `aggregates_written` and `systems_written`, for the same reason those two exist: the pass must report what it OBSERVED, not merely that it ran.

## 9. Leg 8 - observability

Concrete identifiers, consistent with what `_observability_config` and `analyse_chunked`'s `observe_metadata` already do (`supervisor.py:274-287`, `578-599`) and with #6's ratified v4 recipe.

**Span name: `data_modeller`.**
This CORRECTS #10's observability leg, which named a verb-first span `analyse-data-plane`.
Langfuse v4 names an agent span from the LangGraph node name, and `build_supervisor_graph` adds one node per role using the role literal as the node name (`supervisor.py:240-241`), while the supervisor routes with `Command(goto=role)`.
The span name and the routing key are therefore the same string, so a verb-first span name is not available without changing the routing keys.
`analyse-data-plane` becomes a TAG instead.

**Tags.** `langfuse_tags` in `analyse_chunked`'s `observe_metadata` gains `"data_modeller"` and `"analyse-data-plane"`, beside the existing `["analyser", "supervisor", "assigner", "mechanism_typist", "chunked"]`.

**Session.** Unchanged and already correct: `langfuse_session_id = run_id.removeprefix("stream-")`, so recon and analysis land on one timeline.

**Metadata.** `observe_metadata` gains `admitted_parameters` and `admitted_headers`, summed over chunks with `admit_for_role`, exactly as `admitted_endpoints` already is.
The rationale is the one already recorded in place: "the chunk shape IS the diagnosis when a step writes nothing, so it rides the trace rather than living only in the container log".

**Scores: designed-not-built.**
#10's leg named a NUMERIC data-coverage score, and #6 documents `create_score`.
This spec does NOT write one, for two reasons.
First, nothing in this codebase writes a Langfuse score today (no `create_score` call exists), so it is new machinery rather than consistency with the existing pattern.
Second, and decisively, #34 AST-DEC-09 assessed Langfuse for exactly this role and REJECTED it: it is fail-open, optional, and drops span batches under precisely the latency stress a stall produces, so a measurement built on it is silently vacuous in the failing case (`supervisor.py:413-421`).
The authoritative measurement is `DataPlaneStats` plus `PassCensus` plus the eval adapter of section 9.1; the score belongs to the cross-cutting observability ticket, and the seam is named here rather than half-built.

### 9.1 The comparative measurement

`evaluation.py` gains `read_data_plane(project_id)` and `data_plane_metrics(census)`, on the `read_assignment` / `assignment_metrics` pattern (`evaluation.py:372-454`), plus an `evaluate_data_plane` adapter that MEASURES completed runs rather than driving its own, for the reason `evaluate_assigner` already states: a data-plane arm needs a real recon surface and a bootstrapped inventory underneath it, so a run costs a full pipeline.

Primary axis, judged comparatively and never against a threshold: `n_data_items`.
Integrity columns travelling in the same row, because an arm can buy item count by losing something else: `grounded_rate` (items with both a `SURFACES_AT` and a flow, over all items), `surfaces_per_item`, `flows_per_item`, `fields_coverage`, `ungrounded_drop_rate`, `unresolvable_surface_rate`, `out_of_inventory_flow_rate`, `reuse_rate`.
`read_data_plane` counts with INDEPENDENT subqueries, for the reason recorded at `evaluation.py:422-425`: a chained MATCH drops the whole row when a project has parameters but no DataItems yet, hiding the exact state - total non-modelling - that most needs to be seen.

This harness is what makes the default prompt arrangement measurable, and it is why this role ships without an env-selected prompt arm (DPL-DEC-17).

## 10. Verifying the operator's note about the sibling precedent

The operator's note was that the mechanism-typist's contracts follow the same patterns as the Assigner's, to be verified rather than assumed.
Verified against both files: the claim holds for the supervisor-facing protocol and fails in four places, each of which forces a choice here.

1. **Body shape differs.** The Assigner exposes a FACTORY, `make_assigner_body(*, invoke_fn, inventory_fn, bar)` returning a closure. The typist exposes a FUNCTION with keyword collaborators, `mechanism_typist_body(dispatch, state, *, invoke_fn, read_inventory, read_aggregations)`, adapted at the call site with `functools.partial` (`supervisor.py:571`). Chosen here: the factory, because it binds every collaborator in one place and keeps the dispatch-time read explicit.
2. **Retry helper differs.** The Assigner uses `pod._invoke_with_retry`; the typist uses `proposer_reasoning.bounded_retry`. Two helpers do one job. Chosen here: `bounded_retry`, the shared documented one, whose docstring already records the multiplication with the client's own retries.
3. **Invoke signature differs.** The Assigner's is `(messages) -> batch`; the typist's is `(messages, *, schema) -> prose | batch`. They cannot share one injected callable, which is why `analyse_chunked` carries a separate `typist_invoke_fn` (`supervisor.py:564-571`). Chosen here: the typist's signature, and therefore a third seam, `data_modeller_invoke_fn`.
4. **Census is absent from the typist.** The Assigner has `AssignmentStats`; the typist has none, though `drop_unknown_vocabulary` is a silent fail-open drop and its `_merge_systems` repair exists because five well-described Systems were being thrown away unobserved. Chosen here: the Assigner's discipline, in full (section 8), and the typist's missing census recorded as a work item.
5. **Phase guard is present in the typist only.** The typist returns `None` for `phase != "A1"`; the Assigner does not check. Chosen here: the typist's guard, because it IS the A.2 scaffold seam.

## 11. The dissolution plan - an ordered sequence of individually safe steps

The starting state, established by reading the code rather than the tickets: `run_analyser` routes to `run_analyser_chunked` when `analysis.supervisor_enabled` is ON, and to the legacy pod graph when it is OFF, which is still the default (`pod.py:539-557`).
`run_analyser_supervised` - the legacy wrapper #42 names - is already off the production path; its only consumer is `tests/e2e/test_async_scaffold_walkthrough.py`.
So #42's item 3 is largely already discharged by #34, and what actually remains is the data_modeller, the write routing, and the retirement of the legacy two-pass.

**Step 0. Feed observations into the chunk stream.**
`analyse_chunked` calls `chunks_for_job(pseudo_job, assets, profiled=profiled, barrier=True)` with no observations (`supervisor.py:531`), so `Chunk.observations` is ALWAYS empty on the live path and the project's Observations reach no proposer - independently found and recorded as D9 in `recon-analysis-decoupling-review.md`.
This must be fixed before the data_modeller is dispatched, because #34 D5's promise is that observations reach the mechanism-typist and the data-modeller.
It is not a one-line thread: `delivery.collect_observations` projects Observations to dicts over `_OBS_FIELDS` and DROPS the anchor entirely (`delivery.py:29`), while `chunking._observations_for` needs `recon.domain.types.Observation` values with an `anchor`.
So the step is a new read in `l0_stream` returning `Observation` values with their anchors reconstructed, threaded into `chunks_for_job`.
Individually safe: the typist already renders observations and today gets none, so the only possible change is more context, never less.

**Step 1. Extend the inventory additively.**
`read_l1_inventory` gains `data_item_fields` and `data_item_notes`.
Individually safe by the twice-used additive precedent: the existing keys and their shapes are untouched, so no current consumer changes.

**Step 2. Build `analysis/data_modeller.py` standalone, unregistered.**
Gates, prompts, census, body, factory.
Individually safe: no caller exists, so nothing changes at runtime.

**Step 3. Write `skills/analysis/data-plane/SKILL.md`.**
Individually safe: a new file with one consumer, which is already written and not yet dispatched.

**Step 4. Dispatch, and fix the write routing.**
Register `proposer_bodies["data_modeller"]`, extend `build_schedule(..., roles=("assigner", "mechanism_typist", "data_modeller"))`, and add the data branch to `_chunked_write_fn`.

The routing fix is not optional and is a latent defect today.
`_chunked_write_fn` routes `if deltas.systems or deltas.system_edges` to the full enrichment curate and EVERYTHING ELSE to `_aggregates_write_fn` (`supervisor.py:634-646`).
A data-only batch has neither `systems` nor `system_edges`, so it would fall through to the aggregates-only writer and be SILENTLY DROPPED - every judgment discarded on the way out, with a `written` receipt.
The minimal correct fix reuses the existing writer rather than adding one: widen the condition to include any non-empty data list, so a data-only batch reaches `default_curate_with_enrichment_fn`, whose `proposals_to_deltas` half is a no-op for empty `services` and `systems` and whose `enrich` half writes the data.
This is #42's item 4 discharged.
Individually safe, and this is the step at which data first reaches the graph, so it lands together with steps 2 and 3.

**Step 5. Flip `analysis.supervisor_enabled` to default ON, then retire the legacy data pass.**
RATIFIED 2026-07-30: the operator's ruling is to flip the flag AND dissolve the monolith together, in this ticket - not the phased "steps 0-4 now, flag-flip-and-retirement later" path this document originally recommended.
So the flag flip happens FIRST within this step (making the chunk-fed three-role schedule the default production path), and only then is it safe to delete `_data_modelling_prompt`, `_compact_l0_for_data`, and the data-list merge in `_two_pass_analyse` (`pod.py:290-370`, `424-430` - #10's required edits 1 and 4), because nothing still-serving-traffic depends on them once the flip has landed.
The ordering within this step is still load-bearing even though it is no longer gated on a separate decision: flip before delete, never the reverse, or there is a window where the default path has neither.

**Step 6. Retire the monolith.**
`_two_pass_analyse`, `_assignment_prompt`, `_load_analyser_skill`, `_ANALYSER_SYSTEM_PROMPT`, `_L0_REFERENCE_GUIDE`, `_SYSTEM_FACTS_ARE_EDGES_RULE`, `default_analyse_fn`, `build_analyser_graph`, `analyser_graph`, and `run_analyser_supervised`.
With `_load_analyser_skill`'s removal, `skills/analysis/analyser/SKILL.md` loses its last consumer and is retired, which is #30's progressive retirement completed rather than a big-bang delete.
`_MAX_L0_NODES` and the truncation inside `_slice_repr` are retired too, which is #10's required edit 2: this is a PROVABLE no-op on the surviving path, because a chunk is bounded at `CHUNK_MAX_ASSETS = 100` and the cap was 400, so the truncation branch cannot fire.

What survives in `pod.py`, with live consumers named: `AnalyserExport` (broadly), `default_read_fn` (`l0_stream`), `_inventory_block` (`bootstrap`, `assigner`, and now `data_modeller`), `_slice_repr` (`assigner`), `_invoke_with_retry` (`sweep`, `curation`, `assigner`), `default_curate_fn` and `default_curate_with_enrichment_fn` (`supervisor`), and `run_analyser`.
The residual module is coherent - the analyser's entry point plus shared prompt-render and write helpers - though it no longer contains a pod; renaming it is churn and is recorded as a note, not done here.

Tests invalidated by steps 5 and 6 are REWRITTEN, never deleted quietly, on the #34 precedent: `tests/analysis/test_analyser_prompts.py` (wholly about the two retired prompts), the two-pass and skill tests in `tests/analysis/test_analyser_pod.py`, `tests/recon/test_skills.py`'s analyser-skill cases, and `tests/e2e/test_async_scaffold_walkthrough.py`, whose subject is the legacy-versus-supervised export parity this ticket deliberately abandons.

**Step 7. Land the glossary and catalogue updates of section 13.**

## 12. The A.2 reuse map, and the designed-not-built seam

A.2 will be the same agent with a different generation and evaluation goal: a batched completeness sweep per user-controllable datum, adding what A.1 missed, with a critical-thinking gap-closing pass.
Reusability is not a design priority for A.1, so this section states what would actually survive the adaptation rather than shaping A.1 around a guess.

**Reusable unchanged - the supervisor contract.**
`AgentDispatch` (role `data_modeller`, phase `A2`), `ProposalEnvelope`, `StepReceipt`, `ProposerBody`.
One concrete seam gap: the dispatch validator requires exactly one of `chunk` or `sweep_cursor` for a non-sliceless role (`messages.py:112-129`), so an A.2 data_modeller must carry a `SweepCursor`, which today is a placeholder holding only `position: int` (`messages.py:49-57`).
That is the one control-plane shape A.2 will have to fill in.

**Reusable unchanged - the sole-writer contract.**
The four `L1DeltaBatch` data lists, `enrichment_proposals_to_deltas`, and `l1_curator.enrich`.
Nothing about the write path is phase-specific, which is why this ticket adds no writer.

**Reusable unchanged - four of six gates.**
`narrow_to_data`, `drop_unknown_relationship_kinds`, `drop_out_of_inventory_services` and `enforce_groundedness` are pure functions of a batch plus a validation set, and A.2 supplies the same kinds of set.

**Reusable with a changed input source - two gates.**
`resolve_surface_refs` and `bind_fields_to_observed` are reusable as functions, but their `sites` and `observed_names` arguments come from the chunk in A.1 and would come from a live per-Service L0 read in A.2.
The seam is the argument, not the function, which is why both take their vocabulary as a parameter rather than reading the chunk themselves.

**Reusable verbatim - most of the meta-reasoning.**
The role verbatim's identity and output-contract paragraph; the observed-only `fields` discipline; the reuse-first identity discipline; the business-record-versus-technical-parameter discrimination; the trust-assumption shape; worked examples 3, 4, 5 and 6.

**NOT reusable.**
The "chunk you were given" framing and the streamed-surface scaffold steps 1 and 2; the candidate-owner derivation (A.2 iterates per Service over the live graph, so ownership is its input rather than a join it computes); worked example 2's non-lift, which is keyed to a streamed slice; the whole per-chunk census input side.

**The seam, marked.**
`data_modeller_body` returns `None` for `dispatch.phase != "A1"`, the typist's exact precedent.
That is an INERT dormant path, not a silent half-implementation, which is what section 12 of `CODING_STANDARD.md` requires.
It is recorded as `designed-not-built` in the module docstring, in this document, and in the `CONTEXT.md` entry of section 13.

## 13. Glossary and catalogue updates owed

These are drafted here and NOT yet written into the glossary, because two of them depend on open questions 2 and 3.
They land with the build, in the same change, per `CLAUDE.md`.

`src/polymerhus/analysis/CONTEXT.md`:

- NEW **DataPlane Analyser / data-modeller**: the sole owner of the Tier-1 data substrate; lifts logical DataItems from streamed Parameter and Header surface, binds them with `SURFACES_AT`, and maps `PRODUCES` / `CONSUMES` flows onto the settled Service model; emits `L1DeltaBatch{data_items, surfaces_at, data_flows, data_relationships}`; A.1 built, A.2 designed-not-built.
- NEW **Ground (the fourth no-edge-is-written mechanism)**: the data plane's substitute for Withhold, forced by the envelope asymmetry - the four data proposal shapes carry no confidence, so the epistemic control is anchoring in observed surface rather than a calibrated bar.
- NEW **Observed-only fields**: a DataItem's `fields` name only fields observed on the surface; enforced in the proposer's shaping seam by intersection with the observed vocabulary and union with the persisted set, never by instruction alone.
- NEW **Grounded DataItem**: an item with at least one `SURFACES_AT` and at least one flow (T1); the surface half is REQUIRED per chunk (a path noun alone never grounds a lift, ratified 2026-07-30), the flow half is a graph-level acceptance predicate deferred across chunks because it depends on Assigner ownership that may arrive later or be withheld.
- NEW **DataItem notes (discriminative attribute)**: the DataItem-side counterpart of `service_contract` and of a System's `description`; compounded by the data-modeller as its sole incremental author, never blanked.
- AMEND **Analyser** (actor): the "run in two passes - an assignment pass and a dedicated data-modelling pass" description is retired with the monolith.
- AMEND **analysis.supervisor_enabled**: per the resolution of open question 1.

`docs/design/l1-domain-model-catalogue.md`:

- Section 4.3: name `notes` as the realisation of the existing "NL notes" slot, and state that it is the discriminative attribute the data-modeller reads to decide reuse-or-coin.
- Section 5.1: no change needed, and worth stating why - the row already reads `L1DataItem -> L0 Parameter/Header/field`, so the legacy prompt's Endpoint-target worked example (`pod.py:353-354`) contradicted the catalogue and is not carried forward (DPL-DEC-10).

## 14. Decision ledger

**DPL-DEC-01 - two LLM calls: a free-prose reflection, then ONE structured extraction of all four lists.**
*Claim:* the abductive lift from parameter names to business records needs prose, and the four lists must be extracted together.
*Evidence:* the single-call legacy data pass returned zero `data_items` twice, once under assignment load and once under negative framing (`pod.py:330-335`, `392-405`); the typist's reflection-then-extract chain is the ratified sibling shape (grilled #9); the four lists are mutually referential, since a `data_flow.item_key` and a `data_relationship` endpoint must be keys the same call emitted.
*Alternative rejected:* the typist's THREE calls. It loses because the typist split extraction from linking for a reason that does not apply here - its two structured calls need DIFFERENT context (systems vocabulary versus the primary/secondary service split) - whereas all four data lists share one context, and splitting them would re-introduce the cross-call key drift the typist had to patch with `_merge_systems` (`mechanism_typist.py:88-105`). It also loses on cost: #43 measures the reflection call at 92s and a three-call pass at 126s per chunk, and this is the THIRD role on every chunk.
*Assumption:* that a bounded prose call is affordable as a third per-chunk role. Ratified by the operator (question 7).
*Amendment, 2026-07-30:* the reflection's INTERNAL shape was redesigned after the operator identified that the original 7-step scaffold did not integrate `overthink`/`debug-hypothesis` primitives the way the typist's does - it read as a linear checklist rather than a hold-multiple-hypotheses-then-falsify loop. Redesigned to a 6-step ORIENT/HYPOTHESISE/VERIFY-FALSIFY/INTEGRATE/SHAPE/EMIT scaffold, with an explicit null-hypothesis requirement and a separate critical-judgment section mirroring the typist's `SKILL.md` structure. See section 7.3, 7.3a, 7.5.

**DPL-DEC-02 - the body is a factory, `make_data_modeller_body`, with a typist-style phase guard.**
*Claim:* bind collaborators once in a factory, and return `None` for a non-A.1 phase.
*Evidence:* `assigner.make_assigner_body` (`assigner.py:572-600`) is the factory precedent and makes the dispatch-time read explicit; `mechanism_typist_body`'s phase guard (`mechanism_typist.py:380-381`) is the A.2 scaffold precedent.
*Alternative rejected:* the typist's function-plus-`functools.partial` shape (`supervisor.py:571`), which loses because it scatters collaborator binding across the call site and hides which reads happen at dispatch time.

**DPL-DEC-03 - the invoke seam is `(messages, *, schema)` and gets its own injection point.**
*Claim:* a third `data_modeller_invoke_fn` parameter on `analyse_chunked`.
*Evidence:* `_default_invoke_fn(messages, *, schema=None)` returns prose for `schema=None` and structured output otherwise (`mechanism_typist.py:270-280`); `analyse_chunked` already carries a separate `typist_invoke_fn` for exactly this reason (`supervisor.py:564-571`).
*Alternative rejected:* reusing the Assigner's `(messages) -> batch` seam, which cannot express the prose call.

**DPL-DEC-04 - `bounded_retry`, fail-CLOSED on reflection exhaustion, empty on extraction exhaustion, both counted.**
*Claim:* use the shared retry helper; a reflection that never generated means the whole step is empty.
*Evidence:* `proposer_reasoning.bounded_retry`'s docstring names exhaustion as "the caller's FAIL-CLOSED block signal - the two-call proposer must not proceed on an unmet generation"; the typist realises it (`mechanism_typist.py:327-329`).
*Alternative rejected:* `pod._invoke_with_retry`, which loses because it dies with the monolith's neighbourhood and because two helpers doing one job is the duplication section 10 names.

**DPL-DEC-05 - six ordered shaping gates, groundedness LAST.**
*Claim:* the order in section 5 is part of the contract, not an implementation detail.
*Evidence:* `assigner.shape_proposal`'s docstring records the same class of dependency - "normalisation must precede withholding: a percentage-scale confidence clears any bar in 0..1, so withholding a batch that has not been normalised is a no-op wearing the appearance of a gate" (`assigner.py:250-252`).
*Alternative rejected:* a single validate-everything pass. It loses because it cannot express the dependency, so the groundedness test would run against unresolved references and certify an item as grounded on a reference to nothing.

**DPL-DEC-06 - no confidence gate on this path; groundedness is the epistemic control.**
*Claim:* the absence of a withholding bar here is a modelled asymmetry, not an oversight.
*Evidence:* the four data proposal shapes have no `confidence` field (`analyser_types.py:67-101`); `CONTEXT.md`'s *Judgment envelope* entry states the envelope is "reserved for `AGGREGATES` alone because assignment is a graded judgment, while data-surfacing and mechanism-fingerprinting are near-mechanical bindings (the deliberate envelope asymmetry)".
*Alternative rejected:* adding a `confidence` field to the data proposals and a second bar. It loses because it would contradict a ratified model decision and would introduce the percentage-scale defect class the Assigner had to repair, for a judgment the model says is a binding rather than a graded claim.

**DPL-DEC-07 - `fields` observed-only is enforced by code: intersect with the observed vocabulary, union with the live persisted set.**
*Claim:* the invariant is a contract, not an instruction, and the union is required for correctness under streaming.
*Evidence:* T1 section 3 and catalogue section 4.3 both make speculation a failure; `build_dataitem_cypher` writes `SET d += $props` (`l1_curator.py:471`), so a re-proposal replaces `fields` wholesale and would shrink the observed set chunk by chunk; the compounding precedent is the System `description` (`CONTEXT.md`, *System description*).
*Alternative rejected:* instructing observed-only and trusting it, which is what #10's required edit 3 names as insufficient ("the recipe already instructs it; promote to verifiable contract"). A second alternative, compounding in the writer with a `coalesce` union, is rejected in DPL-DEC-08's note.

**DPL-DEC-08 - `read_l1_inventory` gains `data_item_fields` and `data_item_notes`, additively.**
*Claim:* the proposer reads the persisted state it must compound, and the sole-writer stays policy-free.
*Evidence:* the additive pattern is ratified twice, `service_contracts` for #29 and `system_descriptions` for #9, both explicitly leaving the flat list untouched (`l1_inventory.py:53-66`); `withhold_below_bar`'s docstring states the general principle - policy lives "in the Assigner seam, NEVER in the shared `l1_curator` (the sole-writer stays policy-free)".
*Alternative rejected:* a union-on-write in `l1_curator`, which loses because a field-merge policy in the shared writer would apply to every future caller and is the first policy in a module whose whole discipline is having none.

**DPL-DEC-09 - a DataItem's `notes` is its discriminative attribute, compounded by this agent.**
*Claim:* a bare `item_key` list is not enough context for a reuse-or-coin decision, and `notes` fills the same slot `service_contract` fills for the Assigner.
*Evidence:* catalogue section 4.3 already lists "NL notes" as a DataItem attribute, so this names an existing slot rather than adding one; #29's rationale for `service_contract` states the general form - "a bare slug list tells a proposer which names exist, but nothing about what each one owns, so a slug like `byoc` is unroutable" (`pod.py:208-213`); the compounding-not-clobbering rule and its justification are already ratified for the System `description`.
*Alternative rejected:* reusing `fields` as the discriminative attribute, which loses because a field list distinguishes two items only when their observed fields differ, which early in a run they usually do not.
*Status:* RATIFIED 2026-07-30, with a scope constraint the operator set explicitly: `notes` carries an ADVERSARIAL CHARACTERISATION - what the record is, whose trust it carries, what breaks if that trust is misplaced - and names NO payload, NO technique, and NO concrete vector.
A vector -> assumption -> failure triple (the fuller shape the operator's first framing suggested) was considered and rejected: T1 fences hardened trust predicates to Phase B, and `CLAUDE.md` holds the phase-3 `fault-hypothesis` vocabulary as explicitly unratified, so a persisted concrete vector on an A.1 DataItem prop would be a fault-hypothesis in prose, one phase ahead of where the model allows it, indistinguishable from evidence once written.
Example: `"Client-supplied quantity and product reference; server likely re-reads price from the catalogue but may trust the submitted quantity, so value integrity rests on server-side revalidation."`

**DPL-DEC-10 - `SURFACES_AT` targets `Parameter`, `Header` or `Secret`; the legacy Endpoint example is not carried forward; a path noun alone never grounds a lift.**
*Claim:* the surface site of a DataItem is an observed datum, never an address.
*Evidence:* catalogue section 5.1 defines the edge as `L1DataItem -> L0 Parameter/Header/field`; `CONTEXT.md`'s *SURFACES_AT* entry says the same; #10 DP-4 states "SURFACES_AT targets Parameter/Header by design" and separately names secrets as in-scope lift surface; `ROLE_ADMITS["data_modeller"] = {Parameter, Header, Secret}` gives the agent no Endpoint identities to reference anyway.
*Alternative rejected (two, both operator-grilled 2026-07-30):* keeping the legacy worked example's Endpoint target (`pod.py:353-354`), which loses on the catalogue and is additionally unresolvable by the reference gate, since the chunk carries no Endpoint for this role; and lifting a DataItem from a path noun ALONE, grounded only by a later flow, which the operator rejected on the grounds that a path is the address a tester interrogates, never a place data appears - a flow with no observed datum behind it is an inference, not a grounding, and it names nothing concrete for a later phase to act on.

**DPL-DEC-11 - the reference gate canonicalises `surfaces_at` refs and drops what it cannot place.**
*Claim:* correctness must not depend on the model's formatting.
*Evidence:* `_l0_match_clause` MATCHes on exact label plus identity and `_write_each` does not distinguish a zero-row MATCH from a write (`l1_curator.py:446-459`, `608-624`); the identical defect on `AGGREGATES` wrote zero of 114 sound assignments and was fixed exactly this way (`assigner.py:171-186`).
*Alternative rejected:* stating the identity shape in the prompt and relying on it, which is the approach that measurably failed on the assignment path.

**DPL-DEC-12 - `data_flows.service_slug` is validated against the live inventory before the write.**
*Claim:* without this gate the data path restores Service minting.
*Evidence:* `build_data_flow_cypher` MERGEs the Service with provenance-on-mint (`l1_curator.py:512-514`); #34 D4 retired minting from the Assigner; `_aggregates_write_fn` exists precisely so the assignment writer "can never restore the Service-minting path the ticket removed" (`supervisor.py:620-625`).
*Alternative rejected:* letting the writer's MERGE stand as harmless. It loses because a minted Service has no `service_contract`, so it is invisible to the Assigner's matching and is precisely the AMV-12 identity drift #34 D4 removed.

**DPL-DEC-13 - groundedness requires a surface site per chunk (not optional); the flow half of T1's conjunction is a graph-level predicate.**
*Claim:* the surface-site half is epistemically required and decidable per chunk; the flow half is asynchronous with this agent's own pass and cannot be required without deleting items the run is on its way to grounding.
*Evidence:* T1 section 2 states the conjunction; the streamed path re-reads the cumulative surface per pass (`l0_stream.py:8-15`), so an item's flow (which needs the Assigner to have settled ownership, and the Assigner WITHHOLDS by design) can legitimately arrive in a later chunk than its surface site; DPL-DEC-10's rejection of a path-only lift is the reason the surface half cannot be relaxed the same way.
*Alternative rejected:* the original draft's surface-OR-flow disjunction (corrected 2026-07-30 - see section 5.4), which treated the two halves as interchangeable when they are not: only the surface site is an observed datum; the strict conjunction per batch, which loses on the streaming argument; and the conservative fallback of emitting no `data_relationships` at all (#10 DP-3's option (a)), which loses because DP-3 was ratified as (b).
*Status:* RATIFIED 2026-07-30 (surface required, flow deferred to a graph-level acceptance predicate).

**DPL-DEC-14 - candidate owning Services are derived LIVE by joining the aggregation view.**
*Claim:* re-derive the settled assignment at dispatch time; never carry it.
*Evidence:* #10's required edit 2 asks for exactly this, "a LIVE re-derive of the settled assignment", replacing the passed `assignment: L1DeltaBatch` argument (`pod.py:308`, `318-326`); `read_service_aggregations` exists and its docstring states the bounded in-memory match pattern (`l1_read.py:47-65`); the typist already re-derives the same view per dispatch.
*Alternative rejected:* passing the Assigner's in-run batch down the schedule. It loses on the live-graph invariant, and structurally: there is no accumulated-proposals channel, because "the live graph is the accumulator" (`messages.py:16-17`).

**DPL-DEC-15 - observations attach by ORIGIN, not by exact identity.**
*Claim:* per-asset pairing cannot work for this role's admitted types.
*Evidence:* `curator.ANCHOR_ALLOWLIST = {Domain, Subdomain, BaseURL, IP, Service}` (`recon/domain/curator.py:41`), and the triager re-anchors findings UP to the owning broad asset by design, so no Observation is ever anchored to a `Parameter` or `Header`; `chunking._observations_for` matches on exact `(type, identity)` (`chunking.py:167-176`).
*Alternative rejected:* copying the typist's per-asset paragraph render (`mechanism_typist.py:165-182`), which would attach insight to zero admitted assets and produce a render that looks informative and is empty; an evidence-text-match refinement (matching an origin-scoped observation's free-text `evidence` field against the admitted asset's path/name to distinguish "specifically referenced" from "generally origin-scoped" observations) was proposed and REJECTED by the operator 2026-07-30 - origin-scoped rendering stays uniform, no text matching.
*Handoff:* the typist's own per-asset pairing defect (why it is vacuous, not merely different) was described in plain prose and handed to the agent already working on the mechanism-typist, per the operator's direction; it is not filed as a separate ticket by this work and not fixed by this ticket.

**DPL-DEC-16 - a two-layer system message, with the HOW in `skills/analysis/data-plane/SKILL.md` via `skill_for`.**
*Claim:* the reasoning discipline is an operator-tunable file, never an inline prompt constant, and the WHAT survives a missing mount.
*Evidence:* the split and its rationale are ratified for the Bootstrapper and the Assigner (`assigner.py:403-418`, `assigner-A1-decisions.md` section 4 as amended); #30 names the per-role skill and the `skill_for` single-sourcing; `loop-constraints.md` requires a skill error to degrade rather than crash.
*Alternative rejected:* loading the shared `skills/analysis/analyser/SKILL.md`, which loses for the reason already recorded for the Assigner - it addresses a generalist proposer and instructs work this role must not do - and which is being retired in step 6 anyway.

**DPL-DEC-17 - an env-selected prompt arm (`DATA_MODELLER_PROMPT_CONFIG`) ships WITH this agent, mirroring `ASSIGNER_PROMPT_CONFIG`; `baseline` approximates the legacy shape.**
*Status:* RATIFIED 2026-07-30, REVERSING this document's original recommendation (no arm, one fixed arrangement).
*Claim:* a code-level rollback lever should exist from day one, consistent with the Assigner's machinery, even though no byte-faithful legacy prompt exists to reproduce.
*Evidence:* the operator's explicit ruling; `bootstrap._PROMPT_CONFIGS` / `assigner._ASSIGNER_PROMPT_CONFIGS` are the established pattern for this codebase's highest-variance surface (the analyser prompt, AMV-9's 143-vs-11 swing); section 9.1's `evaluate_data_plane` (in scope regardless) is what makes the two arms comparable rather than one being a shipped guess.
*Alternative rejected:* the original draft's "ship one arrangement, no arm" - correct that no BYTE-FAITHFUL baseline is constructible (the legacy prompt took a whole-slice `assignment` argument and an Endpoint-target worked example the catalogue now forbids), but the operator judged an approximate rollback lever still worth having over none, on the Assigner's precedent.
*Note carried forward honestly:* `baseline` here is an APPROXIMATION, not a byte-faithful reproduction (unlike the Assigner's `baseline`) - the doc-comment on the constant must say so, so a future reader does not trust it as a tested prior arrangement.

**DPL-DEC-18 - positive framing; the structural exclusion is code, so the prompt carries no leave-empty litany.**
*Claim:* stating what to fill, and that empty is wrong when a record was named, outperforms prohibiting the other lists.
*Evidence:* recorded twice, in the same words, on both sibling paths (`pod.py:330-335`, `mechanism_typist.py:227-230`), each time after a weaker model anchored on the empties and returned nothing.
*Alternative rejected:* belt-and-braces (prohibit AND narrow), which loses because the prohibition is the thing that measurably caused the failure and the narrowing already guarantees the outcome.

**DPL-DEC-19 - a per-chunk `DataPlaneStats` census with one counter per fail-open drop, plus a structured log line, plus `PassCensus.data_items_written`.**
*Claim:* every fail-open path is counted, so "the model found nothing" and "every judgment was discarded on the way out" are distinguishable.
*Evidence:* `AssignmentStats`' docstring records the run that "proposed 114 sound assignments and wrote zero, and NOTHING in the system said so" (`assigner.py:54-59`); `PassCensus`' docstring records the same discipline one level up, that a pass must report what it observed and not merely that it ran.
*Alternative rejected:* the mechanism-typist's no-census precedent, which loses on its own history: `_merge_systems` exists because five well-described Systems were being discarded unobserved.

**DPL-DEC-20 - the span is the node name `data_modeller`; `analyse-data-plane` is a tag; no Langfuse score.**
*Claim:* #10's verb-first span name is not available, and a Langfuse score must not be the authoritative measurement.
*Evidence:* `build_supervisor_graph` names nodes by the role literal and the supervisor routes with `Command(goto=role)` (`supervisor.py:240-241`), so span name and routing key are one string; #6 documents `create_score` but no call site exists in this repo; #34 AST-DEC-09 assessed and rejected Langfuse for measurement because "it is fail-open, optional, and drops span batches exactly under the latency stress a stall produces, so a gate built on it is silently vacuous in precisely the failing case" (`supervisor.py:413-421`).
*Alternative rejected:* renaming the nodes to verb-first names, which loses because it would change the supervisor's routing keys and the `ROLE_ADMITS` / `CHUNK_ROLES` / `messages.Role` vocabulary for a cosmetic gain.

**DPL-DEC-21 - `_chunked_write_fn` gains a data branch now; role-based routing is deferred.**
*Claim:* fix the silent drop with the smallest change that reuses the existing writer.
*Evidence:* `_chunked_write_fn` routes everything that is not systems-or-edges to the aggregates-only writer (`supervisor.py:634-646`), so a data-only batch is dropped; `default_curate_with_enrichment_fn` already handles a data-only batch correctly, because `l1_curate` is a no-op on empty lists and `enrich` does the work (`pod.py:475-496`).
*Alternative rejected:* extending the `WriteFn` signature to carry the envelope's role and routing on that, which is cleaner and kills the shape-sniffing, but loses HERE because it changes a typed seam with existing test consumers inside a ticket that already touches the schedule; recorded as a follow-up.

**DPL-DEC-22 - the backlog is carried, not transported.**
*Claim:* produce backlog descriptions for out-of-inventory flows and for surface that witnessed no record, and take them no further.
*Evidence:* #34 D6 defers the transport and `ProposalEnvelope` still has no `surfaced` field (`messages.py:132-151`); `make_assigner_body` logs and drops them for the same reason.
*Alternative rejected:* adding the envelope field here, which loses because it re-opens a decision another ticket owns and because no assertion in this increment could prove the backlog is correct.

**DPL-DEC-23 - A.2 is scaffolded by an inert phase guard and marked `designed-not-built`.**
*Claim:* the seam is named and inert, never a half-implementation.
*Evidence:* `CODING_STANDARD.md` section 12 requires exactly this, "make the dormant path inert (an empty string, a no-op default), never a silent half-implementation", and warns that "a no-op checker that rots undetected is a real hazard the model has already suffered"; `mechanism_typist_body` is the precedent.
*Alternative rejected:* designing A.1's internals for A.2 reuse, which the operator has explicitly deprioritised, and which would trade a shipped A.1 for a guessed A.2 interface.

**DPL-DEC-24 - the dissolution is the ordered sequence of section 11; steps 0-6 all land in this ticket, flag flip inside step 5, `_MAX_L0_NODES` retirement is a provable no-op.**
*Claim:* the steps stay individually reasoned about in order even though they are no longer split across two tickets by a flag gate.
*Evidence:* the operator's 2026-07-30 ruling to flip `supervisor_enabled` and dissolve the monolith together (superseding this document's original phased recommendation); `CHUNK_MAX_ASSETS = 100` against a 400 cap makes the `_MAX_L0_NODES` truncation branch unreachable on the surviving path regardless (`chunking.py:37`, `pod.py:35`).
*Alternative rejected:* the original draft's phased split (steps 0-4 shippable now, 5-6 gated on a later flag decision) - superseded by direct operator ruling, not by new evidence; a single fully-atomic change with no step ordering at all, which still loses for the reason #42 itself was deferred: this cannot be done piecemeal without regressions, which argues for a safe ORDER within one change, not for abandoning ordering.

## 15. Verifiability - the assertion catalogue

Named predicates with exact expected quantities.
The mechanised tests are a later stage, written with `/to-assertions` against the BUILT component, per #10's deferral caveat.
Expected values come from this document, never recomputed the way the code computes them.
Contract predicates go in `tests/integration/`, the walkthrough in `tests/e2e/`; the unit tier keeps the red-green loop and touches no database and no live LLM.
Prior art for style and naming: `tests/integration/test_mechanism_typist_contracts.py` (N1 to N11) and `tests/e2e/test_mechanism_typist_walkthrough.py` (W-N1).

**D1 - narrow.** Given a raw batch carrying 2 services, 3 aggregates, 1 system, 1 system_edge, 2 data_items, 2 surfaces_at, 2 data_flows and 1 data_relationship, the shaped batch has exactly 0 services, 0 aggregates, 0 systems and 0 system_edges, and the four data lists are untouched by this gate.

**D2 - kind allowlist.** Given 3 data_relationships with kinds `derived_from`, `reflected_in` and `sourced_from`, exactly 2 survive and `unknown_kind_dropped == 1`.

**D3 - reference gate, canonicalisation.** Given a `surfaces_at` whose `l0` is `{label: "param", identity: {"name": "ProductId"}}` and a chunk carrying `Parameter{name: ProductId, position: query, endpoint_path: /api/x, baseurl: B}`, the shaped entry has `l0.label == "Parameter"` and `l0.identity` equal to all four identity keys.

**D4 - reference gate, drop.** Given 3 surfaces_at of which 1 names a parameter absent from the chunk, exactly 2 survive and `unresolvable_surfaces == 1`.

**D5 - validation gate.** Given an inventory of `{"cart", "catalogue"}` and 3 data_flows naming `cart`, `catalogue` and `wishlist`, exactly 2 survive, `out_of_inventory_flows == 1`, and exactly 1 backlog description is returned containing the literal `wishlist`.

**D6 - no Service is minted by the data path.** After a full pass over a chunk whose model output names 2 non-existent slugs, the count of `:L1Service` nodes for the project is unchanged from before the pass.

**D7 - observed-only fields.** Given a chunk whose admitted assets carry names `{ProductId, quantity}` and a proposed `fields` of `["ProductId", "quantity", "price", "discount"]`, the shaped item's `fields` is exactly `["ProductId", "quantity"]` and `fields_unobserved_dropped == 2`.

**D8 - fields never shrink.** Given a persisted `fields` of `["ProductId"]` for `shopping_basket` and a proposal of `["quantity"]` from a chunk observing `quantity` only, the shaped `fields` is exactly `["ProductId", "quantity"]` and `fields_carried_forward == 1`.

**D9 - fields omitted when nothing was observed.** Given a proposed `fields` of `["price"]` with an observed vocabulary not containing `price` and no persisted fields, the shaped item's props contain NO `fields` key at all.

**D10 - groundedness, surface required.** Given 3 new data_items of which one has a surviving `surfaces_at` only, one has a surviving `data_flow` only (no surfaces_at), and one has neither, exactly 1 survives (the surfaces_at-only item) and `ungrounded_items_dropped == 2`.

**D11 - orphan relationship.** Given a `data_relationship` whose `to_item_key` names no surviving item and is absent from the inventory, 0 relationships survive and `orphan_relationships_dropped == 1`.

**D12 - order is load-bearing.** Given a batch whose only anchor for a new item is a `surfaces_at` that the reference gate drops, the item is dropped by groundedness; asserting the gates in the reverse order would keep it. Stated as a predicate over the shaped output: `kept_items == 0` and both `unresolvable_surfaces == 1` and `ungrounded_items_dropped == 1`.

**D13 - empty but valid.** A chunk admitting 0 Parameters and 0 Headers yields an empty batch, `status == "empty"`, and NO LLM call is made (asserted on the injected `invoke_fn` call count == 0).

**D14 - degradation.** A raising `invoke_fn`, a `None`-returning `invoke_fn`, a raising inventory read and a raising aggregation read each yield an empty-or-partial batch and never propagate; `reflection_exhausted` is true in the reflection case.

**D15 - idempotent replay.** The same chunk plus the same inventory yields a byte-identical shaped batch, and a second write of that batch leaves every `:L1DataItem`, `SURFACES_AT`, `PRODUCES`, `CONSUMES` and typed relationship count unchanged.

**D16 - the write path carries data.** A data-only batch routed through the run's `write_fn` produces non-zero `enrichment` counts; the same batch routed through `_aggregates_write_fn` produces zero, which is the latent drop DPL-DEC-21 fixes.

**D17 - the proposer emits no Cypher and sets no provenance.** No `data_modeller` symbol contains the string `MERGE`, and the four data proposal shapes carry no provenance field, so provenance can only come from `enrichment_proposals_to_deltas`.

**W-D1 - walkthrough, exact counts.**
Fixture: one chunk from one pseudo-job carrying 2 Endpoints (`GET /api/basket`, `POST /api/orders`, both on baseurl B), 4 Parameters (`ProductId` and `quantity` on `/api/basket`, `addressId` and `couponCode` on `/api/orders`), and 1 Header (`X-Cart-Token` on B); a bootstrapped inventory of exactly 2 Services (`cart`, `orders`), each with a contract; the Assigner having assigned `/api/basket` to `cart` and `/api/orders` to `orders`.
Expected after one full three-role pass over that chunk, read back from the live graph: exactly 3 `:L1DataItem` nodes; exactly 5 `SURFACES_AT` edges, every one targeting a `Parameter` or a `Header` and none targeting an `Endpoint`; at least 1 `PRODUCES` and at least 1 `CONSUMES`, every flow's source being one of the 2 pre-existing Services; exactly 2 `:L1Service` nodes, unchanged; every `:L1DataItem` carrying `prov_job == "analyser:<run_id>"`; no `:L1DataItem` carrying a `fields` entry outside `{ProductId, quantity, addressId, couponCode, X-Cart-Token}`.
The item-count expectation is the one figure a live model can legitimately vary, so the predicate is stated as an exact count over a FIXED injected `invoke_fn` in the integration tier, and as `>= 1` with the four integrity clauses above in the live tier - because a walkthrough that asserts a model's exact volume against a live provider asserts non-determinism.

## 16. Known gaps, and what is designed-not-built

**Designed-not-built.**
A.2 completeness sweep: the phase guard is inert, the reuse map is section 12, the `SweepCursor` shape it needs is a placeholder.
The Langfuse NUMERIC data-coverage score: named, not written, with the reason in DPL-DEC-20.
Hardened trust-assumption predicates (DP-2) and hardened DataRelationship invariant predicates (DP-3): Phase B, per T1's fence.
Attributed or inferred DataItem fields: Phase B (AMV-10); A.1 emits observed fields only.

**Knowingly incomplete in this increment.**
The backlog has no transport (DPL-DEC-22), so no assertion here can prove it is correct, and coverage of the "this datum has no owner" signal will look worse before it looks better.
DataItem identity stays deliberately open (DP-1 / L1OP-1): reuse is prompt-driven with no normalising key rule, so cross-service same-logical-item duplicates WILL appear and are the Anti-cluttering cleaner's ratified job (#11). `reused_item_keys` and `new_item_keys` in the census exist so that openness is measurable rather than merely declared.
The shipped prompt arrangement is unmeasured on day one (DPL-DEC-17), mitigated by section 9.1.

**Defects found while specifying, not fixed here.**
`_write_each` counts a `surfaces_at` as written when its `MATCH` found nothing, so `enrich()`'s counts and therefore `WriteCounts.enrichment` overstate (section 5.1); the proposer census is the authoritative count. Recorded here, deliberately not filed as its own ticket yet (operator housekeeping decision, 2026-07-30; question 5).
The mechanism-typist pairs observations to assets by exact identity while the triager anchors only to broad assets, so its per-asset insight render is near-vacuous by construction (DPL-DEC-15). Described in plain prose and handed to the agent already working on the mechanism-typist rather than fixed or filed here (question 6).
The mechanism-typist has no per-chunk census despite two silent fail-open drops (section 10, DPL-DEC-19).
The httpx-profile gate (`chunking._gate`/`_GATED_TYPES`/`profiled_origins`/`barrier`/`Chunk.flagged`) is REMOVED by this ticket rather than fixed - it was already effectively inert in production (`analyse_chunked` always passes `barrier=True`, so the gate could admit-and-flag but never actually withhold), and dropping the Parameter half (mirroring `#34 D1`'s Endpoint precedent) leaves nothing for the apparatus to ever gate again. See section 6, DPL-DEC question 9.
`#28` (per-endpoint profiling) is closed in the tracker but its code never reached `dev` and is stranded across three divergent unmerged branches predating the `src/` restructure; filed separately as `#47`. This ticket does not depend on it - profile classification is absent from the data_modeller's context entirely.
A real field-level DataItem-to-DataItem dependency model (distinguishing two divergent-lifecycle field pairs between the same record pair, which the current writer's `MERGE` on `(from_item_key, to_item_key, kind)` would silently overwrite) is a genuine open grey area, deliberately left to emerge from test evidence rather than designed now; filed as `#46`.
`run_analyser_supervised` is dead in production with one test consumer, and `pod.py` will no longer contain a pod after step 6.

## 17. Questions put to the operator, and their resolutions (grilled 2026-07-30)

Every question below was answered directly by the operator, not inferred from this document's own recommendation; several REVERSE what was originally recommended here, and are marked as such.

1. **Flip `analysis.supervisor_enabled` to default ON in this ticket, or ship steps 0-4 behind the flag and defer the flip?** RESOLVED: flip ON and dissolve the monolith together, in this ticket. Reverses the original recommendation (leave OFF, defer). See DPL-DEC-24, section 11 step 5.
2. **Per-chunk groundedness: surface OR flow, or something stricter?** RESOLVED: a surface site is REQUIRED per chunk; the flow half of T1's conjunction is a graph-level acceptance predicate, not an alternative path to per-chunk survival. Reverses the original surface-OR-flow framing. See DPL-DEC-13, section 5.4.
3. **Approve a DataItem `notes` prop as the discriminative attribute?** RESOLVED: yes, scoped to an adversarial CHARACTERISATION only - no named payload, technique, or vector, to stay inside A.1's descriptive fence and off the unratified phase-3 fault-hypothesis vocabulary. See DPL-DEC-09.
4. **Compound `fields` in the proposer or the writer?** RESOLVED: the proposer, as originally recommended (unchallenged).
5. **Fix `_write_each`'s counted-but-false write now, or file it?** RESOLVED: neither yet - recorded in section 16 as a known defect; not filed as its own ticket by explicit operator choice (housekeeping decision, 2026-07-30).
6. **Fix the typist's observation-pairing defect now, or file it?** RESOLVED: neither directly - the defect was described in plain prose and handed to the agent already working on the mechanism-typist; origin-attachment (not per-asset pairing) is adopted for the data_modeller regardless. See DPL-DEC-15.
7. **Is a bounded prose reflection call acceptable as the third per-chunk role?** RESOLVED: yes.
8. **Widen `ROLE_ADMITS["data_modeller"]` to include `Endpoint`?** RESOLVED: no - and separately, `Secret` WAS added (a different axis of the same table), per #10's own responsibility statement. See the admission-widening note in section 6 and DPL-DEC-10.
9. **Should the data_modeller consume `Chunk.flagged`?** RESOLVED: superseded - the whole profile-gate apparatus (`_gate`, `_GATED_TYPES`, `profiled_origins`, `barrier`, `Chunk.flagged`) is REMOVED in this ticket rather than consumed, because dropping the Parameter gate (mirroring `#34 D1`'s Endpoint precedent) empties `_GATED_TYPES` and makes the whole mechanism permanently unreachable. Verified NOT to affect `ROLE_ADMITS`/`admit_for_role`, the separate per-agent narrowing mechanism. See section 6.
10. **Is `evaluate_data_plane` in scope for this ticket?** RESOLVED: yes.
11. **Rewrite `tests/e2e/test_async_scaffold_walkthrough.py`, or retire it?** RESOLVED (by consequence of #1): rewrite - now unavoidable, since the legacy path it exercises stops being the default the moment `supervisor_enabled` flips ON.
12. **(New, surfaced during grilling) Env-selected prompt arm: ship one fixed arrangement, or build `DATA_MODELLER_PROMPT_CONFIG`?** RESOLVED: build the arm now, `baseline` approximating (not byte-reproducing) the legacy shape. Reverses the original recommendation (one fixed arrangement, no arm). See DPL-DEC-17.
13. **(New) `_chunked_write_fn`'s silent-drop defect on a data-only batch: fix by widening the shape-sniff, or by role-based routing?** RESOLVED: widen the shape-sniff condition to any non-empty data list; role-based routing recorded as a follow-up. See DPL-DEC-21 (already written this way in the original draft; confirmed, not reversed).
14. **(New) DataItem granularity: the record, or the individual datum?** RESOLVED: the record (coarse), unchanged from the original draft; a real field-level dependency question this raised is out of scope and filed as `#46`.
15. **(New) Can a DataItem be lifted from a path noun alone?** RESOLVED: no - the reasoning behind this answer is what drove the reversal of questions 2 and this document's original DPL-DEC-13.
16. **(New) Origin-scoped observation rendering: add an evidence-text-match refinement (specifically-referenced vs. generally-scoped)?** RESOLVED: no - origin-scoped rendering stays uniform.
