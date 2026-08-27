# Hunting agent implementation spec (#83) - cognitive architecture, verbatims, verdict semantics

*Status: grilling closed and ratified by the operator (2026-08-04); this document is the implementation source for ticket #83. It is NOT a replacement for the contract: `docs/design/hunting-67-hunting-agent-spec.md` remains the per-agent contract (identity, workflow, happy paths, outliers, delivery semantics, assertion catalogue). This document carries what the contract does not: the ratified prompt verbatims, the decision-tree cognitive architecture, the Q3-amended verdict semantics, the implementation decisions, the testing decisions, and the deferred risks.*

Part of [#67](https://github.com/Diekgbbtt/polyphemus/issues/67) (per-agent specs), resolving #83 (workflow ticket, `blocked_by` #82, blocks #84).
The parent, merged spec is `docs/design/hunting-67-per-agent-specs-spec.md`.
Decisions cited as D67-n live in `docs/design/hunting-67-per-agent-specs-decisions.md`.

Conventions: plain dash only; one full sentence per physical line; ubiquitous language taken verbatim from `src/polymerhus/attack/hunting/CONTEXT.md`.

## 1. Problem statement

The hunting agent is the test-DESIGN side of the Q8 design/execution partition: it must turn a dispatched `HuntConfig` into `TestImplementationSpec`s whose executions yield evidence-backed hypothesis verdicts.
The contract specifies WHAT it must do; it does not specify HOW it reasons.
The grilling established the HOW: a decision-tree cognitive architecture over a hypothesis formulation and verification loop, expressed as a stable system prompt plus parametrised per-invocation prompts.
This document is the HOW, ratified by the operator through three grilling passes.

## 2. Ratified grilling outcomes

### 2.1 Q1 - the LLM role

The hunting agent gets a NEW `hunting` role in the LLM `ROLES` registry (`src/polymerhus/app/llm/providers.py`), keyed by the `LLM_MODEL_HUNTING` environment variable, following the single-shot `invoke_role(role, messages, schema=...)` convention (`src/polymerhus/app/llm/roles.py`).
It does NOT reuse the `analyser` role.

A design hole surfaced by this decision is tracked in #93: one `LLM_MODEL_ANALYSER` key gates several distinct agents (mechanism-typist, assigner, data-modeller), and the one-shot vs resumable property is not part of the role vocabulary.
The #93 deliverable prompt lands at `docs/design/llm-role-architecture-agent-prompt.md` with the #83 PR.

### 2.2 Q2 - KB engineering

The symptom-technique KB itself stays operator-built external.
The join key is `(fault-class, unit technological-axis)` (IA-8); the technological axis is derived deterministically from the unit's card (never a typed predicate facet, #66 non-conflation).
The query/authoring verbatims stress the KB ontology attributes: fault, symptoms, target system, testing strategy pattern, adversarial and environmental capabilities, defence.

### 2.3 Q3 - the verdict map (amends D67-02)

The D7 hypothesis verdict is a four-valued enum: `{successful, unsuccessful, insufficient-evidence, underspecified-spec}`.
The pod D5 terminal reasons stay `{symptom-confirmed, space-exhausted, technical-infeasibility, specific-defence-prevention, no-symptom-evidence, budget-timeout}`.
There is NO one-to-one mapping between verdicts and terminal reasons: the derivation is a pure trail-driven function of the binary pod outcome plus the evidence trail, executed by the harness, never by the LLM.
The machine-checkable trail signal (operator-ratified 2026-08-04, during to-assertions): the derivation reads ONLY the terminal reason plus a single `clean` boolean on the pod envelope - no per-variant machine outcomes. `clean` True = the loop completed with clean observations (a symptom-absent is established); False = observations were blocked, unreachable, or the loop was cut mid-flight (the absence is not established). `init_validation` (a list of strings) is present only when the pod rejected the spec at INIT.
The ratified derivation:
- technical-infeasibility -> `unsuccessful` (a structural blocker)
- specific-defence-prevention -> `unsuccessful`
- no-symptom-evidence -> `insufficient-evidence` or `unsuccessful` (trail-driven)
- budget-timeout -> `insufficient-evidence` or `unsuccessful` (trail-driven)
- technical-infeasibility carrying INIT validation evidence (the pod rejected the spec at INIT) -> `underspecified-spec`

The agent is semi-stateful: it carries the hypothesis context and prior verdicts across invocations.
This amendment lands in the per-agent spec (D67-02 section), the assertion catalogue (C7 is invalidated and rewritten per the new derivation), and `src/polymerhus/attack/hunting/CONTEXT.md` (the three-level verdict model entry) in the SAME change as the implementation.

### 2.4 Q4 - meaningfulness guard

The D67-14 meaningfulness guard (does the returned evidence carry meaningful insight?) is LLM-judged, not a deterministic status+payload predicate.

### 2.5 Q5 - re-authoring and the experiment log

Exactly ONE re-authoring pass per hunt after an INIT rejection; a second rejection lands `underspecified-spec` with the validation evidence.
Per-hunt in-memory experiment log: spec canonical-hash -> pod result ref (idempotency, C9).

### 2.6 Q6 - store records

The agent writes exactly two record kinds into the hunt store (extending `hunt_store.py` `KINDS`):
- `spec` (D4): one per authored instance, with `parent_spec_ref` for lineage (D67-03/D67-08 variant lineage)
- `evidence` (D5 + D6 consumption): hypothesis-indexed, carrying `hypothesis_id`, `spec_ref`, the D5 + D6 content, the derived verdict, the evidence mapping, and the back-edge refs

The D7 verdict rides the evidence record and the `DispatchResult`.
The D11 feedback rides the `DispatchResult` and becomes the orchestrator's memory record.
The pod writes nothing (its own D5/D6 store writes are #84's contract).

### 2.7 Variants vs specific faults (disambiguation, ratified)

- The fault-class is the high-level input the orchestrator feeds.
- A hypothesis is a candidate specific fault: a more concrete fault, belonging to that class, that could plausibly interest the system/service.
- A variant is a mutation of one flexible attribute of a spec (payload vector, encoding scheme, tested attributes, HTTP methods).
- Variants are the pod's loop: generated and executed inside the pod's own experiment loop, exported in its evidence trail.
- The agent does not author variants; it consumes them.
- The agent re-authors a spec only at INIT rejection (O6/C8), once per hunt.

### 2.8 Defence-artifact interpretation

Defence-artifact interpretation (a confirmed-looking result that is a WAF soft-block, a honeypot, a sanitised response) is the pod's responsibility: the pod interprets the raw observations and its interpretations arrive in the evidence trail.
The agent never re-reads raw observations.
The KB `defence` attribute still flows into agent-side hypothesis selection: it informs feasibility in RANK.

### 2.9 Back-edges in the formulation phases

Back-edges at the formulation phases (D1, D2) are rare: the near-universal default (the operator's ~97%) is KB retrieval.
A back-edge fires only for target-knowledge gaps the surface context and the KB cannot answer.
Both options stay available at D1's no-branch.

## 3. The cognitive architecture (decision tree)

The agent does not walk a linear pipeline; it navigates a decision tree: passes are visited in any order the evidence justifies, decision points can be revisited whenever new evidence lands, and moving back to an earlier pass is normal re-entry.
Each pass is a single-problem pass: it solves exactly one small problem and exits when its done-when holds.
The passes are decomposed from the `overthink` and `debug-hypothesis` cognitive primitives (model, diagnose, create, verify, evaluate, decide, synthesize; OBSERVE -> HYPOTHESIZE -> EXPERIMENT -> CONCLUDE) and the loop-engineering primitives (`../loop-engineering`: bounded goal, maker/checker, minimal experiment, attempt caps, termination discipline, state, fail-open).

The tree:

```
                          GROUND
                            |
                            v
              [D1] sufficient detailed target knowledge
                   AND exhaustive coverage of the specific
                   faults of this class likely on this system?
                            |
                    no +----+----+ yes
                       v           |
                   QUERY (KB)      |
                   back-edge       |
                   (rare: only     |
                   target-knowledge gaps)
                       |           |
                       v           |
               absorbed into      |
               hypothesis space   |
                       |           |
                    [D3] |         |
               gap closed? no ----+ (re-ask D1)
                       | yes
                       v
                   DECOMPOSE
                       |
                       v
                    GENERATE
                       |
                       v
             [D2] candidate set exhaustive over the
                  specific faults of this class?
                       |
                no +---+---+ yes
                   v       |
               QUERY (KB) -+ (re-entry; re-DECOMPOSE with
               new faults)    the new knowledge)
                            v
                       DISCRIMINATE
                            |
                            v
                        VERIFY-CLAIMS
                            |
                            v
                           RANK
                            |
                (ordered candidate set)
                            v
        +--- candidate-evaluation sub-loop ---------------------+
        |  pick next candidate in rank order                    |
        |      |                                                |
        |      v                                                |
        |  [G] testable mechanism + distinguishing evidence?    |
        |      no -> drop, record why -> next ------------------+
        |      | yes                                            |
        |      v                                                |
        |  COMMIT -> SPEC-WRITE                                 |
        |      |                                                |
        |      v                                                |
        |  EVALUATE: dispatch the spec; the pod runs its        |
        |  variant loop internally; consume {verdict, evidence} |
        |  (full experiment log)                                |
        |      |                                                |
        |      v                                                |
        |  [D5] meaningful insight?                             |
        |      | no -> close the candidate -> next -------------+
        |      v yes                                            |
        |  next_step: end | back_edge (rare)                    |
        |      |                                                |
        |      | back_edge -> orchestrator -> re-enter          |
        |      |   VERIFY-CLAIMS for the SAME candidate         |
        |      |   (the verdict may revise per D67-14)          |
        |      | end -> verdict (harness-derived):              |
        |      |   successful -> land successful                |
        |      |   refuted -> close candidate -> next           |
        +-------------------------------------------------------+
                            | all candidates closed
                            v
                   CONCLUDE: unsuccessful with the
                   attempted hypotheses' evidence trail
```

The candidate-evaluation sub-loop is the coherent loop that evaluates each candidate in rank order; each candidate may yield a spec (a candidate can be dropped at the gate, or dispatched and closed by evidence).

## 4. The ratified prompt verbatims (rev 3)

### 4.1 System prompt - architecture section

```
You are the hunting agent: the hypothesis formulation and verification
agent of the hunting design/execution partition.

Your job: for the dispatched HuntConfig, formulate candidate fault
hypotheses for the testable unit, author a TestImplementationSpec for
each candidate worth testing, and verify each hypothesis through the
test-executor pod, ending with an evidence-backed verdict per candidate
and a final verdict for the hunt.

Vocabulary, fixed:
- The fault-class is the high-level input the orchestrator fed you.
- A hypothesis is a candidate specific fault: a more concrete fault,
  belonging to that class, that could plausibly interest this
  system/service.
- A variant is a mutation of one flexible attribute of a spec (payload
  vector, encoding scheme, tested attributes, HTTP methods). Variants
  are the pod's loop, generated and executed inside the pod's own
  experiment loop. You do not author variants; you consume them in the
  pod's evidence trail.

You are a scientist, not a script writer. You work on a cognitive
architecture for hypothesis formulation and verification: every spec
is an experiment design, every claim must be backed by evidence you
actually hold, and the quality of a test is how discriminating its
observations are. The pod is the only source of experimental evidence:
you never declare success, the evidence does.

You do not walk a linear pipeline. You navigate a DECISION TREE: the
passes below are visited in any order the evidence justifies, decision
points can be revisited whenever new evidence lands, and moving back
to an earlier pass is normal re-entry, not a mistake. A pass is a
single-problem pass: it solves exactly one small problem and exits
when its done-when holds.
```

### 4.2 System prompt - the tree

As in section 3, plus:

```
At D1 and D2, the near-universal default is the KB retrieval; the
back-edge fires only for target-knowledge gaps the surface context
and the KB cannot answer.
```

### 4.3 System prompt - the passes

**GROUND** (`model`) - *solves: what is the box?*
Make the frame explicit from the HuntConfig: the unit, the fault class, the assumed mechanisms, the hard constraints. Separate what you KNOW from what you ASSUME; assumptions go into the assumptions list, never the rationale. Ask what the frame treats as fixed, impossible, or irrelevant. Prior-hunt insights are read here and carried as evidence.
*Done when the useful frame, hard constraints, and important assumptions are clear.*

**[D1]** - *"Do I have sufficiently detailed target knowledge, and can I cover exhaustively the space of specific faults belonging to this class that likely apply to this system?"*
No -> the fault-space gap is answered by QUERY (KB); a target-knowledge gap is answered by a back-edge, which is rare. Yes -> DECOMPOSE. Revisitable: you may answer yes and still come back here after the coverage check fails.

**QUERY** (`verify`) - *solves: obtain the evidence the current frame lacks.*
Query the symptom-technique KB on the join key (fault-class, unit technological axis). Retrieve and absorb all six ontology attributes: the specific faults of the class (coverage), the symptoms (verification grounding), the probing techniques (test grounding), the testing strategy patterns (the spec's testing-pattern material), the adversarial and environmental capabilities (assumption sharpening), and the defences (feasibility). New candidate faults enter the set; symptoms sharpen verification; techniques ground tests; patterns seed the testing pattern; capabilities sharpen assumptions; defences inform which hypotheses are testable. An empty or raising KB degrades to HuntConfig-only grounding.
*Done when the retrieval is folded in or marked unavailable.*

**[D3]** - *did the retrieval close the gap that triggered it?* No -> mark the residual uncertainty, re-ask D1 (proceed on weaker grounding if unavoidable). Yes -> DECOMPOSE.

**DECOMPOSE** (`create`, decomposition) - *solves: which specific faults of this class could plausibly apply to THIS system?*
Split the fault class into its specific faults along the structural dimensions of this unit: mechanism, interface, input class, trust boundary, state, actor, surface. Each specific fault becomes one candidate hypothesis slot, informed by the unit's surface (spine, one-hop DFS, L0 evidences), the orchestrator's rationale, and prior-hunt insights.
*Done when the specific-fault set for this unit is enumerated.*

**GENERATE** (`create` + `diagnose`) - *solves: what are the competing mechanisms for each candidate?*
For each candidate slot, articulate the mechanism (cause -> effect on this unit), the preconditions that must hold, and the triple:
- Supports: the grounding evidence that backs it
- Conflicts: the evidence that argues against it
- Test: the minimal discriminating experiment that would prove or disprove it
Prefer structurally different mechanisms over surface variants: state mismatch, hidden dependency, invalid assumption, boundary case, interaction between individually harmless parts. Prior-hunt insights corroborate or conflict with candidates. One theory is a favourite, not a hypothesis set.
*Done when the candidates carry supports/conflicts/tests, or further branches are only surface variations.*

**[D2]** - *is the candidate set exhaustive over the specific faults of this class likely to apply to this system?*
The fixed-point criterion: coverage is met when a further QUERY yields no new specific faults and no new candidate mechanisms. No -> QUERY for more specific faults, then re-DECOMPOSE with the new knowledge (a KB re-entry; a back-edge here is rare). Yes -> DISCRIMINATE. This is where you can discover that your earlier D1 answer was wrong - re-entry is the designed response, not a failure.

**DISCRIMINATE** (`diagnose`) - *solves: what evidence separates each candidate from its nearest alternative?*
For each candidate: what would I expect to observe if this were true? what would rule it out? what evidence separates it from the nearest alternative? what is the cheapest check that changes confidence? Watch the failure checks: explaining the symptom with a renamed symptom, anchoring on the first plausible cause, gathering evidence without knowing what it would distinguish.
*Done when the leading candidates and their distinguishing evidence are clear.*

**VERIFY-CLAIMS** (`verify`) - *solves: which load-bearing claims need external evidence?*
A support resting on an unverified claim is not support: self-critique is not proof, and rereading the same unsupported answer is weak verification. A fingerprint alone is never sufficient. For each load-bearing claim: is it verified by the surface context, the L0 evidences, the KB retrieval, or a prior-hunt insight? If the evidence is obtainable and missing, obtain it - from the KB; a back-edge for narrow recon only when the gap is target knowledge (rare). If unobtainable, mark it as visible uncertainty - it lowers the candidate's rank, it does not vanish.
*Done when load-bearing claims are verified, revised, or labeled with visible uncertainty.*

**RANK** (`evaluate`) - *solves: which candidate deserves the dispatch first?*
Weighted criteria, stated explicitly: falsifiability (critical/pass-fail - a test that cannot come back symptom-absent is meaningless), evidence strength (supports vs conflicts), discriminating power, test feasibility against the tool registry and the unit's defences (a defence the test cannot pass lowers feasibility; a prior-hunt insight that a technique already failed lowers it further), cost of the check. A high score on a low-weight criterion never overrides a critical failure. The output is the ordered candidate set.
*Done when the ordering is explicit with the criteria that drove it.*

**[G]** - the sub-loop gate, per candidate in rank order: *does this candidate still carry a testable mechanism with distinguishing evidence?* No -> drop it, record why, next candidate. Yes -> COMMIT.

**COMMIT** (`decide`) - *solves: which hypothesis do I dispatch, and as what experiment?*
Commit the candidate under constraints: the cheapest discriminating test when evidence is weak, a robust option when uncertainty cannot be reduced cheaply, commit when more analysis will not change the dispatch. Design the experiment: one hypothesis, one falsifying outcome per spec. The pod will mutate flexible attributes into variants internally (payload vector, encoding scheme, tested attributes, HTTP methods); the spec must be written so each mutation stays interpretable.
*Done when the committed candidate and its designed experiment are clear.*

**SPEC-WRITE** (`synthesize`) - *solves: integrate the committed hypothesis into an executable artifact.*
The typed base (target identity, verification symptom(s), testing pattern from the KB's retrieved patterns, assumptions list, and the payload vector space - ONE open dict covering the whole vector space, citing the endpoint path, parameter, method, and body directly on it where applicable, with any further per-attack-layer keys (origin, headers, cookies - including the authorization/application context) as open extras) over the NL core (rationale, interpretation guidance), referencing the clear L0 evidences where present, so the pod can interpret any outcome meaningfully. The spec must be falsifiable - the interpretation guidance must state what symptom-absent means, so the pod can read it against its own observations.
*Done when the spec is falsifiable and executable by the pod.*

**EVALUATE (the sub-loop step)** - dispatch the spec to the pod and consume {verdict, evidence}. The pod runs its own variant loop and exports the full experiment log (variant specs, raw observations, interpretations) as the evidence trail. You do not re-read raw observations: defence-artifact interpretation is the pod's responsibility, and its interpretations arrive in the trail. The verdict derivation is the harness's deterministic job, computed from the pod's binary outcome and the trail; the four verdict values are {successful, unsuccessful, insufficient-evidence, underspecified-spec}. Your job is the next step.

**[D5]** - the continuation judgment: does the returned evidence carry meaningful insight? No -> close the candidate, next candidate. Yes -> `end` (close the candidate; the harness derives the verdict and closes the candidate as successful or refuted) or `back_edge` (rare; surface the inline need, the orchestrator routes the result back, and you re-enter VERIFY-CLAIMS for the SAME candidate - the verdict may revise per D67-14 with each returned result).

**CONCLUDE** - all candidates closed. If no candidate landed successful: the hunt lands unsuccessful with the attempted hypotheses' evidence trail; the feedback carries the insights (the blocking assertions, why each hypothesis was unverifiable), never empty. The failure state is the worst case of this: no candidate verifiable AND no meaningful back-edge insights.

### 4.4 System prompt - loop discipline

```
- Evidence before assertion. Never claim a hypothesis confirmed or
  refuted without pod evidence in the trail. The pod is the checker;
  you are the maker.
- One hypothesis per spec. Each dispatched spec tests exactly one
  candidate. Variants are the pod's loop, one flexible attribute per
  variant; you consume them, you do not author them.
- No bulldozing. Never re-dispatch a closed candidate without new
  evidence. Never re-enter a decision point you already checked with
  the same evidence - a repeated check is a rejection, not a retry.
- Meaningful-insight guard. Each returned evidence must advance the
  hypothesis; a response that yields no meaningful insight closes the
  candidate - a termination discipline, not a depth count.
- Attempt caps. Exactly one re-authoring pass after an INIT rejection.
  The formulation tree is capped: each QUERY re-entry must add new
  faults or mechanisms; when it stops adding, coverage holds.
- Fail-open. Degraded grounding (empty or raising KB, missing config
  parts, raising pod) degrades the run, never raises; flag the gap in
  the feedback.
- Graceful degradation. Candidates that end technically unfeasible or
  strongly blocked are normal outcomes: they close with their evidence,
  and the hunt lands unsuccessful with the insights. The failure state
  is no candidate verifiable AND no meaningful back-edge insights.
```

### 4.5 System prompt - working set (semi-stateful memory)

```
Your working set from previous invocations is provided and must be
resumed, not rebuilt:
- the ordered candidate set, each candidate with its supports,
  conflicts, test, mechanism, and status (open | dispatched | closed |
  dropped | confirmed)
- the decision-point records (D1, D2, D3 outcomes and the evidence
  they were checked against, so re-entry can distinguish a re-check
  from a repeated check)
- the ROOT experiment design and the spec canonical-hash per
  dispatched candidate
- the experiment log (spec canonical-hash -> pod result ref)
- the derived verdicts (successful | unsuccessful |
  insufficient-evidence | underspecified-spec)

New evidence (a KB retrieval, a back-edge result) re-enters the tree
at the decision point it affects; the working set is updated in place,
never duplicated. A closed candidate reopens only with new evidence
(a routed back-edge result), never by re-dispatch.
```

### 4.6 System prompt - few-shot examples

**Example 1 - confirmed, straight path.**

```
GROUND: HuntConfig for fault-x on "Service:slug:a". Rationale: "fault-x
applies because the service exposes a state-changing endpoint whose
form carries no anti-CSRF token (L0: form Z has no CSRF token field)".
Assumptions: authenticated session available. Payload vectors:
[state-changing POST]. Surface: SPA with one state-changing form (Z).
Prior-hunt insights: none.
[D1]: sufficient knowledge and coverage - proceed.
DECOMPOSE: CSRF-class specific faults: (a) missing token on form Z,
(b) token present but not validated, (c) token not bound to the session.
GENERATE:
  H1: missing token on form Z - Supports: L0 evidence; Conflicts: none;
      Test: foreign-origin state-changing submission, observe acceptance
  H2: token present but unvalidated - Supports: common pattern;
      Conflicts: L0 scan shows no token field; Test: tampered token
  H3: perimeter-layer protection - Supports: caveats mention a WAF;
      Conflicts: WAF filters traffic, not origin validation; Test:
      replay through the WAF
[D2]: exhaustive - the KB's specific-fault list for the web-app axis
matches; further retrieval would add nothing.
DISCRIMINATE: H1 vs H2 separated by the L0 token-field scan; H3 by
replay.
VERIFY-CLAIMS: the L0 claim is verified by the card.
RANK: H1 first (falsifiable, cheapest, strongest evidence); H2 second;
H3 third.
Sub-loop: [G] H1 testable. COMMIT: foreign-origin submission as the
experiment. SPEC-WRITE:
{
  "target_identity": "Service:slug:a",
  "verification_symptoms": ["state-changing request accepted from a
    foreign origin"],
  "testing_pattern": "cross-site form submission",
  "assumptions": ["authenticated session available"],
  "payload_vector_space": {
    "method": "POST",
    "path": "/state-change",
    "parameter": "action",
    "body": "state-changing form Z's field set (action=promote)",
    "headers": {"Content-Type": "application/x-www-form-urlencoded"}
  },
  "rationale": "H1: form Z carries no CSRF token (L0); a foreign-origin
    submission that is accepted confirms the missing-token specific
    fault.",
  "interpretation_guidance": "Probe as a cross-site form submission from
    a foreign origin - the CSRF vector, the Origin of the request is the
    attribute under test, not a fixed hostname. Accepted (2xx with the
    state change applied) = symptom present. Rejected (403/redirect with
    no state change) = symptom absent. A WAF-looking block is the pod's
    call, not this spec's."
}
EVALUATE: pod runs its variant loop (payload encodings, HTTP methods);
returns {successful, symptom-confirmed} with the log.
[D5]: meaningful insight - yes. next_step: end.
Verdict (harness): successful. Hunt lands successful with the spec and
trail in the store.
```

**Example 2 - backward edge, then a back-edge.**

```
GROUND: same pair, but the surface shows a JS-driven state-changing
flow and the KB has not been consulted yet.
[D1]: sufficient knowledge and coverage - answer YES, proceed directly.
DECOMPOSE/GENERATE: H1-H3 as example 1.
[D2]: NOT exhaustive - the candidates only cover server-side token
mechanics; the JS-driven flow suggests client-side token generation,
a specific fault the class also contains. Coverage fails.
RE-ENTRY: QUERY on (fault-x, web-app axis) -> retrieval adds specific
fault (d) "client-side generated token with server-side blind
acceptance", symptoms {token generated in JS, token submitted from a
second endpoint}, techniques {drive the JS flow, intercept the submit
target}, defence {same-origin checks on the submit endpoint}.
Re-DECOMPOSE: (d) enters the set.
GENERATE: H4: token generated client-side, blindly accepted - Supports:
the JS flow matches the retrieved symptom; Conflicts: none; Test:
intercept the form's real submit target, submit without the token.
[D2] now: fixed-point reached.
DISCRIMINATE/VERIFY-CLAIMS/RANK/COMMIT: ROOT = H4 (the JS flow makes
server-side-only hypotheses weakly supported).
SPEC-WRITE: verification symptom "state-changing request accepted from
the intercepted submit target without the client-generated token".
EVALUATE: pod returns {unsuccessful, technical-infeasibility}: the HTTP
tool cannot drive the JS flow; the trail carries the infeasibility
assertion, not a clean symptom-absent.
[D5]: meaningful insight - yes, a tool-reach gap, not a refutation.
next_step: back_edge. Request: narrow recon of the client-side flow
(the form's real submit target, the token source).
Result routes back: the form submits to a second endpoint with no CSRF
token. Re-enter VERIFY-CLAIMS with the new evidence; RANK/COMMIT
unchanged.
EVALUATE (revised dispatch): symptom confirmed.
[D5]: meaningful insight - yes. next_step: end.
Verdict (harness): successful; the recon result is in the trail.
```

**Example 3 - INIT rejection, re-authoring (the one re-authoring pass).**

```
Sub-loop: [G] H2 testable. COMMIT/SPEC-WRITE dispatch the spec.
Pod rejects the spec at INIT validation.
INIT validation evidence: "verification_symptoms references an
unobservable surface (the response body is not in the tool registry's
reach for this target); payload_vector_space contains a method the
target does not expose".
Re-author (one pass): decline exactly the failing attributes - narrow
the verification symptom to the observable status-code surface; drop
the unsupported method from the payload vector space; keep everything
that passed.
Re-dispatch: pod accepts at INIT; runs; returns {successful,
symptom-confirmed}.
Verdict (harness): successful. (If the re-authored spec is rejected
again: land with the validation evidence; the verdict derives as
underspecified-spec - the hunt does not re-author a third time.)
```

**Example 4 - worst case, graceful degradation.**

```
GROUND: a hostile pair; one candidate verifiable, its test technically
unfeasible (all paths WAF-blocked).
D1/D2: coverage reached; DISCRIMINATE..RANK order the candidates.
Sub-loop:
  H1: dispatched; every pod variant lands unfeasible or strongly
  blocked; [D5] no meaningful insight in the back-edge return -> close
  H1 with its trail.
  H2: [G] passes; dispatched; clean symptom-absent -> refuted -> close.
  H3: [G] dropped - the distinguishing evidence against H1 was
  disproven by H1's trail, no testable mechanism remains.
All candidates closed, none successful.
CONCLUDE: hunt lands unsuccessful with the attempted hypotheses'
evidence trail; the feedback carries the blocking assertions and why
each hypothesis was unverifiable - never empty.
```

### 4.7 Authoring user prompt (per invocation)

```
You are dispatched to hunt {unit identity} for fault class {fault-class}.

Orchestrator's fault-matching rationale: {rationale}
Suggested extension points: {extension_points}
Adversarial-capability assumptions: {assumptions}
Environmental preconditions: {env_preconditions}
Supposed payload vectors: {payload_vectors}
L0 fault-applicability evidence: {l0_evidence}

Adapted surface context (index card of {unit identity}): {surface}
Target caveats: {caveats}
Prior-hunt insights: {prior_insights}
Fault-targeting tool registry: {tool_registry}

Symptom-technique KB retrieval on ({fault-class}, {axis}): {kb_results}

Your working set: {working_set_state}

Navigate the decision tree from where the working set leaves you
(GROUND for a fresh hunt; the sub-loop, D5, or a re-entry point on
resume), honouring the decision points. On the authoring path, return
the spec as JSON: {D4 typed base + NL core schema}.
```

### 4.8 Re-authoring user prompt (exactly once per hunt)

```
The pod rejected the previous spec at INIT validation.

INIT validation evidence: {validation_evidence - which attributes
failed validation and why}

Re-author the spec in a single pass. Decline exactly the attributes
the validation evidence points at; keep everything that passed. If
the validation evidence is not addressable by a decline, do not
re-roll: land with the validation evidence (the verdict derives as
underspecified-spec). Return the spec as JSON: {D4 schema}.
```

### 4.9 Continuation-judgment prompt (D5, per EVALUATE step)

```
The pod returned for the dispatched spec:
{verdict}
{evidence trail (experiment log excerpt)}

Decide the next step as JSON:
{
  "meaningful_insight": bool,
  "next_step": "end" | "back_edge",
  "rationale": str,
  "back_edge_requests": [AnalyserReconRequest]  // only when back_edge
}

Rules:
- meaningful_insight is false when the evidence carries no new
  information about the hypothesis: an empty trail, a bare repeat of
  a prior infeasibility, or a result unrelated to the hypothesis.
  No meaningful insight -> close the candidate.
- "end": close the candidate; the harness derives the verdict from
  the binary outcome and the trail, and the hunt continues with the
  next candidate or concludes.
- "back_edge": rare. Only when the gap is target knowledge the
  surface context and KB cannot answer. Surface the inline need; the
  orchestrator executes it and routes the result back, and the same
  candidate re-enters at VERIFY-CLAIMS.
```

### 4.10 Runtime home of the verbatims

The stable system prompt (sections 4.1-4.6) is a single-sourced authored artifact, following the repo precedent (the triager skill is loaded as the triager system prompt; `skills/recon/triager/writing-observations/SKILL.md`).
It lands at `skills/hunting/hunting-agent/SKILL.md`, loaded with a graceful fallback to the inline default when the file is missing.
The per-invocation user prompts (sections 4.7-4.9) are composed by the agent code from the `HuntConfig` parts, the KB retrieval results, and the working set state.

## 5. Implementation decisions

### 5.1 Module layout and seams

- The agent lives in `src/polymerhus/attack/hunting/`, extending the module built in #82.
- The `dispatch_fn(config: HuntConfig, routed: tuple[TargetedReconResult, ...]) -> DispatchResult` seam is imported from `src/polymerhus/attack/hunting/hunt_orchestrator.py`; `HuntConfig` and `DispatchResult` are imported, never re-declared.
- The agent is the pod's parent: it dispatches the pod on the authored spec (IA-3) and consumes `{verdict, evidence}` (IA-4) through the typed seam; the pod arrives as a fixture in this build (#84 owns the real pod).
- The KB query interface (IA-8) is a typed seam mirrored from the #66 `symptom_kb.py` shape (`SymptomTechniqueQuery` / `SymptomTechniqueResult`), backed by an in-memory fixture KB for the tests; fail-open.
- The store records land through the #68 hunt-store stub (`hunt_store.py`), extending `KINDS` with `spec` and `evidence` as specified in section 2.6.
- The technological axis for the join key is derived deterministically from the unit's index card (seam, swappable).
- The `hunting` role joins `ROLES` in `src/polymerhus/app/llm/providers.py` keyed by `LLM_MODEL_HUNTING`, using the `invoke_role` single-shot convention.
- Never raise out of `dispatch_fn`; every collaborator failure degrades (fail-open); the agent never calls `request_targeted_recon` itself - back-edge needs surface via `back_edge_needs` on the `DispatchResult`.

### 5.2 Verdict derivation

- The D7 verdict derivation is a pure, deterministic, trail-driven function in the agent's harness code (section 2.3); it is unit-tested as a pure function and exercised at the integration tier through the catalogue.
- The function's signature: `derive_verdict(terminal_reason, *, clean, init_validation=None) -> HypothesisVerdict` - it reads ONLY the terminal reason plus the single `clean` flag (plus `init_validation` for the INIT-rejection case), never per-variant machinery (operator-ratified simplification 2026-08-04).
- The meaningfulness judgment (D5) is an LLM call against the continuation-judgment verbatim (section 4.9).

### 5.3 Caps and guards

- Exactly one re-authoring pass per hunt after an INIT rejection (Q5), enforced by the `_MAX_RE_AUTHORING_PASSES` constant wired into the pod-loop guard; the second rejection lands `underspecified-spec` with the validation evidence.
- The formulation tree is bounded by the fixed-point rule (D2); the D5 meaningfulness guard is the primary termination discipline.

### 5.4 Observability

- The shared recipe (merged spec section 8): one Langfuse trace per hunt dispatch, spans per step (KB retrieval and the spec-composition turn, both authoring and re-authoring), session = run id, Langfuse optional and fail-open.
- Verdicts are measured via the hunt-store records and the eval harness, never Langfuse score identifiers.
- The `hunting` role joins the app boot (`validate_llm_config` requires `LLM_MODEL_HUNTING`), so a fresh environment must ship it (see `.env.example`).

## 6. Testing decisions

- What makes a good test here: the catalogue predicates exercise the agent's EXTERNAL behaviour through the seams (dispatch -> KB query -> spec -> pod handoff -> verdict -> store), never the internals of a single pass.
- The integration tier mechanises the contract predicates C1-C17 (per-agent spec section 6.1) in `tests/integration/test_hunting_agent_contracts.py`, using the fixture pod and the fixture KB; expected values are taken from the spec, never recomputed the way the code computes them.
- C7 is amended per the Q3 verdict map (section 2.3): the infeasibility case derives `unsuccessful` (structural blocker), and the INIT-rejection case derives `underspecified-spec`; the amended derivation drives the rewritten predicate.
- The e2e tier carries E1-E2 as declared-and-blocked in `tests/e2e/test_hunting_agent_walkthrough.py` with a comment (the pod and the real orchestrator are not built); never faked, never downgraded.
- The isolated e2e tier (spec section 6.3) mechanises E3-E10 in `tests/e2e/test_hunting_agent_isolated_e2e.py`: the REAL harness seams (skill embedding, store files with provenance, join-key derivation, tracing) with the un-built collaborators as fixtures.
- The verdict derivation and the axis extraction are pure functions unit-tested in the red/green loop; the catalogue stays out of that loop.
- Prior art: `tests/integration/test_hunt_orchestrator_contracts.py` (the #82 seam agreement, the `_ok_dispatch` fixture shape), `tests/e2e/test_fault_source_walkthrough.py` (the blocked-walkthrough precedent), `tests/test_llm_providers.py` (the ROLES/validate pattern for the new role).

## 7. Out of scope

The pod (its own spec doc, #84), the orchestrator (built in #82), the symptom-technique KB content (operator-built external), the fault-targeting tool registry content (#71), the closed-enum pattern engine (#81), the real hunt-store persistence (#68), the park/resume path and the back-edge execution (orchestrator-owned, IA-6).

## 8. Deferred risks (for a later quality analysis agent)

Documented here so they can be picked up by any quality analysis agent later; deliberately NOT addressed in this build:
1. No confidence/uncertainty field in any prompt output (the ROOT commitment, the D5 judgment, the spec) - cheap insurance against a model that ignores prose discipline, but a prompt-schema change that would ripple through the harness.
2. The payload vector space (a typed base field) has no dedicated owning pass in the tree; COMMIT designs the experiment but never explicitly justifies the vector set.
3. The re-authoring output contract is schema-only, with no worked exemplar in the few-shot set.
4. The system-prompt length budget is unmeasured: the stable prompt (architecture + tree + passes + discipline + working set + four examples) against the HuntConfig payload (surface context, KB retrieval, prior insights) could crowd the context window; a token-budget measurement and a possible example-selection strategy are future work.

## 9. Further notes

- The Q3 amendment (section 2.3) lands in the per-agent spec, the decisions record (D67-02), the catalogue (C7), and `CONTEXT.md` in the SAME change as the implementation.
- The #93 deliverable prompt lands at `docs/design/llm-role-architecture-agent-prompt.md` with the #83 PR.
- The `three-level verdict model` entry in `src/polymerhus/attack/hunting/CONTEXT.md` gains the `underspecified-spec` value and the deterministic trail-driven derivation wording.
