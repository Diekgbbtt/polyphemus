# Unit threat model - modeller workflow (design record)

## Amendment 2026-10-25: impact-first elicitation

The threat-model impact-elicitation workstream supersedes the likelihood-only risk score and the failure-mode artifact in this document.
The decisions are in `docs/design/threat-model-impact-elicitation-adr.md`; the component map is `docs/design/threat-model-impact-elicitation-impact-map.md`.
Where this document and the amendment disagree, the amendment wins.

- A threat carries `VC`, `VI`, and `VA` plus a literal end impact. The store computes `impact = 1 - (1-VC)(1-VI)(1-VA)`, the ordinal weight, and `threat risk = likelihood_weight * impact_weight`.
- The ranking and the dispatch buckets use the combined risk. The run record carries `impact_weights` and `impact_breakdown`.
- The `failure_modes` artifact, `Threat.failure_mode_refs`, and the pod `failure-mode` variant basis are removed. The modeller no longer judges technical feasibility; the hunter and the pod own the effective attempt.
- The trust procedure uses the four axes `identity`, `spatial`, `temporal`, and `controls_semantics`.
- The well-formedness phase runs between `VULNERABILITIES_WRITTEN` and `COMPLETED`. Its exit is one `wellformedness` note plus the `COMPLETED` write; a lower-gate write is the re-entry signal.
- Every vulnerability binds a suite class parent or leaf. Technique families are not classes. `suite_gap` is removed. Class findings are non-blocking.


*Status: design decision record (2026-10-15), from the unit threat model grilling (workbench: `docs/design/unit-threat-model-workbench.md`). It records the operator's decisions and the specified workflow as given. Open points are marked. Nothing here is built. The workbench carries the question numbering; this document carries the workflow contract. Extended the same day with the Q10-Q17 answers (consumption at COMPLETED, the evidence and drop rules, the threat entity, the grounding inputs, the material disposal). Extended 2026-10-16 with the Q18-Q32 answers (drop semantics reframed to retention-first, the hunter threat payload, the store home, dispatch sequencing in scope, no schema gate - per-step verbatims). Extended 2026-10-17 with the Q33-Q36 answers (the CVSS-inspired 5-level risk scoring with the four-attribute ontology; the confidence-degree rename and its falsification-nature lifecycle; design B, the per-unit directory with per-threat files; the validation seam; the hunter feed-forward contract). Extended 2026-10-18 with the Q37-Q40 answers and the production hunter prompt redesign decisions (workbench Rounds 7 and 8).*

## 1. Model identity and consumption

- One model per testable unit, stored as `<unit_id>.yaml`.
  The unit id IS the model id.
  Different L1 units are different ids by construction, so no run component belongs in the name.
  (Operator decision 2026-10-15; supersedes the earlier (unit, run) proposal, whose collision argument was rejected.)
- The model is consumed at the COMPLETED write (Q10): there is no separate "confirmed" status and no persisted status lifecycle.
  The five uppercase workflow states are exactly what the harness passive tracking persists; the model's state is structural - vulnerabilities are promoted to threats or degraded as unfeasible or duplicate inside the content.
  Every unit yields a model; there are no model-level drops.
- A new run excludes units whose model is already completed from intake, and records the exclusion in the run (Q10).
- The model is consumable once it features the threats (Q28); the threat ranks drive the dispatch sequencing (Q20).
- The model is persisted per project at `data/<project_id>/hunting/threat_modeller/` with `produced/` and `consumed/` subdirectories (decided 2026-10-16, Q19/Q21); file names sanitise `:` and `/` to `-`, and the document id stays authoritative; the per-threat layout is decided (2026-10-17, Q34, design B): `produced/<unit_name>/` holds the model document plus one `threat-<rank>.yaml` file per threat, consumption moves each threat file, and the model document moves when its last threat file is consumed; the command surface is the single generic store write (Q12).
- The model carries an `evidences` attribute per record - request records (e.g. `GET <endpoint path>`), HTTP-history entry identifiers, notes, previous threat models - replacing citations; `probe_plans` are removed (Q11).

## 2. The reasoning requirement

- There must be a structured thought procedure, tracked passively in the harness as done in the current hunt-orchestrator implementation, so that the trajectory keeping is guaranteed by the harness.
  In the current implementation the phase turns are inbox-request turns of one actor per run and the loop states ride the graph's `loop_state` channel; the same passive tracking pattern applies here.
- The machine is an extended finite state machine: states, transitions, and per-state gates.
- Each state's gate is a threat model store write-tool command (section 3); one generic store-write surface extends the document at each gate (Q12).
- A core design principle: the modeller thinks primarily in function of the trust model, mapped from the service application contract or from the system technical description.

### 2.1 Evidence, probing and the drop rule (Q10-Q15)

- Probing is part of the workflow phases: the modeller probes the running target to back its trust assumptions and technical fault hypotheses with technical evidence, or to falsify them, iterating until the assumption space is sufficiently explored (saturation; no modeller-scoped cap).
- Every claim carries a **confidence degree** (renamed from `rung` 2026-10-17, Q35):
  - `OBSERVED` - witnessed by a probe or a request record;
  - `INFERRED` - reasoned from observed facts plus technology or framework defaults;
  - `ASSUMED` - a hypothesis not yet probed.
  The degrees direct the probing (the ASSUMED claims are the probe targets) and gate the feasibility judgement.
  The content profile is extended: an entry features references to the grounding probes or requests that produced it, and the attribute is repeatable and indexable when written as a list (a claim may carry several entries, each indexing its own grounding).
  Lifecycle (pure falsification, Q35): a promotion probe must have a pure falsification nature - an accurate proxy signal to a falsification claim on the claim under test; when the proofs do not back the falsification claim, the claim is certified robust and promoted from `ASSUMED` to `INFERRED` or `OBSERVED` depending on the accuracy delta of the proxy signal.
  A falsified vector lowers the likelihood, it never drops the vulnerability; the degrees freeze with the model at the COMPLETED write.
  The same loose fail-open principle as the drop rule governs: only a strong technical proof contradicting the trust agreement's properties or elements drops the threat.
- The threat carries its own confidence degree as well: it is authored at the COMPLETED write and grades the threat's load-bearing premise (for example the carrier agreement the fault rides); it is one factor of the threat's risk score (section 2.1, the scoring bullet below).
- Drop rule (reframed 2026-10-16, retention-first): the vulnerability hypothesis is retained by default, stated broadly at the trust-agreement level; vectors and payloads belong to the hunters.
  A probe that falsifies a vector lowers the likelihood; it never drops.
  A drop needs a fundamental technical-infeasibility finding - the mechanics the failure mode relies on are absent, or the data is not attacker-influenced, so the trust agreement was misspecified - and the finding corrects the interface and trust agreements it was mapped from (a backward effect).
  Drops are recorded in place; the failure mode stays in the model for debugging and is never fed forward to the hunter.
- Failure modes serve the technical feasibility assessment and the likelihood scoring only; a vulnerability may have one or more (1:n); they stay in the formal model, are kept in the threat for debugging, and are never passed downstream (Q30).
- The ranked rows are **threats**: fault -> vulnerability class -> failure mode assessment -> likelihood; threat ids are assigned symbolically at the COMPLETED write, in ranked order (`threat-1` = highest).
- Likelihood is scored with the adopted CVSS 4.0-inspired variant (decided 2026-10-17, Q33): the scoring function uses only **attack vector**, **environmental requirements (attack requirements)**, **required privileges**, and **complexity**, each parametrised by a brief formal ontology over the unit's metrics and state attributes, injected into the risk-scoring step of the modeller's chain of thought; the **5-level scale** is adopted from the start, and a factually unfeasible threat stays recorded with score `none`; impact is excluded; the threat's confidence degree is one factor of the score. The threshold calibration, the per-level weights, and the exact level names land with the change spec (workbench R3-2); the full CVSS base-metric adoption including impact is deferred to ticket `#368`.
- Breadth is a feature of this phase: the kept set maps research directions and the hunters deepen them; low-ranked threats stay dispatchable, and the surfer dispatches the high and medium threats first, pausing the low ones until those are executed (Q20).

### 2.2 Termination, probes and model validation (Q55-Q58)

- Termination is saturation-based with no modeller-scoped cap (Q55(a)): a unit's modelling stops when every probeable `ASSUMED` claim is resolved and a full further pass yields no new assumption branches.
  The cost bound is the execution-wide token budget plus the risk budget.
- The modeller's `exec` probe budget is unbounded at the role level, like the hunter's (Q56(a)).
  The saturation stop, the execution-wide token budget, and the risk budget bound the run; the probe cadence is telemetried as the gate cadence is (R2-17).
- Side-effect rules (Q57(a)): mutating probes are allowed for evidence (for example persisting a value or submitting a form); every probe and its side effect is recorded in `evidences`; restoration is best-effort where the surface offers it (as the trial practised with the channel default); probes are never destructive or data-exfiltrating.
  The modeller checks mechanics; it does not exploit.
- `ratify` is repurposed into the completion-time whole-model validation (Q58(a)): it runs the loose necessary-attribute checker across the model, records the non-blocking outcome, and finalises the COMPLETED write.
  The per-phase loose checks ride the gate writes (R5-2).

## 3. The workflow (as specified)

Starting context: the L1 discretely testable unit.
The grounding inputs are the unit projection (the service contract or the system technical description, with the linked endpoints and services-systems), the L1 application-surface overview (a new L1 entity: core features and canonical user journeys; landing shortly in the bootstrapped typed surface), and an optional grep of the notes store and the previous threat models (Q14).
HTTP-history reads and live probes are phase activities, not inputs; their records become claim evidence.

### 3.1 Grounding -> state UNIT_TECHNICAL_SHARP

- Ground on the service contract or the system technical description.
- Extend onto the linked endpoints and services-systems.
- Query the HTTP-history database for the request-response (HAR) records to those endpoints (evidence; the store may be empty for a fresh project).
- Interact with the running target in various manners to reverse-engineer the technical mechanism the unit relies on; amend the probes upstream in this state.
- Once an exhaustive, sharp picture of the unit exists, define formally:
  1. all technical interface agreements between the components involved in that unit,
  2. the control flows, and
  3. the data flows.
- Reasoning material: the first two steps of `docs/design/modelling-trust-boundaries-notes.md`, particularly the Request-handling stack layers.
- Gate: a threat model store write-tool command that initializes the threat model document.

### 3.2 Trust mapping -> state TRUST_MODELLED

Two analysis branches, executed sequentially, so that the service contract failure is shaped from different angles.

1. Trust-agreement branch: all described interface agreements are translated into trust agreements (aka boundaries).
   The modeller reasons over the data attributes of the data contracts, the application contexts, and the principal privileges.
   The branch consumes the interface agreements, the OBSERVED/INFERRED/ASSUMED layers of the request-handling stack or of the application workflow protocol, and the agreements among them (Q14).
   Material: the trust-modelling steps of `docs/design/modelling-trust-boundaries-notes.md` that do not concern making assumptions.
2. Dynamic-state branch: afterwards the unit is analysed from the application-states-flow perspective; dynamic state trust is modelled.
   From this angle the modeller can uncover faults specific to the contract failures of the class race condition (TOCTOU), multi-step business-logic bypass, and forced state transitions.
   Material: `docs/design/modelling-dynamic-states-trust-notes.md`, until stage 4 of its workflow.

- Gate: a threat model store write-tool command that extends the threat model with the trust model outcomes of both branches.

### 3.3 Assumptions -> state TRUST_ASSUMPTIONS_WRITTEN

- Continue sequentially evolving both perspectives of the trust models, and write the assumptions that can be captured from both angles.
  The respective notes documents outline effective adversarial reasoning workflow steps that bend the legs of the trust agreements.
- Each assumption is named by induction from or to a technical programming fault (itself an assumption) that a developer could have made.
- Result: a cohesive and solid set of technical programming faults.
- Gate: a threat model store write-tool call that extends the threat model with the trust assumptions and the respective programming faults.

### 3.4 Vulnerability citation -> state VULNERABILITIES_WRITTEN

- Switch to world 2 (the symmetric world), with an abduction reasoning model: the modeller does a runtime state adversarial analysis.
- In function of the mapped classes of programming faults, the modeller cites the web vulnerability classes that could characterise the application if those programming faults were effectively implemented.
- Fundamental entities: the web-vulnerability skills of the unspurious suite (`/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/`, about to merge into `dev`), consumed through the bound `skill_load` and `skill_list` (a filtered listing: a required name regex, a parent/leaf cascade, and each entry's frontmatter) surface; the suite is added to all hunter agents and the threat modeller (delivered by the suite workstream; the client components are written here against the assumed names and contracts).
- Naming rule (Q14): name the vulnerability classes freely from the canonical taxonomy first (unrestricted induction); only then consult the suite and map each named class to the suite class that covers it.
  The stored `web vulnerability class` value must equal a skills-suite class directory name; the control plan binds that skill to the downstream hunter prompts.
  Where no suite class covers a named class, the canonical name is kept and the gap flagged.
- There can be multiple vulnerabilities per fault.
- Gate: a threat model store write-tool call that extends the threat model with the vulnerabilities that characterise the application if those faults are effectively implemented.

### 3.5 Failure-mode deduction -> state COMPLETED

- Each vulnerability yielded is material for deduction: map back approximately to one or more runtime execution failure modes (1:n allowed, Q15), based on the originally written technical sharpening of the unit, for the case where the vulnerability is exploited.
- Drop rule (reframed 2026-10-16, retention-first): the vulnerability and its upstream faults drop only on a fundamental technical-infeasibility finding, recorded as a backward correction of the agreements it was mapped from; falsified vectors lower the likelihood instead (section 2.1).
- The surviving threats are ranked by likelihood (qualitative; impact excluded) and threat ids are assigned in ranked order at this write.
- Gate: a threat model store write-tool call that extends the threat model with the failure modes and the ranked threats.

### 3.6 Feed-forward to the hunters (specified 2026-10-17, Q36)

- Each threat is dispatched to a hunter as a threat payload: a HumanMessage rendering of the abduction components - the technical interface agreement overview, or the application dynamic-state evolution -> the trust boundary agreement, or the dynamic-state transition trust -> the respective programming faults -> the vulnerabilities that characterise the application if the faults are effectively implemented - plus the unit context, the technical sharpening overview, the trust overview, the likelihood with rationale, the confidence degree, and the evidences.
- The failure modes are never rendered (R3-8): they stay in the model for debugging.
- The hunter's production prompt (redesign decisions 2026-10-18, workbench R8-1) keeps the original decision tree's navigation and the core of the `TestImplementationSpec` typed surface with reframed attributes: the threat ontology sits in a dedicated paragraph; the discipline extends the existing discipline paragraph; grounding absorbs the class-skill and source reading (target surfaces first, then the skill, then the knowledge DB, HTTP history, notes, hunt store, auth context); the tree's fault-exhaustiveness question is replaced by grounding on the technical failure modes of the trust agreements; new SLICE and COLLECT phases feed the discrimination axis (advanced techniques/proxies, chaining with low-hanging vulnerabilities and the capabilities they must gain, technology-specific failure-mode instances, and payload-vector classes discriminated by carrier, protocol, and behaviour - the encoding scheme is not a discrimination variable); DECOMPOSE becomes the DISCRIMINATE, GENERATE becomes combinatorial over the axis instances without the structural `supports`/`conflicts`/`test` attributes, the exhaustiveness check becomes WELL-FORMEDNESS, the second DISCRIMINATE is removed, a likelihood-based ranking runs on the fly, and VERIFY-CLAIMS keeps falsification-only probes; EVALUATE, CONCLUDE, and [G] are removed.
- Typed surface: `verification_symptoms` are the failure modes of the interface or state-change technical agreements (yielded from the exploited assumption on the trust agreement or the dynamic-state transition), and stay the manifestation ground truth for the test-executor pod; `variants` are combinations of the subset of skills-ontology entities; `payload_vector_space`, `interpretation_guidance`, and `testing_pattern` are retired; the typed surface stays simple and execution-oriented, with deep plain-prose values the pod can extend from.
- The hunter harness FSM refactor (workbench R8-2) and the test-executor-pod contract (R8-3) are decided (2026-10-18) and land with the change spec; the production prompt is implemented in a dedicated work phase with refine-adversarial-review iterations.
- Prototype evidence for the feed-forward contract (the QA measurement) lives in `docs/experiments/unit-threat-model-testimplspecs-qa.md`; its structural limitation (exhaustiveness verification) is documented there.

## 4. Harness-tracked states (summary)

One generic store-write command surface extends the document at each gate (Q12); the harness-tracked trajectory stays passive (Q12); the COMPLETED write is the consumption point (Q10).
No blocking schema-validation gate exists anywhere (Q28); the validation seam is decided (2026-10-17, Q35, workbench R5-2): the gate write checks parseability only, fail-safe and loud on an unparseable write; consumption-time parsing is surfer-driven - the surfer parses what is parsable and feeds the parsed object to the next layer, which accepts a non-strict schema and translates it into the object rendered in the hunter prompt; each phase's transition gate carries a formal data contract of core/necessary plus optional attributes, and a loose schema checker verifies only the necessary attributes.
The trajectory keeping rides the per-step verbatims injected alongside the gate-write tool responses (the hunter-harness phase-transition verbatim pattern - the verbatim selects on the write's state attribute; module constants, never the system prompt).
The model becomes consumable once it features the threats (Q28).

| # | State | Gate (store write command) |
|---|---|---|
| 1 | UNIT_TECHNICAL_SHARP | initialize the model document |
| 2 | TRUST_MODELLED | extend with the two branches' trust outcomes |
| 3 | TRUST_ASSUMPTIONS_WRITTEN | extend with assumptions and programming faults |
| 4 | VULNERABILITIES_WRITTEN | extend with the cited vulnerability classes |
| 5 | COMPLETED | extend with the failure modes and the ranked threats |

## 5. Material dependencies (as specified)

- The two modelling-notes documents are removed from production as standalone documents; their material is embedded into the specific phases of the prompts (Q13):
  - `docs/design/modelling-trust-boundaries-notes.md`: steps 1-2 and the request-handling stack layers for grounding; the trust-modelling steps (not the assumption-making ones) for the trust-agreement branch; the adversarial steps for the assumption state.
  - `docs/design/modelling-dynamic-states-trust-notes.md`: until stage 4 for the dynamic-state branch; the later stages bear on the assumption and deduction states.
- The unspurious web-vulnerability skills suite: the classification material for the vulnerability state, via the bound `skill_list` / `skill_load` surface.
  `skill_list` is searched by a required name regex; a parent match includes its leaves and a leaf match includes its parent.
- HTTP-history records, the L1 unit projection, the L1 application-surface overview, and live probes: the evidence material for grounding and for the trust-agreement and dynamic-state branches; the probes are amended in the grounding state.
- Note: HTTP-history reads and probes are actions, not documents; where no store exists (fresh project), the evidence is the probe record and the notes alone.

## 6. Open points (carried to later rounds)

- Dispatcher side: the per-threat layout and the cross-unit sequencing direction are decided (R5-1 design B; Q20); the quiesce-predicate changes, the stop/resume mechanics, and the execution-completion detection land in the change spec (R2-6 closed 2026-10-18, Q59).
- The hunter data contract implementation details land in the change spec (workbench R2-3 residual); the feed-forward contract is specified (section 3.6); the production hunter prompt redesign is R8-1 (implementation phase pending, refine-adversarial-review iterations); the hunter harness FSM refactor (R8-2) and the test-executor-pod contract (R8-3) are decided (2026-10-18: the proxy-signal FSM matrix and the pod contract reframe, workbench R8-2/R8-3) and land with the change spec.
- The risk scoring is adopted (Q33); the enum is ratified as `none / low / medium / high / critical` with monotonic weights (Q40(b)); the threshold calibration and the weight table remain for the change spec (workbench R3-2); the unreliability risks ride it (R3-4).
- The validation seam is decided (R5-2); the termination and probe rules are decided (R3-6; Q55-Q58, section 2.2), and the `ratify` model-validation role with them (R3-7 closed 2026-10-18, Q58; alpha-omega ticketed `#355`).
- The hunter-side materialisation grounding is retired fully (2026-10-18, Q39; workbench R2-16).
- Round 4: eval coupling (R4-1, narrowed to the artifact translation requirement and riding the change spec); docs and supersessions (R4-2 closed 2026-10-18: the ordering-halt ADR is written (`docs/design/unit-threat-model-ordering-halt-adr.md`), the `CONTEXT.md` term pass is done, and the remaining doc tasks ride the change spec - the domain-model update, the minimal evolution-paradigm citation (the phase-1 system now has a threat model feature with a different design model from attack-tree-based models; the development of the latter should draw inspiration from the insights emerging from the former's usage), and the hygiene batch (the runtime role-key rename, the back-edge residue removal, the chain/direction wording re-check)); abduction research delivered and empirically evaluated (R4-3 + R8-4: pre-registered verdict KILL, accepted 2026-10-18; the TBSG exploration continues as ticket `#371` because the evaluated prototype has low quality; the two orthogonal disciplines (drop-decision, assumption-to-threat closure) are adopted and land with the modeller prompt material in the change spec; the boundary-record vocabulary stays an optional annotation candidate), alpha-omega deferred and ticketed (R4-4, ticket `#355`); the full CVSS base-metric adoption deferred and ticketed (`#368`).

## 7. Prototype and trials (2026-10-15)

- Prototype: a subagent executed the workflow on a real unit from a previous White Jotter run (the sample dossier: `docs/experiments/unit-threat-model-prototype/inputs/sample-unit-dossier.md`); its model and trajectory live under `docs/experiments/unit-threat-model-prototype/output/`.
  The review and the operator's feedback are folded into Q10-Q17 (workbench section 1.7); the two drops are reinstated per the then-current rule, since reframed retention-first (section 2.1).
- Trials: two live-target trials against the running comfyui deployment, one service (`Service:model-download`) and one system (`WebPresentation:custom-node-catalog::manager-shell`), with probing and episodic notes embedded in the workflow input (inputs and outputs under `docs/experiments/unit-threat-model-prototype/trials/`).
