# Autonomous Vulnerability-Discovery System — Design Document

*Status: pre-MVP design consolidation. This document captures the system as converged through design discussion. It is an explanation-and-reference document: the first half explains the architecture and why it is shaped this way; the second half is a referenceable register of design decisions, the MVP boundary, open points, and risks. Decisions are tagged `DD-n`, open points `OP-n`, risks `R-n` for cross-reference.*

---

## 1. Purpose and scope

The system performs **autonomous discovery of complex, composed attack chains** against a deployed software target. Its product is not a list of findings but a **maintained threat model** — a recursive attack-chain graph that is grown, verified against the live target, and kept current as the target evolves `[DD-1]`.

The present design targets the discovery phase. The **pentest-realism layer** — external/out-of-scope assumptions, impact triage, live-engagement state effects — is explicitly deferred to a later phase that wraps the discovery core `[DD-2]`. The framing is therefore closer to sophisticated, autonomous, multi-step vulnerability research than to a turnkey penetration test, which keeps the founding concern (single-component testing yields an impoverished, context-free threat model) answerable: the graph reasons about a component *in the context of the deployed system*.

## 2. System overview

The organising principle is **separation of concerns by soundness** `[DD-3]`. Three layers cooperate, each doing only what its epistemics permit:

- The **LLM (planner) layer** perceives the target and *hypothesises* — it proposes faults, symptoms, techniques, and assumptions. It is creative and unsound, so it never has the last word.
- The **symbolic / structure layer** owns the graph: node and edge typing, the dataflow of objects between steps, status roll-up, deduplication, and identity. It is sound but only as complete as what it is given.
- The **execution oracle** runs a technique against the live target and is the sole source of ground truth.

A fourth principle cuts across all three: **token minimisation** `[DD-4]`. It is not merely an efficiency goal; it drives concrete structural choices — encapsulated verification pods, evidence-to-capability mapping for noise analysis, and budget-bounded termination.

The model stack favours **open-weight models**, optionally fine-tuned, in a heterogeneous arrangement where high-reasoning turns (maintaining the threat model) may use frontier models and execution-heavy turns use cheaper open models `[DD-5]`. Three components were deliberately removed: BRON (CWE already references related CAPEC), a learned prioritiser (a bad ranking only wastes budget and never fabricates a finding, since execution validates), and MulVAL specifically — though the *principle* of a sound derivation layer is retained `[DD-6]`.

## 3. The threat-model graph

### 3.1 One recursive grammar

The threat model is a **single recursive attack-chain DAG** `[DD-7]`, rooted at an abstract end impact and bottoming out at legitimate actions. There are not two static regions; there is one grammar whose pattern repeats at every level `[DD-13]`. The recurring pattern is:

> an **objective** is served by a **technique**, which requires one or more **requirement-faults**; each requirement-fault manifests as one or more **symptoms** (lower-level objectives); each symptom is served by a further technique; and so on, until a technique is a **legitimate action** that needs no fault beneath it.

This is the **three-kind cycle** `objective → technique → requirement-fault → objective(symptom) → technique → …`. The kinds specialise by region but the cycle is uniform `[DD-13]`:

- In **region 1** (the exploit path) the objective is the **impact/goal**, the technique is an **exploit** (emits a capability, `achieves` the objective), and the fault is a **requirement**.
- In **region 2** (inside a verification pod) the objective is a **symptom** — the region-2 analog of a goal, *a way the parent requirement-fault manifests in a specific attack-surface area or fashion* — the technique is a **probing technique** (emits evidence, `probes` the symptom), and the fault is again a **requirement** of that probing technique.

So **all faults are requirements**; "symptom" is a distinct **objective node**, not a role a fault plays. The "two phases" (requirements above, symptoms below) are a **local pattern instantiated at each requirement-fault boundary**, not a global bisection of the graph.

### 3.2 Nodes

- **Objective** — what a technique is trying to bring about. In region 1 these are the **impact** and its **goals**; in region 2 they are **symptoms** (a way a requirement-fault manifests, in a specific attack-surface area or fashion). Symptom is the region-2 analog of a goal, *not* a kind of fault `[DD-11, DD-12]`.
- **Technique**, in exactly two families `[DD-9]`:
  - *Exploit* — emits a **capability** and `achieves` an objective (region 1).
  - *Probing* — emits **evidence** and `probes` a symptom (region 2). The leaf-most is an atomic, directly-implementable **legitimate action**.
- **Requirement-fault** — a hypothesised weakness, **always a requirement** of the technique above it. Fault and capability are **merged into one node** `[DD-10]`: the capability is the object the fault *emits* on its requirement edge. The capability is edge-relative — a capability toward an exploit, evidence toward a probe. Faults are **not reducible to CWEs**: many are bespoke developer-error or trust-assumption weaknesses with no clean catalogue entry (see §3.5).

### 3.3 Edges

Edges are **typed by role and carry typed data objects** `[DD-16]`, layering a data flow on top of the attack-engineering control flow. The role types:

- `requires` — a requirement-fault is required by the technique above it; the edge carries the emitted object (a **capability** toward an exploit, **evidence** toward a probe).
- `is-symptom-of` — a symptom is a way an upstream requirement-fault manifests, in a specific **attack-surface area** or **fashion** `[DD-12]`. Connects a symptom directly to the requirement-fault it manifests (no technique between). This replaces the earlier "cause" framing.
- `achieves` / `probes` — an exploit `achieves` an objective; a probing technique `probes` a symptom.

Requirement and symptom are now **separate node kinds**, not edge-relative roles of one fault node `[DD-11 amended]`: a requirement-fault's verification objective is a *distinct* symptom node beneath it, which removes the earlier "requirement above / symptom-root below" duality on a single node.

### 3.4 Structural invariants

- **Alternation** `[DD-8]`: technique and fault strictly alternate. Every *non-leaf* technique requires ≥ 1 fault; **leaf** techniques are legitimate actions and require none. Leaf-ness is *provisional* — a failed leaf can be demoted by minting a requirement beneath it (see assumption-promotion).
- **Composite faults** `[DD-14]`: a fault that decomposes (e.g. "identifier returned in mutation response" = "mutations allowed" AND "identifier in success response") is an AND of sub-faults *mediated by a verification technique*, so no fault-to-fault edge ever appears.
- **Capabilities are never nodes** `[DD-10]`: a capability is only ever the object a requirement-fault *emits*. The reflection must reject any abduced "attacker can X" and re-express it as a fault that emits X; if nothing yields it and it is benign or external, it is omitted, not nodified. (This guard prevents a capability masquerading as a fault, which would hide the real weakness and bake in an exploitation fashion.)
- **Instances are fault-driven, not technique-refined** `[DD-32]`: a general probing technique does not decompose into instance-techniques (no technique→technique edge). It **requires** its abduced faults (OR across alternative grounding faults, AND within a composite); a "specific instance" of probing is that probe grounded on a chosen fault, appearing one cycle down inside that fault's own symptom→probe sub-cycle. Requirement edges therefore carry AND/OR, like decomposition edges.
- Expansion is **backward-chaining / regression planning** `[DD-15]`: an unmet objective spawns a technique, whose unmet requirement-faults spawn symptoms, recursively, stopping at a legitimate action. The *generative substrate* for that expansion is specified in §3.5.

### 3.5 Hypothesis generation: prior-guided anatomy abduction `[DD-32]`

The single most important choice for attack sophistication is **what the planner generates from**. The system does **not** drive generation by recombining a curated catalogue of techniques/CWEs; it drives generation by **abducing faults from a model of the target's anatomy** — its components, data flows, trust boundaries, and the *distribution of mistakes developers typically make building this kind of system* (violated invariants, unstated trust assumptions, single failure modes). Techniques are then **consequences** of an abduced fault, not primitives retrieved from a list. Properties:

1. **Fault-first, technique-derived.** Once a fault is named (e.g. "downstream services trust the gateway-injected identity header"), the technique to exploit it usually falls out trivially. Creativity lives in fault/symptom abduction; the probing-technique layer beneath is largely mechanical materialisation. Concretely, a general probing technique does not branch into instance-techniques — it requires its abduced faults, and each fault drives its own sub-cycle (see the "instances are fault-driven" invariant in §3.4). A symptom may also be probed by several *fashions* (alternative probing techniques) with different requirement-fault footprints; the planner prefers the stealthiest/cheapest fashion.
2. **Faults are richer than CWEs.** The fault vocabulary is the model's implicit prior over how systems betray their invariants — bespoke trust-assumption and developer-error weaknesses, most of which have no clean CWE. CWE/CAPEC become **post-hoc classification labels** applied after discovery, not the generative driver `[DD-6 amended, DD-28 amended]`.
3. **Uses the LLM at its actual strength.** Abduction composes the model's full pretraining prior (codebases, bug reports, postmortems) with the specific system; a catalogue under-uses that prior by restricting retrieval to a curated subset.
4. **Placement.** The creative engine is **symptom/fault abduction inside the verification pods** (and at the region-1 requirement layer). A symptom such as "identifier disclosed in the GraphQL area" is already an anatomy-derived hypothesis about *where and how this specific system leaks*.
5. **Prior-guided for budget.** Abduction is high-recall / low-precision, which fights token-minimisation `[DD-4]`. It is therefore **likelihood-ranked**: hypothesise the *most plausible* developer mistakes first ("what would a competent-but-rushed team most likely have gotten wrong here?"), and let the oracle prune cheaply — not an unbounded brainstorm.
6. **Domain-scoped.** This wins where sophistication lives in the *fault* and the technique is trivial — logic, auth, and trust-boundary bugs in web/SaaS/OSS, the system's target domain. It does **not** transfer to domains where sophistication is irreducibly technique-craft (binary exploitation, gadget chains, crypto) `[scoping risk, R-2 amended]`.
7. **Ceiling.** The bound moves from catalogue-coverage to **model-prior coverage** — a far higher ceiling, but still finite: abduction cannot conjure a fault class the model has no conception of, and does not invent new attack *physics* `[R-2]`.
8. **Cost to the rest of the system.** Bespoke faults may have **no catalogue probe** (the probing technique must be synthesised, not retrieved) and **no clean identity** (two bespoke faults being "the same" is a semantic judgment, not a CWE match), which makes node identity `[OP-2]` harder. The retrieval/IR pipeline is demoted from *generative driver* to a **grounding and probe-materialisation aid**.

## 4. Verification pods and lifecycle

### 4.1 Pods and the operational boundary

Symptom verification is delegated to a **separate agent pod with its own lifecycle**, spawned at each requirement-fault that needs verifying `[DD-19]`. The boundary **recurses** — a nested pod at each requirement-fault — so "two phases" is the local contract at every boundary, not a single global cut.

Pods are **encapsulated**: leaves generate raw evidence internally, the pod rolls it up, and only the pod's top node **exports a consolidated `{verdict, emitted-object}`** across the boundary. The emitted object then maps to the capability that the parent exploit consumes, and this **evidence-to-capability mapping along the traversal** is what enables noise analysis and prevents token waste `[DD-17]`.

A consequence to accept deliberately: cross-branch correlation now happens at the **capability (boundary-object) level, not the probe level** `[DD-20]`. A probe in one pod cannot satisfy a probe in another; only consolidated capabilities cross branches. This is the intended trade for token-bounded modularity.

The pod's internal loop: **elicit a probing technique → build its attack (sub-)tree → execute → on failure, elicit another**, bounded by budget `[DD-21]`.

### 4.2 Status and roll-up

Faults carry a lifecycle: **hypothesised / verified / infeasible** `[DD-22]`. Roll-up `[DD-23]`:

- **OR-success** — any one successful symptom branch verifies the upstream requirement; its evidence (as a capability object) traverses up to that requirement-fault.
- **AND** — a composite fault is verified only when all its sub-faults verify.
- **Infeasible** — a requirement is `infeasible` when its symptom achieve-set is exhausted *or* the sub-DAG budget is spent; the negative verdict propagates upward identically to a positive one. Budget therefore doubles as the termination oracle, consistent with `[DD-4]`.

### 4.3 Deduplication

A requirement-fault is a **handle to a possibly-shared verification module** `[DD-24]`. If two exploits require the same fault, the second reuses the first's sub-DAG rather than re-dispatching it. This makes **node/module identity mandatory** (it must be defined over the `{fault, emitted-object-type}` pair, not the label) and requires a **"verification-in-progress" state** so parallel consumers block-and-reuse rather than re-dispatch.

### 4.4 Assumptions

**Assumptions are first-class node properties** on techniques and requirement-faults `[DD-18]`, expressed as **machine-checkable predicates over typed objects** (e.g. on a "JWT identifier disclosed" fault: *the identifier equals the JWT `sub` claim*). Assumptions are the structured form of the graph's known incompleteness — latent, un-nodified preconditions.

The **assumption-promotion algorithm** `[DD-27]` (deferred, see §6) handles a *verified-but-failed* exploit: when every requirement is verified yet the exploit's expected capability is not obtained, a dedicated agent selects the **weakest violated assumption** and **branches a new requirement-fault** beneath the failed technique (always a requirement — upward, AND-conjoined — never a symptom). It requires structured, post-condition-level failure reporting and a cascade budget. This is the only operation that *grows the requirement side* from a failure, so its typing is load-bearing even though the algorithm itself is deferred.

### 4.5 Memory and evolution

Failed branches are remembered keyed on the **failed precondition** (revival keys), and re-testing is **change-driven** rather than continuous: a target change re-activates or prunes only the branches whose preconditions it touches `[DD-26]`.

### 4.6 Dissemination (noted for later)

A **symptoms-exploration / dissemination mechanism** `[DD-25]`: feedback released from a pod, analysed by a dedicated agent, that disseminates details relevant to all other tree nodes. Design pending (`OP-7`).

## 5. Evaluation

Discovery quality is measured with **composed Vulhub stacks** (real CVEs, natural faults, controllable composition) as the workhorse, plus one cloud-goat target as the heterogeneity/realism showcase; **context is treated as the independent variable** so the context-dependence result is the headline `[DD-30]`. Real-CVE reproductions provide external validity; seeded faults provide recall scale; ground truth is pre-registered. The execution oracle gives precision (validated-finding false-positive rate) directly; recall is measured against the known/seeded set; a capture–recapture estimate across the two search directions gives a coverage proxy. A **judge-LLM validation** of proposed faults/symptoms is deferred `[DD-31]`. Reporting (when execution is present) uses CWE/CAPEC classification, minimal cut sets (BDD/ZDD) and CVSS-environmental impact `[DD-28]`. Prompt injection of the agent via retrieved content is out of scope for the MVP `[DD-29]`.

## 6. MVP boundary

**In the MVP.** The recursive grammar (§3); two technique families; merged fault+capability with dataflow objects; assumptions as properties; verification pods with the hypothesised/verified/infeasible lifecycle and OR/AND/budget roll-up; memoised shared sub-DAGs; episodic memory; and the **execution oracle inside pods** (probes are executed). Executing probes returns the probe-based stop rule that a purely planning-only build would lack.

**Deferred (post-MVP).** Assumption-promotion `[DD-27 / OP-6]`; the dissemination mechanism `[DD-25 / OP-7]`; judge-LLM validation `[DD-31]`; exhaustive graph-resolution algorithms; the pentest-realism wrapper `[DD-2]`; any learned prioritiser; cut-set-based reporting refinement.

## 7. Open points

- **OP-1 — Roll-up function.** OR-success is specified; the **AND** and **infeasible-by-budget** halves are not yet precise. This is the highest-value next spec: the lifecycle is inert without it and the oracle pass cannot propagate a verdict upward.
- **OP-2 — Node/module identity.** Mandatory now (deduplication). Needs a precise definition over `{fault, emitted-object-type}`; harder under `[DD-32]` because bespoke (non-CWE) faults have no catalogue key, so "same fault" becomes a semantic judgment.
- **OP-3 — Object/capability type vocabulary.** Mandatory for dataflow matching and for machine-checkable assumptions; not yet enumerated.
- **OP-4 — Search/expansion policy + budget governor.** With the catalog demoted to a prior and the probe-stop only present where execution runs, the budget is the real termination guarantee. An AO\*/MCTS policy over the AND-OR DAG, with episodic memory as a transposition table, is the candidate.
- **OP-5 — Symptom coverage.** The live incompleteness question: did we enumerate *enough* manifestations of a fault? (See `R-1`, `R-6`.)
- **OP-6 — Assumption-promotion.** Attribution/weakest-assumption heuristic, structured failure-reporting format, cascade budget. Deferred.
- **OP-7 — Dissemination mechanism** `[DD-25]`. Design pending.
- **OP-8 — Failure→root-cause attribution ordering.** Which assumption to suspect first.
- **OP-9 — "Legitimate action" floor predicate.** Operational test for "needs no weakness to perform" / actionable granularity.
- **OP-10 — Evaluation harness + ground-truth set.** Implementation and pre-registration.
- **OP-11 — Target input model schema.** Component/data-flow graph, versions, trust boundaries — the substrate the DAG roots in.
- **OP-12 — Recon→symptom catalog schema.** Normalised evidence format the planner consumes.

## 8. Risks

- **R-1 — False negatives dominate.** Execution catches unsoundness (a hallucinated branch fails when run) but nothing definitively catches a branch never imagined. Mitigations: bidirectional (requirement/symptom) search, capture–recapture coverage proxy, human attention at the unverified frontier. This is the risk the evaluation must speak to.
- **R-2 — Generative ceiling (model-prior bound).** Under `[DD-32]` the bound is no longer catalogue coverage but **model-prior coverage** — a far higher ceiling. Novelty is *combinatorial and system-specific* (trust-violations the model can compositionally reason about), not the invention of new attack *physics*; the system stays blind to fault classes outside the model's prior.
- **R-11 — Abduction is low-precision / domain-scoped.** Anatomy abduction is high-recall, low-precision, so cost-per-confirmed-finding rises against `[DD-4]` unless it is strictly likelihood-ranked. It is also domain-scoped (logic/auth/trust-boundary bugs); applied to technique-craft domains (binary, crypto) it would under-generate. Do not over-claim the creativity win beyond the target domain.
- **R-3 — Budget-bounded termination.** Termination is by budget and deduplication, not structural exhaustion; without a disciplined governor (`OP-4`) the recursion and any promotion cascade can expand cost without bound.
- **R-4 — Inherent blind spots.** Business-logic/economic flaws (recoverable only if the planner hypothesises the lever and validates by instantiation), TOCTOU/races (recoverable via a replay oracle, not via the static graph; destructive non-monotonicity remains out), novel primitive classes, second-order/deferred-effect (in tension with effect-driven generation), and spec-vs-intent gaps where code is correct but policy is wrong.
- **R-5 — Identity errors.** A wrong identity definition silently degrades the DAG into a duplicate tree, breaking deduplication, cross-branch correlation, and cut sets.
- **R-6 — LLM symptom-linking.** Contextualising the planner with the upstream fault makes off-topic hallucination a weak worry; the residual risk is **coverage** (topical ≠ complete), bounded by knowledge-base coverage. The deferred judge-LLM validates correctness, not coverage.
- **R-7 — Scope/breadth.** The assembled system is plausibly several theses; the MVP boundary (§6) must be enforced.
- **R-8 — Dual-use / disclosure.** Real findings against real OSS trigger coordinated-disclosure obligations; a disclosure and dual-use plan is required.
- **R-9 — Evaluation validity.** Seeded faults are "cleaner" than wild ones (overfitting to seeding artifacts); single-app targets cannot exhibit the context-dependence result, so at least one heterogeneous target is load-bearing.
- **R-10 — Prompt injection.** Out of scope for the MVP and recorded as an accepted limitation; a self-injectable agent is a known gap to close later.

## 9. Glossary

- **Fault** — a hypothesised weakness; merged with the capability it emits when exploited.
- **Capability** — the typed object a fault emits toward an exploit; the attacker-held asset.
- **Symptom** — a way a fault manifests in a specific attack-surface area or fashion; an `is-symptom-of` child of a requirement-fault.
- **Exploit technique** — emits a capability, drives toward impact.
- **Verification technique** — emits evidence, confirms a fault; the leaf-most is a legitimate action.
- **Legitimate action** — a directly-implementable technique requiring no fault beneath it; the recursion floor.
- **Pod** — an encapsulated agent process verifying one requirement-fault, exporting `{verdict, emitted-object}`.
- **Assumption** — a machine-checkable predicate a node relies on; a latent un-nodified precondition; promotable to a requirement-fault on failure.
