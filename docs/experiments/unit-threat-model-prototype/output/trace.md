# Prototype trajectory - Service:article-publishing

Prototype run of the unit threat-modeller workflow (2026-10-15).
Unit: `Service:article-publishing` on the White Jotter target (`http://dj-viscon-workshop-1.vsos.ethz.ch`).
Input: `docs/experiments/unit-threat-model-prototype/inputs/sample-unit-dossier.md` (the only evidence source).
Output: `docs/experiments/unit-threat-model-prototype/output/threat-model-article-publishing.yaml`.

## Simulated runtime surface (labelled)

The planned runtime tools do not exist in this checkout. The following substitutions were made and are labelled where they occur below.

- `skill_list`: SIMULATED by listing `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/` and reading `README.md` plus `INVENTORY.md`. The listing returned 30 kept class skills and 101 nested variants.
- `skill_load(<name>)`: SIMULATED by reading `skills-unspurious/<class>/SKILL.md` or the nested `skills-unspurious/<class>/<variant>/SKILL.md`. The nested layout is not loadable until the W4 loader stream lands (README, status section).
- Threat-model store write tool: NOT AVAILABLE. Each gate below records the command as it WOULD be issued by the harness. The command shape is illustrative; the typed command surface is an open point (workflow section 6).
- HTTP-history database: NOT PRESENT (dossier provenance note; workflow section 5). Every HTTP read or environment interaction is recorded as a probe plan, never as an observation.
- Live probing: NOT PERFORMED (no target access in this run). All probe plans are untested.

Illustrative command shape used for every gate:

```
threat_model_store write \
  --model Service:article-publishing \
  --gate <UNIT_TECHNICAL_SHARP|TRUST_MODELLED|TRUST_ASSUMPTIONS_WRITTEN|VULNERABILITIES_WRITTEN|COMPLETED> \
  --section <section-name> \
  --source <trace-evidence-ref>
```

---

## State 1 - UNIT_TECHNICAL_SHARP

**Activity.** Grounded the unit on the service contract and extended onto the linked endpoints and systems.

- Unit evidence read: contract saves a jotter article with title, markdown source, rendered html, abstract, cover reference and date; exposure authenticated; aggregated endpoint `GET /admin/content/editor`; edge `EXPOSED_VIA WebPresentation:__singleton__` (OBSERVED).
- Extension onto connected systems (OBSERVED): Vue SPA over cleartext http with no CSP / X-Content-Type-Options / X-Frame-Options / Referrer-Policy; nginx/1.30.1; `/api` namespace and admin routes in the bundle; role vocabulary sysadmin, contentmanager, visitor, test, seeded accounts; the AuthorizationSystem guards `article-publishing` and `article-removal`; the AuthenticationMechanism is unevidenced; the IdentificationSystem has reduced grounding (no edges).
- Extension onto related services (OBSERVED): article-browsing serves the list newest first and single articles by identifier, public. account-registration binds submitted roles to the new account, public. book-cover-upload is a guarded service in the scaffold.
- HTTP-history reads that WOULD be run: PP-1 (submission request shape, Set-Cookie attributes), PP-9 (OPTIONS and Allow). Recorded as probe plans, not observations.
- Environment interactions that WOULD be run: PP-2 (two-principal replay), PP-3 (method matrix), PP-4 (html producer determination), PP-5 (extra-attribute binding), PP-6 (cover serving), PP-7 (transport and session attributes), PP-8 (error shape). Recorded as probe plans.

**Formal definitions written (content of the gate).**

- Interface agreements IA-1 to IA-8. The load-bearing gap: IA-2 and IA-3, the submission shape and the persistence decision, are unevidenced (ASSUMED and INFERRED). IA-5 records the cross-unit reading: the html stored here is served by the public browsing unit. IA-6 records the observed absence of runtime policy headers. IA-8 records the unknown credential mechanism.
- Control flows CF-1 to CF-6. CF-1 editor to persist; CF-2 reader flow; CF-3 removal; CF-4 authorization with the enforcement point unevidenced; CF-5 cover resolution; CF-6 failure shape.
- Data flows DF-1 to DF-7. The high-yield reading: DF-3, rendered html, has an UNKNOWN producer and a known consumer (readers, as markup), and DF-7, identity and role, crosses a cleartext channel.
- Probe plans PP-1 to PP-9 attached, all tagged PROBE_PLAN.

**Store-write gate (as it would be issued).**

```
threat_model_store write --model Service:article-publishing \
  --gate UNIT_TECHNICAL_SHARP --section technical_sharpening \
  --source docs/experiments/unit-threat-model-prototype/inputs/sample-unit-dossier.md
```

**Content written.** identity block; technical_sharpening with interface_agreements (8), control_flows (6), data_flows (7), probe_plans (9).

---

## State 2 - TRUST_MODELLED (branch a, then branch b)

### Branch a - trust agreements from the interface agreements

**Activity.** Translated each interface agreement into a trust agreement by reasoning over data attributes, application contexts and principal privileges. No assumptions were made in this branch; each mismatch is recorded as a trusted-but-unverified item.

- TA-1 over B1: the channel grants neither integrity nor confidentiality because every observed URL is cleartext; the server trust direction (present a valid session, be the principal) is unbacked by the channel.
- TA-2 over B2: the load-bearing attribute of the html field is safe for an HTML document context; the granting party is the untrusted client if the client produces the html.
- TA-3 over B3: the role attribute is trusted to equal true entitlement at the publication function; the evidence stops at the SPA route.
- TA-4 over B4: the article identifier is trusted to bind to authority; the scaffold names only function-level guards.
- TA-5 over B5: state attributes are trusted to be server-owned transitions; the FSM shows no review state.
- TA-6 over B6: a validated cover reference is trusted to keep naming the validated asset; validation and resolution are different components.
- TA-7 over B7: the stored html is trusted safe for readers with no runtime policy backstop (observed absence of CSP and nosniff).
- TA-8 over B8: honest response outcomes are trusted; error shape unevidenced.

### Branch b - dynamic state trust (stages 1 to 4 of the dynamic-states notes)

**Activity.** Constructed the EFSM and characterised and evaluated the transitions.

- Stage 1: service boundary and S0; state variables enumerated (article identity, ownership, the three content representations, cover reference, date, inferred status, principal role and session validity).
- Stage 2: states S0 to S7 and transitions T1 to T11, including the concurrent re-submission at T11 and the publication-window transition at T10.
- Stage 3: per-transition preconditions, verified conditions and trusted-only conditions. Consistent result: T2, T4, T5, T7, T8, T10, T11 verify nothing that is evidenced; T6 verifies nothing by design; T9 verifies at acceptance only.
- Stage 4: violations VT-1 to VT-6 recorded without presuming attacker control.
  - VT-1 untrusted-to-trusted crossing into stored html with no evidenced guard.
  - VT-2 object binding by identifier trusted, not verified (T7, T8).
  - VT-3 no review state between persistence and public serving.
  - VT-4 validation and use separated for the cover reference.
  - VT-5 the S1 to S2 role crossing with an unverified decision source.
  - VT-6 no evidenced uniqueness or idempotency (exploratory).

**Store-write gate (as it would be issued).**

```
threat_model_store write --model Service:article-publishing \
  --gate TRUST_MODELLED --section trust_model \
  --source trace.md#state-2
```

**Content written.** trust_model with trust_agreements TA-1 to TA-8 and dynamic_state_trust stages 1 to 4 (states, transitions, characterisations, violations VT-1 to VT-6).

---

## State 3 - TRUST_ASSUMPTIONS_WRITTEN

**Activity.** Continued both perspectives adversarially. Each assumption is named by induction FROM or TO a technical programming fault. The negative-language and strict-requirement clues from the trust-boundaries notes were applied to the contract and the scaffold.

Simulated tool call: `skill_list` was not needed in this state (no classification yet). The fault vocabulary came from the dynamic-states notes stage 7 (missing guards, incorrect authorization, stale-state reliance, non-atomic updates, inadequate object binding, failure to verify a trust prerequisite) and from the trust-boundaries stack layers.

Assumptions written, with their induction direction and fault:

- A1 -> F1 client-derived html accepted verbatim. Induction FROM the data contract (both representations saved) TO the fault (no re-derivation or sanitisation). Root violation VT-1.
- A2 -> F2 renderer output assumed safe. Later retired at the COMPLETED gate.
- A3 -> F3 function gate enforced only at the UI or edge. Induction FROM the coarse role vocabulary and the unevidenced enforcement point. Root violation VT-5.
- A4 -> F4 object-level binding inferred from session validity. Induction FROM function-level guards existing and no object-level guard being named. Root violation VT-2.
- A5 -> F5 state attributes persisted as data instead of gated transitions. Induction FROM the date attribute in the contract and the absent review state. Root violations VT-3, VT-6.
- A6 -> F6 validate-then-resolve gap on the cover reference. Induction FROM the reference form plus the separate upload guard service. Root violation VT-4.
- A7 -> F7 ambient cookie used as proof of intent. Induction FROM the cleartext SPA delivery and the unevidenced mechanism.
- A8 -> F8 session material treated as confidential over a cleartext channel with seeded accounts. Premise for the transport half is OBSERVED.
- A9 -> F9 unfiltered model binding. Induction FROM the contract enumerating a subset of the model attributes.

Cohesion check performed: F3 (function gate), F4 (object binding) and F9 (field binding) cover the three authorization planes of one save; F1 and F2 are the two exclusive readings of the html producer; F5, F6 and F7 cover state authority, asset authority and request intent. F2 was flagged at this point as the weakest member because it doubles F1 on the same content flow.

**Store-write gate (as it would be issued).**

```
threat_model_store write --model Service:article-publishing \
  --gate TRUST_ASSUMPTIONS_WRITTEN --section assumptions \
  --source trace.md#state-3
```

**Content written.** assumptions A1 to A9, each with id, statement, fault label and description, rung, induction note and citations.

---

## State 4 - VULNERABILITIES_WRITTEN

**Activity.** Switched to world 2 with abduction: for each mapped programming fault, cited the web vulnerability classes that would characterise the application if the fault were implemented. This was a runtime-state adversarial analysis over the FSM and the trust mismatches, not a sweep of the skill catalogue.

Simulated tool calls (recorded in place):

- `skill_list` -> listed `skills-unspurious/` (README + INVENTORY): 30 classes, 101 variants, 28 decomposed classes.
- `skill_load(xss)` and `skill_load(xss-stored)` -> read both SKILL.md files; xss-stored owns the write-then-retrieve pairing that matches the article storage boundary.
- `skill_load(mass-assignment)`, `skill_load(mass-assignment-nested-relation-write)` -> the singleton binder and the nested child write.
- `skill_load(idor)`, `skill_load(idor-direct-object-swap)`, `skill_load(two-principal-authz)` -> the one-identifier swap and the owning cross-principal procedure.
- `skill_load(broken-function-level-authorization)`, `skill_load(http-method-tampering)` -> action-level failure and its verb drift bypass family.
- `skill_load(csrf)`, `skill_load(business-logic)`, `skill_load(race-conditions)`, `skill_load(insecure-file-uploads)`, `skill_load(crypto-weakness)`, `skill_load(weak-credential-discovery)`, `skill_load(ssti)` -> the remaining candidates actually considered.

Vulnerabilities written: V1 (xss-stored, F1), V2 (xss, F2), V3 (ssti, F2), V4 (BFLA, F3), V5 (http-method-tampering, F3), V6 (idor, F4), V7 (business-logic, F5), V8 (race-conditions, F5), V9 (insecure-file-uploads, F6), V10 (race-conditions, F6), V11 (csrf, F7), V12 (crypto-weakness, F8), V13 (weak-credential-discovery, F8), V14 (mass-assignment, F9).

Multiple vulnerabilities per fault were used where the fault admits different runtime readings over the same interface: F2 yielded V2 and V3; F3 yielded V4 and V5; F5 yielded V7 and V8; F6 yielded V9 and V10; F8 yielded V12 and V13.

Explicitly considered and not cited at this state: information-disclosure and header-injection were read and rejected as primary classes, because no response-reflection or header-emission evidence exists in the sharpening and neither carries the runtime state reading this state asks for. They may return as enabling findings at the surfer stage.

**Store-write gate (as it would be issued).**

```
threat_model_store write --model Service:article-publishing \
  --gate VULNERABILITIES_WRITTEN --section vulnerabilities \
  --source trace.md#state-4
```

**Content written.** vulnerabilities V1 to V14, each with skill_class, fault_ref, characterisation and why_this_class.

---

## State 5 - COMPLETED (failure-mode deduction)

**Activity.** Mapped every vulnerability back to an approximate runtime execution failure mode grounded in the State 1 sharpening, for the exploitation case. Applied the drop rule.

Kept after deduction: FM1 (V1), FM2 (V4), FM3 (V5), FM4 (V6), FM5 (V7), FM6 (V8), FM7 (V9), FM8 (V10), FM9 (V11), FM10 (V12), FM11 (V13), FM12 (V14).

Dropped after deduction:

- FM13 (V2): the would-be failure mode is server-render sanitising bypass and stored execution. Not technically feasible from this perspective: no server-side render step is evidenced, the SPA is the only evidenced html producer, and a server that re-rendered would not need the client html field at all. Fault F2 and assumption A2 are dropped with it. Re-entry condition: PP-4 shows a server render step at save or serve time.
- FM14 (V3): the would-be failure mode is template evaluation to code execution. Not technically feasible from this perspective: no templating layer is evidenced in the publication path. Dropped with F2.

Ranked the kept chains by rough likelihood (no numeric formula): see the ranked_chains section of the model.

Note on FM6 (V8) and FM11 (V13): both are kept at low likelihood with their grounding weakness stated in the entry, because neither invariant nor credential fact is evidenced. They are candidates for removal by the review, unlike FM13 and FM14 which are removed by the workflow's own rule.

**Store-write gate (as it would be issued).**

```
threat_model_store write --model Service:article-publishing \
  --gate COMPLETED --section failure_modes,ranked_chains,open_questions \
  --source trace.md#state-5
```

**Content written.** failure_modes FM1 to FM14 with the two drops recorded; ranked_chains (12 kept chains, high to low); open_questions; citations.

---

## Trajectory summary

| State | Activity | Gate | Wrote |
|---|---|---|---|
| UNIT_TECHNICAL_SHARP | Grounding, endpoint extension, formal interface/control/data definitions, probe plans | threat_model_store write --gate UNIT_TECHNICAL_SHARP | identity, technical_sharpening (IA 1-8, CF 1-6, DF 1-7, PP 1-9) |
| TRUST_MODELLED | Trust-agreement branch, then dynamic-state branch stages 1-4 | threat_model_store write --gate TRUST_MODELLED | trust_agreements TA 1-8, dynamic_state_trust stages 1-4, VT 1-6 |
| TRUST_ASSUMPTIONS_WRITTEN | Adversarial continuation, fault induction | threat_model_store write --gate TRUST_ASSUMPTIONS_WRITTEN | assumptions A 1-9 with faults F 1-9 |
| VULNERABILITIES_WRITTEN | World 2 abduction over the skills suite | threat_model_store write --gate VULNERABILITIES_WRITTEN | vulnerabilities V 1-14 |
| COMPLETED | Failure-mode deduction, drops, ranking | threat_model_store write --gate COMPLETED | failure_modes FM 1-14, ranked_chains, open_questions |

Places where the workflow or document shape was underspecified (feeds the grilling round):

1. The drop rule does not distinguish "not feasible in mechanism" from "not evidenced in this sharpening". FM13 and FM14 were dropped on the second reading; the rule text supports either reading.
2. The workflow does not say whether a dropped assumption is deleted or retired. A2 was retired in place for auditability.
3. Ranked chains were modelled as fault-vulnerability-failure-mode triples. The workflow leaves the entity model open (its relations-and-rows question).
4. The gate commands and their typed surface are undefined; the illustrative shape used here is a guess.
5. Probe plans had no specified home. They were placed inside technical_sharpening and mirrored in citations with PROBE_PLAN tags.
6. The rung vocabulary is open; OBSERVED, INFERRED and ASSUMED were used with premises and faults tagged separately where they differ.
7. Variant versus class citation is unresolved while the loader is flat and the nested layout is not loadable (V1 cites xss-stored plus xss).
8. The workflow assumes HTTP-history evidence exists. With none, grounding leaned on the contract wording; the submission interface is an inferred shape that a single probe could invalidate, taking part of the fault set with it.
9. No rule exists for exploratory low-likelihood entries (FM6, FM11); they were kept with the weakness stated rather than silently dropped.
