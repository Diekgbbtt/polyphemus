# Hunting #67 - per-agent specs decision record

Status: RATIFIED through two direct grilling passes (2026-08-03); every decision below was answered by the operator individually, and several corrected the drafting agent's own claims (Q2 verdict-level mis-specification, Q7 pattern-vocabulary scope).
Ticket: #67 (`Hunting Phase-2 spec: per-agent specs`), part of the wayfinder map #54.
Base: `feat/hunting-67-per-agent-specs`, branched off `dev` at 8737f72 (which carries the merged #63 implementation).

Conventions: plain dash only; one full sentence per physical line; ubiquitous language taken verbatim from `src/polymerhus/attack/hunting/CONTEXT.md`.
Every decision below carries its claim, the operator answer that licenses it, and the strongest alternative it rejects.
The downstream spec document is `docs/design/hunting-67-per-agent-specs-spec.md` (drafted from this record).

---

## 1. The frame this record locks

A test procedure is an experiment design, not a script: the pod converts a fault hypothesis into evidence through the live target's observable behaviour, and the quality of a test is measured by how discriminating its observations are.
The pitfalls that shape the decisions below: linear-script thinking, over-literal specs, tautological verification, silent environment bets, prior-evidence blindness, verdict-level confusion, absent termination discipline, and single-shot payloads.

## 2. Decisions from grilling round 1 (Q1-Q5)

### D67-01 - The pod is a cooperative agent team; this turn ships only a minimal LangGraph scaffold

**Claim.** The test-executor pod is a cooperative team of agents, analogous to the recon job-executor pod but with a different topology.
What is in scope for this implementation turn is literally the minimal scaffold the pod can later be built on: a general-purpose tool-calling capability, memory, Langfuse observability stubs, its communication interface with the parent HuntingAgent, and a helper symbolic layer used for specific testing-verification use-cases.
The pod is a sub-module within the hunting module, so it may use any construct the project's domain modules have, following the DDD approach.

**Evidence.** Operator answer to grilling Q1: the pod is a cooperative team "similarly to the recon job executor pod, but with a different topology", and this turn scopes "literally the minimal langraph scaffhold" with the named features, "a sub-module anyways within the huntin module, hence any construct that this project's domain modules have, following the DDD approach".

**Rejected.** A single-agent tool-calling loop as the pod's composition; and any build-out of the cooperative-team execution logic beyond the scaffold (out of scope by the ticket).

### D67-02 - The pod terminates binary; the three-valued verdicts live one level UP, at the HuntingAgent's hypothesis

**Claim.** The pod's state machine ends in the binary states `{successful, unsuccessful}`, exporting `{verdict, evidence-trail}`.
The three-valued set `{successful, unsuccessful, insufficient-evidence}` is NOT a pod state set: it is the hypothesis-level evaluation performed one level up, by the HuntingAgent, over the specific fault-testing procedure hypothesis.
The HuntingAgent derives that three-valued evaluation from the pod's binary outcome plus its evidence trail: a pod-`unsuccessful` carrying infeasibility or noise in the trail can map to hypothesis-`insufficient-evidence`; a clean symptom-absent maps to hypothesis-`unsuccessful`.
The pod is an instrument, not a judge of the hypothesis.

**Evidence.** Operator answer to grilling Q2: "2. is the correct answer, but most importantly this question surfaces a misunderstanding on your side or a mis-specification in the ticket: mentioned verdicts are for specific fault-testing procedure hypothesis done by the HuntingAgent one level upper, the test-executor pod is one level lower and its state machine ends in the states mentioned in 2".

**Rejected.** Three-valued pod terminals; a pod that can emit `insufficient-evidence` itself.

**Glossary delta.** The `three-level verdict model` entry's level-3 wording must be sharpened to make the pod binary and the hypothesis verdict derived one level up.

### D67-03 - TestImplementationSpec: core NL over a fundamental typed base

**Claim.** The spec is option-3-shaped: a core NL body inside a typed envelope, where the typed base is fundamental (mandatory), not decorative.
Its composition: the attack-surface context, the rationale and the verification symptom(s), the assumptions (brought over from the prompt the hunt-orchestrator feeds), the relevant previous test findings (likewise passed on from the hunt-orchestrator prompt), the payload vector, and the testing pattern (an abstract testing strategy).
All of it is described at a high level as a baseline; where there are relevant clear evidences in the L0 surface, the description must reference them, so the test-executor core agent has the flexibility to interpret any unsuccessful output meaningfully and drive a feedback-based testing loop, which may involve declining any attribute of the spec into a different variant.

**Evidence.** Operator answer to grilling Q3: option 3 (core NL with typed envelope) is closest, "BUT there must be a fundamental typed base", followed by the composition list and the feedback-loop capability.

**Rejected.** A fully typed schema (option 2) that would box the executor in; a fully NL core with only a thin envelope (option 1) that the engine could not drive.

### D67-04 - The hunt-orchestrator's tool surface includes a read-only L0/L1 graph view

**Claim.** The hunt-orchestrator is given the back-edge (targeted-recon requests) and the hunt-store reads, AND a read-only view over the L0/L1 graph, so it can ground its reasoning in the live graph rather than only in index-card projections.
The graph view is read-only: the orchestrator never writes L0/L1 (sole-writer discipline unchanged).

**Evidence.** Operator answer to grilling Q4: also a read-only L0/L1 graph view.

**Rejected.** Back-edge + hunt-store reads only (the drafting agent's recommended option).

### D67-05 - One observability recipe for all three agents

**Claim.** The same Langfuse observability recipe (traces, spans, score identifiers) applies to all three agents: hunt-orchestrator, hunting agent, and test-executor pod.
The pod's internals are observable to the same degree as the parent agents, not boundary-only.

**Evidence.** Operator answer to grilling Q5: same recipe for all three agents.

**Rejected.** Same recipe for orchestrator + hunting agent only, with the pod traced at its boundary (the drafting agent's recommended option).

## 3. Decisions from grilling round 2 (Q6-Q10)

### D67-06 - Four-way termination set closing the binary ends

**Claim.** The pod's looped state machine stops on exactly four conditions, all landing on the binary ends with the distinguishing evidence in the trail:
(1) symptom confirmed via the verification symptom(s) -> `successful`;
(2) pattern/probe space exhausted without symptom -> `unsuccessful`;
(3) a strong technical infeasibility assertion (unreachable target, missing tool, everything WAF-blocked) -> `unsuccessful` with the infeasibility in the evidence trail;
(4) budget/timeout reached -> `unsuccessful` with partial evidence.

**Evidence.** Operator answer to grilling Q6: the four-way set "as proposed".

**Rejected.** Folding infeasibility into space-exhausted (would blur the refuted-vs-inconclusive distinction the HuntingAgent needs); adding an external kill-switch interrupt as a required stop (orthogonal to the set).

### D67-07 - The testing pattern stays an open NL pattern in a typed envelope; the closed-enum engine is deferred to a dedicated ticket

**Claim.** The testing pattern is NOT a closed enum now: it is an open NL pattern carried inside the typed envelope, and the engine treats it as guidance over a generic loop.
The closed-enum pattern engine (a small set of mechanically-drivable patterns such as replay-differential, fuzz-differential, oracle-based, blind-boolean, timing, composite) could yield significant benefits if done accurately, but it is a large and complex build; it is documented as a potential future extension in a dedicated ticket with an exhaustive description, to be opened AFTER this and the other Phase-2+ specs are finished.

**Evidence.** Operator answer to grilling Q7: option 1 "could yield significant benefits if done accurately, though doing it as such requires quite a lof of work since it si quite complex, so document it as a potential future extention in a specific ticket that captures the work with an exhaustive description (after finishing the specs). However now let's stick with 2".

**Rejected.** Shipping the closed enum now; shipping an enum now with a generic fallback for unrecognized names.

### D67-08 - Variants are derived spec instances; the evidence trail is the full experiment log

**Claim.** When the executor declines or refines an attribute of the spec, the result is a derived variant spec instance, recorded with provenance.
The pod exports the full experiment log as its evidence trail: the variant specs, the raw observations, and the interpretations - so the HuntingAgent has what it needs to map the binary outcome onto the three-valued hypothesis verdict (D67-02).

**Evidence.** Operator answer to grilling Q8: "Variants are derived spec instances, full experiment log exported".

**Rejected.** Keeping variants internal and exporting only a verdict plus a summary; exporting only the interpreted evidence classes without raw observations.

### D67-09 - Budget and timeout are pod-internal fixed caps

**Claim.** The pod's probe budget and timeout are its own fixed internal caps, set by the pod itself, not carried as spec fields and not inherited as typed parameters from the HuntConfig.
The spec may not override them.

**Evidence.** Operator answer to grilling Q9: "Pod-internal fixed caps".

**Rejected.** Spec-carried budget/timeout seeded from the HuntConfig; budget arriving only via the orchestrator's prompt text.

### D67-10 - Typed base depth: everything except the rationale and the interpretation guidance

**Claim.** The typed base covers everything except two NL fields: the rationale and the interpretation guidance.
Typed: target identity, verification symptom(s), testing pattern, assumptions list, and payload vector space.
NL: rationale, interpretation guidance.
Budget and timeout are NOT spec fields (D67-09): they are pod-internal fixed caps.

**Evidence.** Operator answer to grilling Q10: "Typed: everything except rationale + interpretation".

**Rejected.** Typing only target/symptom/pattern/budget and leaving assumptions + payload vector to NL (the drafting agent's recommended option); a minimal envelope of target + pattern + budget.

## 4. Deferred work items (to open as tickets after the specs)

- The closed-enum testing-pattern engine (D67-07): a dedicated ticket with an exhaustive description of the pattern vocabulary and per-pattern engine mechanics.
- The cooperative-team execution logic of the pod beyond the scaffold (D67-01): already out of scope per the ticket; the scaffold is the future build-on point.
