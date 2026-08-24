# The polymerhus Domain Model - the reasoned ontology

*Canonical project ontology for polymerhus, an autonomous web-application vulnerability-discovery system.*
*This is the source from which per-context glossaries are later derived; it is not itself a glossary.*

This document states the primitive concepts of the domain, argues why they are the primitives, shows how they relate, and names the invariants that bind them.
It reasons from first principles and then grounds each claim in the running code (`path:line`) or a ratified decision (`L1D-*`, `NM-*`, `AMV-*`, `DD-*`, commit hashes).
Where a design document contradicts the code, the code wins and the correction is stated inline; the two live design references are `recon-pipeline-design.md` (Layer 0) and `l1-domain-model-catalogue.md` (Layer 1, which itself supersedes parts of `service-system-model-design_1.md`).
Concepts that are designed but not built are marked as such explicitly, in the same scrupulous spirit the recon design keeps.

---

## 1. The two questions this ontology answers

An ontology for an autonomous vulnerability finder must answer two questions that a human pentester never has to answer out loud.

First: what are the irreducible concepts of vulnerability discovery against a web application - the atoms, not the tools or the pipeline stages?

Second: what further concepts does *automating* that procedure force into the open - the things a human holds implicitly in their head and that a machine must make first-class or it cannot reason at all?

Section 2 answers the first from first principles.
Section 3 derives the second, and grounds each in a place where its absence manifested as a real defect in this project's own history.
Sections 4 through 8 integrate the two into one model, name its actors, state its binding invariants, and mark where it is honestly silent.

---

## 2. The primitives of vulnerability discovery

### 2.1 The surface and its atom

Vulnerability discovery begins with a black box the tester does not control and reconstructs from the outside.

The *attack surface* is the total set of loci at which the tester can present input to that box and observe a consequence.

The atom of attack surface is not "the application" and not "an endpoint" alone.

The irreducible unit is a **locus where externally-controllable input crosses into the system and the system acts on it**: an endpoint together with the parameter or header that carries the input.

The Layer-0 store realises this atom as a small fixed set of typed node labels (`src/polymerhus/recon/domain/curator.py:27-31`): `Domain, Subdomain, IP, Port, Service, DNSRecord, BaseURL, Endpoint, Parameter, Header, Certificate, Technology, Secret, Traceroute, ExternalDomain`.

A bare `Endpoint` is a reachability fact; input-carrying capability is expressed by the `Parameter`/`Header` nodes that hang off it, which is exactly why a fault signature keys on the *reachability of a user-controllable input into a sink*, not on a lone endpoint (`service-system-model-design_1.md` §9.5).

The truth condition of an L0 node is mechanical and narrow: it exists because a tool witnessed it at a moment in time.

### 2.2 Observation, inference, hypothesis - three kinds of claim

These three are distinct epistemic species, and conflating them is the most common ontological error the model exists to prevent.

An **observation** is a directly-witnessed fact about the surface, defeasible only by the surface changing under it: "this path returned 200", "this `Server` header is present".

An **inference** is a claim about structure that was never directly visible and had to be reconstructed: "these endpoints constitute the checkout service", "this service sits behind that WAF".

A **hypothesis** is a falsifiable claim about a *fault* that has not yet been tested: "this service trusts that field to have been authorised for this user, and role R can violate that".

The project's node named `Observation` (`src/polymerhus/recon/domain/types.py:18-25`) is, confusingly, not an observation in this sense - it is a *low inference*: an adversarial natural-language insight the triager reads out of tool output, explicitly not a restatement of a primitive (the writing-observations discipline, memory `observations-vs-attack-surface-primitives`).

Genuine observations live below it, as the typed L0 nodes themselves.

Inference proper is the whole of Layer 1 (Section 4).

The three form an **escalating epistemic ladder**: an observation is witnessed, an inference is reconstructed from observations, and a hypothesis is a falsifiable claim built on inference about a fault that could exist - each rung is a weaker, more defeasible, and more adversarially valuable claim than the one below it.

The hypothesis is a first-class concept in this ontology, modelled in full in Section 2.6.

It is a **phase-3 primitive**, not graph structure: the fault-hypothesis lives in the reasoning of a testing technique during the vulnerability-probing phase, and is never written to the L0/L1 graph.

The operator has deliberately chosen to let the ontology name and lead this primitive even though the phase that would exercise it is not yet built (`NM-8`).

Its nearest *built* realisation today is a single concrete instance of the primitive - the trust-assumption predicate carried on a `CONSUMES` edge (`src/polymerhus/analysis/l1_types.py:139-153`, `L1D-14`), a falsifiable claim ranging over a typed data object - but that instance is not the whole of the concept, as Section 2.6 makes explicit.

### 2.3 Target, boundary, mechanism - the load-bearing tripartition

Not everything on the surface plays the same role in an attack, and the model's central cut is between three roles.

A **target** is a thing the attacker wants to break, individuated by *business purpose*: the checkout, the sign-in, the reward-points ledger.

In L1 this is the `Service` (`src/polymerhus/analysis/l1_types.py:70-77`, `L1D-3/L1D-4`); a Service *claims* surface elements by asking "what business function does this serve?".

A **mechanism** is a cross-cutting technical capability that many targets lie on: a WAF, a CDN, an API paradigm, the authentication machinery, the web-presentation channel.

In L1 this is the `System` (`src/polymerhus/analysis/l1_types.py:80-90`); a System *overlays* elements that share a mechanism, regardless of their business function.

The single test that decides Service versus System is **membership direction** (`L1D-4`): partition-by-purpose is a Service, overlay-a-shared-mechanism is a System.

A **boundary** is not a node at all - it is where trust changes hands, and it is realised as an *edge*: the `CONSUMES` edge from a service to a data item it did not produce is a trust boundary, and the assumption predicate on that edge is the boundary made explicit (`L1D-14/L1D-15`).

This tripartition is load-bearing because the impactful faults do not live inside any single target; they live on the boundaries between targets and in the shared mechanisms (`L1D-15`), which is why the model refuses to flatten everything into "endpoints" and insists on the Service/System/DataItem trichotomy.

A corollary the operator had to state twice, and the code now enforces: a *mechanism classification* (how the UI renders, which API paradigm, which auth method) is a property of the mechanism, not of the target that uses it (`l1-domain-model-catalogue.md` §1).

Storing "rendering model" on a Service is a category error: a rendering fault is a fault of the rendering system, transferable to every service it serves, and pinning it to one service both hides that transfer and duplicates state (`l1-domain-model-catalogue.md` §1, three-reason argument).

### 2.4 Where trust enters, and between which parties

Trust in this domain is not a single relation; it enters at two distinct pairs of parties.

The primary pair is **inter-service**: service A consumes data produced by service B and assumes some property P of it (`L1D-14`, the Tier-1 trust substrate).

This trust is modelled as *derived, not asserted*: an assumption is representable only when it hangs on a represented flow `A -CONSUMES-> D <-PRODUCES- B`, so assertion-without-a-dataflow is structurally unrepresentable (`service-system-model-design_1.md` §4.3).

That is the ontological guarantee that the model's trust boundaries are the real ones and not narration.

The second pair is **tester-and-target**, and it is the pair a human holds silently: every self-report of the black box (a status code, a header, a rendered page) is the target speaking about itself, and the tester trusts it only provisionally.

This second trust relation is the reason the automation-forced primitives of Section 3 exist at all: a machine that cannot represent "how much do I trust this claim, and who told it to me" cannot hold the tester-target boundary the way a human does reflexively.

### 2.5 Coverage - and coverage of what

"Coverage" in this domain is two different measures that the model must not conflate.

**Recon coverage** is surface coverage: has every asset that exists been *seen* - every subdomain enumerated, every endpoint crawled, every parameter fuzzed.

**Analysis coverage** is interpretive coverage: has every seen asset been *judged* - assigned to a service or deliberately set aside.

The two are joined by the **stale pool**, which is not a structure but a derived query: the L0 assets with no inbound `AGGREGATES` edge (`L1D-24`, `src/polymerhus/analysis/sweep.py`).

The stale pool is precisely the ledger of "seen but not yet judged", and its size is a coverage signal - which is why an *empty* stale pool is ambiguous and, as Section 3.5 shows, was empirically a negative signal, not a positive one.

Whether a job that returned nothing *looked and found nothing* or *never looked* is deliberately not a coverage concept in this model but an operational quality-gate concern, handled outside the ontology (Section 3.5).

### 2.6 The fault-hypothesis - a first-class primitive of the vulnerability-probing phase

The top rung of the ladder is the reason the whole system exists: a claim that a *specific fault could exist at a specific locus*, shaped so that a probe could confirm or refute it.

This ontology names it a first-class primitive, the **fault-hypothesis**, but locates it precisely: it belongs to **phase 3 of the penetration-testing workflow** - the vulnerability-probing phase - and it is **not graph structure**.

The recon and analysis phases build a persisted substrate (L0 observed, L1 judged); phase 3 *reasons over that substrate*.

In phase 3, a **testing technique** is instanced - a technique embodies a fault-hypothesis and is enacted as one or more **probes**, each a targeted test against the substrate - and a probe that succeeds discovers a **vulnerability** (a confirmed fault).

The fault-hypothesis lives inside a technique's reasoning for the duration of the test; it is never a node, and it has no anchoring edge.

It is deliberately named ahead of the code: phase 3 and its technique/probe machinery are the deferred Stage-3 signature-evaluation engine (`NM-8`, `L1D-29`), so everything in this section is **designed-not-built** except the one built instance named below.

**What it is.** A fault-hypothesis is a *defeasible, falsifiable* claim of the form "unit U, at locus L, could exhibit fault-class F, because property P is assumed there and P may not hold" - a structured belief with an explicit refutation criterion, exactly the `define-hypothesis` discipline the analyser is meant to acquire (`AMV-1`).

It is not an observation (nothing has been witnessed) and not a bare inference (it asserts a *fault*, not merely a structure); it is the escalation of an inference into a testable adversarial claim, exercised in phase 3 rather than stored in either layer.

**What grounds it.** A hypothesis is licensed by the L1 inferences beneath it and, through them, by the L0 observations those inferences anchor to: an XSS hypothesis is grounded in a `DataItem` judged user-controllable with a path into a rendering `System`; an IDOR hypothesis is grounded in a Service aggregating an endpoint whose parameter is judged an object reference (`service-system-model-design_1.md` §9.4-9.5).

The substrate is the *input* a technique reads; the graph is never rewritten to hold the hypothesis.

The grounding is *necessary-condition* reasoning, never proof: the graph can only ever show that a fault-class is *not impossible* at this locus, and confirming it is the probe's job (`L1D-28`, the necessary-only default-open prefilter).

**Which loci a technique reads.** A phase-3 technique reasons over the same loci the rest of L1 already types, which is the payoff of keeping the model's structure in the persisted layers rather than minting a hypothesis node:

- a **Service**, when its contract could be invalidated (a BOLA/BFLA authorization-policy hypothesis);
- a **System**, when a finding against the mechanism would transfer to every Service on it (a WAF-bypass hypothesis, transferable by the identity-by-adversarial-transfer rule, `L1D-7`);
- a **DataItem** or a **`CONSUMES` edge**, when a trust assumption over a typed data record may be violated - this is the one *built* instance: the `CONSUMES` assumption predicate (`L1D-14`) is persisted L1 substrate that a phase-3 technique consumes, the seed of the general primitive rather than the primitive itself;
- a **structural locus** carried by an atom's `witness_refs`, so a probe targets the witnessing L0 elements, not the raw member set (`L1D-30/L1D-32`).

**How it is defeased.** A hypothesis is confirmed or refuted by a *probe* - a targeted backward-recon request routed back to the requesting agent (interface agreement B, `L1D-26`), whose result confirms the vulnerability or retires the hypothesis.

This closes the ladder into a loop: observation grounds inference (persisted), inference escalates to a phase-3 hypothesis (transient), the hypothesis's probe produces fresh observations back into the substrate, and the cycle repeats - the reflection loop of phase B (`service-system-model-design_1.md` §7.3), made into an explicit phase rather than an implicit analyst habit.

---

## 3. The primitives that automation forces into the open

A human pentester holds provenance, confidence, staleness, identity-across-runs, defeasibility, and the difference between "I have not looked" and "I looked and found nothing" implicitly, in their head.

An automated system must make *most* of these first-class modelled concepts or it cannot reason, and this project's history is the proof: each gap below manifested as a specific defect before it was named.

The one exception is the absence distinction, which the operator has deliberately placed *outside* the ontology as an operational concern rather than a modelled primitive (Section 3.5); it is discussed here only to record that exclusion and where the concern lives instead.

### 3.1 Provenance - who or what made this claim

Without provenance, an LLM's guess is indistinguishable from a parser's deterministic reading, and no claim can be trusted, attributed, or retracted.

The model makes provenance mandatory on every write: every L1 node and edge carries `prov_job`/`prov_model`/`prov_prompt_id` (`src/polymerhus/analysis/l1_types.py:39-45`, `src/polymerhus/analysis/l1_curator.py:184-185`, `L1D-25`), stamped by the system, never by the proposer.

The proposer is *structurally forbidden* from setting it: the analyser's proposal models deliberately omit provenance and it is injected at the curate boundary (`src/polymerhus/analysis/analyser_types.py:1-14, 133-161`), and the sole-writer strips any attempt to set a reserved key from LLM-originated props (`src/polymerhus/analysis/l1_curator.py:139-142, 174-181`).

Provenance is therefore not metadata; it is the concept that lets "an LLM said so" and "a tool measured it" be different kinds of fact in the same graph.

### 3.2 Confidence - the strength of a judgment

An inference is not a fact, and a model that records only the inference loses the one thing that lets a reader weigh it.

The `AGGREGATES` assignment edge carries a **judgment envelope** from day one - `{confidence, status, evidence_refs, provenance, ts}` (`src/polymerhus/analysis/l1_types.py:48-58`, `L1D-25`) - even though the MVP only ever writes `status="committed"`.

The stated reason is exactly the failure it prevents: without a carried confidence, a low-confidence assignment can masquerade as authoritative (`L1R-4`).

Confidence was long the missing *policy* that the project's worst assignment defects trace back to, and it is **no longer missing for assignment** (2026-07, `#34`/`#8`): `withhold_below_bar` drops an aggregate whose confidence falls below `ASSIGN_CONFIDENCE_BAR` (0.75) in the Assigner's own seam, so a below-bar judgment yields no edge and the element stays in the stale pool (`src/polymerhus/analysis/assigner.py`).

Three things about that policy are ontologically load-bearing.

It is a **shaping** rule, not a stored one: absence *is* the withholding, and no "withheld" edge exists - which keeps the graph a record of judgments made, not of judgments declined (`AMV-14`).

It lives in the *proposer's* seam and never in the sole-writer, so the writer stays policy-free and the maker/checker split holds: the Assigner self-withholds (maker), the designed-not-built Auditor would check survivors (checker, Section 5).

The bar is an **empirical output, not a reasoned input** - `evaluation.bar_sweep` reads the kept-vs-bar curve off a run's real confidences, so the number is answerable to measurement rather than argument.

One correction the model must carry, because it cost the guarantee silently: a threshold means nothing without a *scale*. `AggregatesProposal.confidence` is an unbounded float, so a model answering `85` where the contract is 0..1 cleared the 0.75 bar and voided the entire gate - observed on 213 of 675 live edges before `normalise_confidence` was placed ahead of the bar. A graded judgment is only gradable on a scale the system enforces.

What remains unset is the *stale-pool* policy: nothing decides what to do with an element the bar left unjudged (Section 3.5, `AMV-9`).

### 3.3 Staleness and temporal identity

A claim about a live target decays; the model must be able to say when a fact was last true.

Every node and edge carries `first_seen`/`last_seen` datetimes, set `ON CREATE` and refreshed on every touch (`src/polymerhus/analysis/l1_curator.py:220-226`).

This is what lets the two stores be *re-derived* rather than migrated: a re-run refreshes `last_seen` on what still holds and leaves stale timestamps on what no longer surfaces, without churning identity.

Staleness is the temporal companion to identity: identity says "this is the same thing across time", `last_seen` says "and here is when we last confirmed it".

### 3.4 Identity across runs - the idempotency primitive

A human re-testing a target next week silently knows it is the same target; a machine must be *told* what makes two things the same, or every re-run duplicates the graph into a useless duplicate tree (`L1R-5`).

The model's answer is a single principle applied everywhere: **identity is a stable intrinsic key, and every write is an idempotent MERGE on it** (`L1D-22`, `src/polymerhus/analysis/l1_curator.py:15-19`).

A Service is keyed on `(project_id, business_function_slug)` (`L1D-12`); a System on `(project_id, kind, discriminator)` with a non-null `__singleton__` sentinel so a null discriminator cannot silently duplicate a singleton (`L1D-9`, `src/polymerhus/analysis/l1_types.py:32-36`); an L0 Observation on a deterministic SHA1 of its content so the same finding converges rather than duplicating (`src/polymerhus/recon/domain/curator.py:176-177` per recon design §4.1).

This primitive is realised only at the project boundary, and closing the gap beyond it is a stated goal, not a curiosity.

`business_function_slug` is stable *within* a project - `FR-INVENTORY` injects the current inventory into every analyser prompt so each run is internally clean - but it is not stable *across* independent runs of the same target: two identical pipelines produced only 41% identity overlap (Jaccard 0.407), and the "disjoint" services are the same business functions under differently-coined slugs (`AMV-12`).

The current terminal state is therefore within-project stability only; the intended end-state is **cross-run canonical identity** - a business-function vocabulary that is stable across runs, so a target can be regression-diffed over time and two runs compared node-for-node.

The model does not yet have what it needs to reach that end-state: a canonical business-function vocabulary seeded from the operator KB, and/or embedding-nearest-slug reuse at first write, and/or a stemming-aware normaliser that catches the morphological synonyms the exact-key check misses (`seller-payouts` versus `seller-payout`, `AMV-13`).

`AMV-12` and `AMV-13` are the roadmap toward that end-state, and cross-run identity is an open primitive of this ontology, not a settled one (Section 8).

### 3.5 Absence - deliberately an operational concern, not an ontological one

There is a genuine distinction between a probe that *ran and found nothing* and one that *never effectively ran*, and the project has collided with it repeatedly: a clean empty tool result was once mislabelled a failure (fixed in commit `aabd156`, so the gate now treats `returncode == 0` as success regardless of stdout, `src/polymerhus/recon/domain/pod.py:223-236`); an *empty stale pool* was a negative signal because a stronger model over-assigned ~31-38% junk into services rather than judging cleanly (`AMV-9`); and a dead target once reported every job `success` and reached `complete` in 39.7s with 1 endpoint instead of 182, indistinguishable from a healthy run (`AMV-14`).

The operator has ruled that this distinction is **not a domain-model primitive**: the ontology models what *is* discovered - the observed surface and the inferences over it - not what was not looked at.

Absence and coverage-liveness are therefore handled as a testing and quality-gate concern *outside* the model (per-job yield expectations, a run-level surface-sanity gate, a target-liveness precondition checked before a run), which is exactly where `AMV-14` places them.

A consequence worth stating plainly: because absence is operational rather than ontological, the silent-drop behaviour of fail-open (Section 7.4) is an accepted operational trade, not an ontological defect - the model never undertook to record the difference between a dropped judgment and an unmade one, so nothing in the ontology is violated when it does not.

### 3.6 Defeasibility and convergence

A judgment must be retractable, and repeated judgment must reach a fixed point; neither is automatic.

**Convergence** is the property that re-running the analyser over the same surface reaches a stable graph, guaranteed by idempotent MERGE on identity - the pure-function contract `f(L0-slice + observations) -> L1-deltas` predicts identical reads and writes whether pushed (streaming) or pulled (batch), and this was confirmed live (`L1D-22/L1D-23`, `NM-7` update; STATE.md streaming growth `[0,77,142,143,143]` converging).

Convergence is fragile against process bugs: the curation pass once *failed to converge* because it read its context once and then resurrected a merged-away service from the stale snapshot, reporting `merged=1` forever (STATE.md FR-CURE2E defect 1, fixed by re-reading after any destructive op).

**Defeasibility** - the ability to withdraw a judgment - is only partly modelled.

The MVP is monotonic: it only ever appends via MERGE, and the single true retraction case, service-splitting, is explicitly deferred (`NM-4`).

Streaming inherits this monotonicity as a defect: every speculative early assignment over a partial surface is permanent because there is no retraction, which is the measured cause of streaming's precision decay versus batch (`AMV-16` thesis; streaming 19.7% noise versus batch 0%).

Destructive reconciliation (`merge`/`delete`/`relabel`, `src/polymerhus/analysis/l1_curator.py:716-1002`) exists, but it is a *curation-time repair* authority, not a *reasoning-time retraction* - the model can be corrected by a later global pass, but a single judgment cannot yet defease itself as fuller evidence arrives.

### 3.7 The session - an agent's reasoning memory as a first-class concept

A bounded-context ecosystem bestows on each proposer a fluent vocabulary, but nothing yet explains where a proposer's *accumulated reasoning* lives across the several calls it makes within one run.

The automation-forced answer, operator-corrected 2026-08-07 (`#94`, `docs/design/llm-role-architecture-agent-prompt.md` §0.1): the L1 graph is only the WRITE side - the facts a proposer commits. It is not the agent's memory: calling an agent with `invoke_role` rebuilds its prompt from scratch each call, so nothing of what it decided in chunk N reaches chunk N+1 except what it persisted to the graph. A `session` agent closes that gap: its context is carried in a LangGraph **checkpointer thread** keyed by `thread_id`, so each turn resumes where the previous turn left off and the context window grows across the run.

The identity an agent's memory needs is therefore **not** the cross-run node identity of Section 3.4. It is an *instance* identity: distinct to each concurrent execution unit that shares a run and a role, because the checkpointer would otherwise load one pod's memory into another and mis-route context (`#94`; the `PodSession` collision the operator flagged). The model's answer is the **session address** - a per-module typed value (`src/polymerhus/app/llm/session_address.py`: `AnalysisSession`, `PodSession`, `HuntSession`, satisfying a structural `SessionAddress` `Protocol` with `.thread_id`/`.role_id`) that composes a collision-free thread id (segment-escaped, hash-bounded) from the run plus the module's own instance discriminators - analysis's serialization (none), a recon pod's `(phase, tool, input-asset)`, a hunt's `(hunt_id[, spec])`. The memory is resolved context-aware (#120): a stateful turn under a module context routes first to that module's per-module in-memory `ModuleIndex` (a per-thread in-memory saver + store), else to the shared process-wide pooled checkpointer (`app/llm/checkpoints.py`, a `PostgresSaver` over a `ConnectionPool`, fail-open to a shared in-process `InMemorySaver` when Postgres is absent). The per-module index also backs the resume seam: `agent_contexts(run_id, phase, tool)` enumerates a run's committed pod-context thread ids read-only (lock-guarded) as the deterministic contract a future resume agent implements against (#124); the thread ids are stable because the `SessionAddress` composition is a pure function of the run plus its module discriminators, proved byte-identical by the address audit (#119/#124 - no UUID/time source enters it).

Two further seams are deliberately NOT part of this primitive, only exposed by it: context-window compaction + long-term memory (`#95`, the `middleware`/`store` hooks on `app/llm/session.py` - the `middleware` seam for the compaction body, the `store` seam for long-term memory), and the adaptive inference-method / capability configuration (`#99`, which adjusts the `thinking` baseline a role currently declares statically in `app/llm/providers.py::Role.thinking`). Both plug into the session seam; neither is this ontology's - the session is the durable reasoning-memory concept, the compaction is a token-budget concern (#95 ticket), and the capability adjustment is a config policy (#99).

_Status_: session (the resumable reasoning-memory primitive) is BUILT for the stateful agents (analysis proposers, recon triager/configurator, recon-orchestrator, hunting hunt-orchestrator/hunter, and the test-executor pod's `pod_runner`/`pod_triager` on per-spec `HuntSession` threads - #84, D84-2/7; `stateful` in `app/llm/session.py`); the per-module `ModuleIndex` + context-routed resolution and the read-only `agent_contexts` resume enumeration are BUILT (#120/#124); compaction of the now-growing context is BUILT (`#95`, ADR `context-compaction-95-decisions.md`; the `middleware` seam it plugs into is exposed, and every checkpointer-backed session agent across the modules is a wired consumer); the cross-unit fusion PRIMITIVES (the memory-read seam `read_session_memory`/`aread_session_memory` over a child's own thread, plus the actor mailbox + delivery middleware that posts `{content, messages, thread_id}` into a parent's inbox) are BUILT - only the integral fusion reasoning (a parent acting on the fused memory, `#85`) remains designed-not-built.

A session-turn behavior added 2026-08-12 (`#109`, ADR D11 items 3-4): **reasoning replay**. A turn's assistant message that carried reasoning (per the T3 capability profile `reasoning_in_response`/`reasoning_field`, D11 item 5: `reasoning_content` at message level, `reasoning_details` via `provider_specific_fields`) is RE-PERSISTED into the session thread **byte-identical** by the replay pipeline at the seam (`app/llm/reasoning.py` + `session.py::_replay_reasoning`), so the next turn's restored prefix is byte-identical and provider-native KV caching can hit (D8.1). Encrypted reasoning is replayed as well - its **readability** (present/parsed/replayed) is tracked via a dedicated langfuse llm-response field, never by skipping the payload (D11 item 4). Cache presence (`usage_metadata.input_token_details.cache_read`) and heuristic proxies are recorded as observability, never gates (D11 item 3; the empirical caching checker remains a grill element in `settings.recon`). The pipeline is parity-free: profile unknown per D5 Rule 1 -> no parse, gap logged.

A second session-turn behavior was ratified 2026-08-18 (`#95`, ADR `context-compaction-95-decisions.md`): **context-window compaction**.
The session's trail occupancy is measured from the provider's real per-step usage (`input_tokens + cache_read`); once it crosses a configurable threshold of the model's real window (default 90% of `context_limit`, provenance-gated per D5 Rule 1), an out-of-band compact pass folds OLDER reasoning AND older turn inputs (which the running summary now carries) into a running summary (a synthetic message in the trail, quality-gated) and offloads large tool-output bodies to the module's own store, leaving a header (outline, status, head/tail excerpts, body ref) in the window.
The pass coordinates with reasoning replay through a token-bounded precedence: the most recent replay-eligible reasoning (a 30k-token tail) stays byte-identical, older spans are summarised.
The next call on the session awaits any in-flight pass (a barrier) - a call never proceeds on an over-budget window - while the module store keeps the full trail at full fidelity for export/eval.
A pass compacts exactly the trail the usage ledger last measured (its boundary); anything added since - the current turn's own input - is the fresh delta and rides untouched on top of the staged trail, so replacement can never eat input the pass never saw.
A pass that produces no summary leaves every message verbatim.

**The pod memory store** (the #84 test-executor pod's own memory sidecar, D84-20/28, adapted to the per-project deterministic-key pattern D84-33 through D84-38 as of T1/#177): the pod is both a session consumer and the owner of a durable, per-project, **deterministic-key** experiment-memory store (`src/polymerhus/attack/hunting/pod/pod_memory.py::PodMemoryStore`, `data/<project_id>/test-executor-pod/`) with TWO bodies - `experiment-logs/<fault>_<strategy>/<order>.yaml` (one file per variant, overwritten idempotently) and the per-project `notes.yaml`. The spec identifier is the #164 hunter's `<fault>_<strategy>` (D84-34, NOT a content hash) and the order number is the variant ordinal; notes are keyed `<fault>_<strategy>:<order>:<note_name>` (D84-36). There is NO `_seq`/`_ref` (D84-36): the deterministic key plus the natural list order disambiguate every artifact; reads are latest-first, with the typed attribute filters (order/kind/classification/symptom_status) beside the retained substring match. It is pod-owned and per-project, never the cross-project `(unit_id, fault_class)` namespace. Its notes carry the canonical D84-32 value fields under a **closed `POD_NOTE_KINDS` enum** (provisional, D84-28): `experiment_summary` (the ONE consolidated P3 note per stretch - the Triager's primary reasoning artifact), `kb_insight` (a KB-derived testing primitive), and `freeform`. The `note` tool (`pod/note_tool.py::PodNoteTool`) is a `BaseTool` (extra="forbid" args, coded rejections, fail-open on a None store) that writes/reads this store, with the prompt-memory pattern (D84-27): `MEMORY_READ_GUIDANCE` + the per-turn indexable key-list covering both the note keys and the experiment-log identifiers embedded in the Runner's lap opener and the Triager's delta.

---

## 4. The integrated model - L0 observed, L1 judged, and the hinge between

### 4.1 Two stores, two epistemic species

Layer 0 and Layer 1 are two physically co-resident but logically separate stores, independently navigable, joined only by cross-layer edges (`L1D-1`), and they never share identity keys so either can be re-derived without churning the other (`L1D-2`, `src/polymerhus/analysis/l1_curator.py:32-39`).

The separation is not an implementation detail; it is the boundary between two kinds of claim.

An **L0 node is a descriptive claim** whose truth condition is "a tool witnessed this feature of the surface".

An **L1 node is an interpretive claim** whose truth condition is "an analyst-role LLM judged this to be the case from evidence".

A Service is never observed - no tool emits "checkout service"; it is *reconstructed* from the endpoints, data, and behaviour the tools did observe.

That is why the analyser is the only producer of L1 nodes and why its outputs are called proposals, not readings (`src/polymerhus/analysis/analyser_types.py:1-14`).

### 4.2 The hinge - crossing the boundary is crossing from "what is there" to "what it means"

Three cross-layer edges carry claims from the observed store into the judged store, and they are the epistemic hinge of the whole ontology.

| Edge | From -> To | Carries | Epistemic role |
|---|---|---|---|
| `AGGREGATES` | `L1Service` -> L0 node | full judgment envelope `{confidence, status, evidence_refs, prov_*, ts, endpoint_template?}` | the assignment judgment: "I judge element e belongs to service S, this confident, on this evidence" (`L1D-25`, `src/polymerhus/analysis/l1_curator.py:351-409`) |
| `SURFACES_AT` | `L1DataItem` -> L0 Parameter/Header/field | `prov_job`, `first/last_seen` | where a judged logical data item appears on the observed surface (`src/polymerhus/analysis/l1_curator.py:478-496`) |
| `EVIDENCED_BY` | `L1System` -> L0 node | `prov_job`, `first/last_seen` | the observed fingerprint that grounds a judged mechanism (a `Server:` header, a cookie) (`l1-domain-model-catalogue.md` §5.1) |

Crossing this boundary means an inference is being anchored to the observations that license it, which is what keeps L1 defeasible: pull the evidence and the judgment loses its ground.

The L0 target of every cross-layer edge is `MATCH`ed and never `MERGE`d (`src/polymerhus/analysis/l1_curator.py:390-391`), so the interpretive writer can never mint a descriptive node - the two stores' sole-writers stay disjoint (Section 5, Section 7.1).

The cross-layer edge is also the *lazy fetch hop*: L1 is navigated natively for all reasoning, and L0 is fetched across `AGGREGATES` only at concretisation, never in the hot loop (`L1D-1`, traversal-then-fetch, Section 7.5).

### 4.3 The envelope asymmetry is intentional

Only `AGGREGATES` carries a full judgment envelope; `SURFACES_AT` and `EVIDENCED_BY` carry only provenance and timestamps, and this asymmetry is a deliberate ontological commitment, not an accident of implementation.

It encodes the claim that *assignment* is a graded judgment worth confidence and evidence - "does this element belong to this service" is genuinely uncertain and revisable - while *data-surfacing* and *mechanism-fingerprinting* are near-mechanical bindings that are either right or absent: a `Server: Varnish` header either grounds a ReverseProxy or it does not, and "this parameter is where the item surfaces" is a lookup, not a weighing.

The model therefore reserves the judgment envelope for the one cross-layer edge that carries a graded judgment, and keeps the other two as plain provenance-stamped bindings by design.

### 4.4 The typed spine versus the natural-language read

Within L1, every unit is a typed spine with natural-language characterisation hung off typed handles (`L1D-17`), mirroring a soundness split (`DD-3`): the symbolic layer reasons over the enums and edges, the creative planner consumes the prose.

The spine is what makes a downstream fault-symptom addressable as a graph locus rather than a brittle substring match (`L1D-19`); it is the strongest forward-compatibility lever in the model and the one part whose retyping is a one-way door.

The rule that separates spine-on-System from spine-on-Service is the mechanism-classification principle of Section 2.3: only `business_function`, `exposure`, and free-text contract handles are Service props; `api_paradigm`, `navigation_model`, `rendering_model`, and `auth_methods` are all System-side, reached by an edge (`l1-domain-model-catalogue.md` §3).

The "free-text contract handle" is realised as `service_contract` (2026-07-27, #29): a brief functional profile of what the business function does and owns, written in the application's own domain nouns and action verbs.
It is the primary evidence the cross-layer Assigner consumes - it matches the nouns and actions of an observed endpoint path against the contract to judge ownership - which is why the contract must discriminate between business functions, and why it may never contain a path, URL or parameter name: the operator KB states none, so a path in a contract is a model's guess that would afterwards be indistinguishable from evidence.
This makes the Service the one L1 node that carries its own description of itself, and it is what lets an opaque slug (`byoc`, `agent-tool`) be routable at all.

Two spine dimensions are ontologically independent and neither may be inferred from the other: `navigation_model` (SPA/MPA/Hybrid) and `rendering_model` (CSR/SSR/...), because a SPA may use SSR and an MPA may use CSR for a widget (`L1D-31a`); the earlier code that inferred rendering from navigation (SPA -> CSR) was deleted as a modelling error (`FR-MODELFIX`).

Some spine slots are not read off the surface at all but *classified* by a dedicated procedure over runtime signals - the anatomy skills (Section 5), which are the "how to reverse-engineer this kind of system" companion to the enumeration of kinds.

### 4.5 DataItem - data as a first-class node, the crown-jewel locus

A logical data record (a session token, an order, a `sales_figure`) is a first-class L1 node keyed on a flexible semantic `item_key`, identity independent of the many L0 sites it surfaces at (`L1D-13`, `src/polymerhus/analysis/l1_types.py:110-125`).

This is decided against two alternatives - edges between L0 parameters (which re-entangles the stores and fragments one logical item into dozens of parameters) and prose in a security profile (which no symbolic reader can query) - and the decisive argument is that machine-checkable trust assumptions are literally unimplementable without typed data objects for the predicates to range over (`DD-18`).

The DataItem is doubly load-bearing: it is the Tier-1 trust locus, and it is the *noise filter for concretisation* - the small semantic selector through which a test reaches its handful of real L0 sites instead of fanning out over a service's whole member set (`L1D-32`, the `L1R-8` hazard).

---

## 5. Actors and their authority

The model is enacted by a small set of actors, and the authority each holds is itself part of the ontology, because "who may assert what" is what makes a claim in the graph mean anything.

**The operator** is the only human, and the source of intent the system is blind to by design.

The operator supplies the target, the scope, the free-text `operator_kb` business framing, and the settings, and provides the ground truth about what the application *is for* that no purely technical view recovers (`service-system-model-design_1.md` §1.1).

Crucially the system is deliberately kept blind to the target's true identity - it analyses `soupmarket.shop` without being told it is OWASP Juice Shop - so the operator's authority is to frame the business, not to leak the answer (STATE.md, the bootstrap-first e2e discipline).

**The proposer roles** are LLM agents that hold judgment but not write authority.

The `triager` reads L0 tool output into adversarial `Observation` insights (`src/polymerhus/recon/domain/pod.py`, recon design §4.5); the `analyser` reconstructs the L1 service/system model - historically in two passes, an assignment pass and a dedicated data-modelling pass, split because one combined call systematically starved data modelling (`_two_pass_analyse`; STATE.md DataItems=0 defect), and since `#34` dissolved into **responsibility-scoped proposers** behind a supervisor, each consuming a `Chunk` narrowed by its own admission set (the `Assigner` owns `AGGREGATES` and emits nothing else, `src/polymerhus/analysis/assigner.py`; the `mechanism-typist` (`#9`) owns System typing, emitting `Service->System` edges over the same chunk-fed schedule, `src/polymerhus/analysis/supervisor.py`); the anatomy skills (`webpage-profile`, `authorization-pyramid`) classify spine slots that cannot be read off the surface and emit the triple *typed classification -> spine slot, evidence -> Observation, deeper probe -> backward-recon request* (`L1D-31`, `src/polymerhus/analysis/anatomy.py:60-86`).

Two role attributes the model now carries explicitly (Section 3.7, `#94`): **agent_mode** (`one_shot` | `session`, whether a role is a stateless structured call or a checkpointer-backed resumable agent whose context grows) and a declared **thinking** baseline (`Role.thinking` in `src/polymerhus/app/llm/providers.py`, translated to `reasoning_effort`, to be made capability-adaptive by `#99`, `docs/design/capability-adaptive-client-99-decisions.md` A1).
The structured-output method is chosen **semantic-first** by whether the call binds a tool (the session/crawl `ToolStrategy`/`bind_tools` seams -> `function_calling`) or is a pure one-shot extraction (`invoke_role` -> `structured_output` json_schema, `strict=False`), then corrected by the capability profile in the fixed degrade chain `json_schema` -> `function_calling` -> `json_mode`; `reasoning_effort` is orthogonal to method choice (a thinking model's tool calling is a provider quirk, not a rule).
The stateful proposers are the analysis trio (`assigner`/`mechanism_typist`/`data_modeller`, each on its own per-run `AnalysisSession` thread), the recon triager (per concurrent pod `PodSession`), and the hunting hunter (per-hunt `HuntSession`); the bootstrapper, anatomy, curation and sweep stay `one_shot` (their reasoning is externalised to the graph, no working set to resume).

Two roles are registered but dormant (`configurator`, `job_orchestrator`, `src/polymerhus/app/llm/providers.py:14`), reserved seams for the designed-not-built context-memory scaffold (recon design §9).

Every proposer emits proposals that omit provenance and identity, which the write boundary injects and guards - the proposer can never spoof who it is or what a node's identity is (`src/polymerhus/analysis/analyser_types.py:1-14`, `src/polymerhus/analysis/l1_curator.py:139-142`).

**The sole-writer** is the single authority that turns a proposal into a fact-in-the-graph.

There is exactly one per store - `src/polymerhus/recon/domain/curator.py` for L0, `src/polymerhus/analysis/l1_curator.py` for L1 - and it is the ontological boundary between "proposed" and "true here": it enforces identity, stamps provenance, validates every label and edge type against a fixed allowlist, and interpolates nothing unvalidated into Cypher (`src/polymerhus/analysis/l1_curator.py:69-129, 328`).

The sole-writer is where the maker/checker discipline lives at the data boundary: the maker proposes, the writer is the mechanical checker of shape and identity.

**The verifier** is an independent adversarial agent that gates work, re-derives every load-bearing number with its own queries, runs counter-factuals the maker did not, and never self-approves (STATE.md, repeated "verifier REJECTED then APPROVED after correction").

Its authority is epistemic: nothing is "done" until a separate agent has reproduced the evidence.

**The loop** is the meta-process that plans bounded work areas, runs them one worktree at a time, and records what was learned in the STATE ledger; it is the actor that accumulates the empirical findings this ontology mines.

**The auditor** is a designed-not-built actor (`AMV-16`): a separate checker that would vet proposals *before* they are written - a confidence gate, a noise classifier, an identity-reuse check - moving the maker/checker discipline upstream from repair-after-the-fact to prevention-at-creation.

It is recorded here because it is the natural home for the currently-orphaned confidence and absence policies (Sections 3.2, 3.5), and because the model's own history argues both for it and for caution: prevention at creation is what actually kept the batch graph clean, but an auditor that is a no-op on good input rots undetected exactly as the broken curation stage did.

---

## 6. How the epistemic terms interlock

The reasoning vocabulary is not a list of independent terms; the terms constrain each other, and the model works only because of how they compose.

**Evidence** grounds **inference**: an L1 node's claim is only as good as the L0 nodes its cross-layer edges anchor to, so pulling the evidence defeats the judgment (Section 4.2).

**Provenance** and **confidence** are orthogonal and both required: provenance says *who* asserted a claim, confidence says *how strongly*, and a claim needs both to be weighed - a high-confidence claim from an unreliable role and a low-confidence claim from a reliable one are different things (Sections 3.1, 3.2).

**Assumption** and **hypothesis** are inference escalated toward the top of the ladder (Section 2.6): a trust assumption is a judgment shaped so that a probe could refute it, representable only when it hangs on a derived data flow (`L1D-14`), and it is the one persisted instance of the general phase-3 fault-hypothesis - a falsifiable claim that a fault could exist at a locus, grounded in the inferences beneath it.

**Staleness** is the temporal projection of **identity**: identity says two observations are of the same thing across time, `last_seen` says when that thing was last confirmed, and together they make re-derivation non-destructive (Sections 3.3, 3.4).

**Defeasibility** and **convergence** are the dynamics of judgment under repetition: convergence is the guarantee that repeated identical judgment reaches a fixed point (idempotent MERGE), defeasibility is the missing-in-MVP ability to withdraw a judgment when evidence turns, and their tension is the streaming-monotonicity defect (Section 3.6).

The **identity ⊥ membership** principle is the keystone that makes the rest coherent: a unit is keyed on what it *is* (its business function, its mechanism kind), never on what it *contains* (`L1D-11`).

Without it, membership churn would entangle two units' identities into a duplicate tree, breaking dedup, breaking the inverse "which services manifest this facet" traversal, and breaking downstream rooting (`L1R-5`); with it, membership is free to be N:M forever and a shared L0 element becomes *signal* (a session cookie shared across services is the evidence they sit on one identification system) rather than a partition violation (`L1D-10`).

---

## 7. The invariants as ontological commitments

These are not coding conventions; each is a commitment about what the model *means*, stated with the consequence if it is violated.

### 7.1 Sole-writer - there is exactly one authority that makes a claim true

Commitment: for each store, one and only one module may write it, and it is the boundary between proposed and true (`src/polymerhus/recon/domain/curator.py:1-13`, `src/polymerhus/analysis/l1_curator.py:1-40`).

Consequence if violated: identity, provenance, and label allowlists can be bypassed, so "true in the graph" stops being a well-defined predicate - unprovenanced nodes, duplicate identities, and injected labels become possible, and no reader can trust any node's origin.

The commitment is what lets provenance-on-write and idempotent-identity be *guarantees* rather than hopes.

### 7.2 Idempotent identity (identity ⊥ membership) - sameness is intrinsic

Commitment: two things are the same iff their intrinsic key matches, and re-running any write converges (`L1D-11/L1D-22`).

Consequence if violated: re-derivation duplicates the graph into a duplicate tree that defeats every downstream traversal (`L1R-5`), and the store stops being a stable substrate that Stage-3 signatures and phase-2 rooting can name.

This is the one-way door of the whole model (`L1D-11` is explicitly decide-now).

### 7.3 Provenance-on-write - no claim is anonymous

Commitment: every node and edge records who or what produced it, stamped by the writer, never the proposer (`L1D-25`, `src/polymerhus/analysis/l1_curator.py:220-226`, and the `ON CREATE` node-provenance fix in `FR-NFR`).

Consequence if violated: an LLM guess and a tool measurement become the same kind of fact, and a wrong claim can be neither attributed nor retracted - the tester-target trust boundary (Section 2.4) collapses because the graph forgets who was speaking.

### 7.4 Fail-open - partial knowledge beats no knowledge, at a cost

Commitment: one bad delta never aborts a batch, and a missing collaborator degrades rather than crashes - every layer catches and converts (recon design §5; `src/polymerhus/analysis/l1_curator.py:_write_each`, per-item skip-and-log).

Consequence if violated: a single malformed proposal or a transient Neo4j blip would lose an entire run's work.

Fail-open *silently drops* - a dropped judgment and a never-made judgment are indistinguishable downstream, and the anchor-allowlist drop is the exemplar, where an out-of-allowlist Observation is computed, paid for, and lost with only a log line (recon design §7.4).

This is an accepted operational trade of visibility-of-absence for liveness, not an ontological defect: because absence is deliberately outside the model (Section 3.5), the ontology never undertook to distinguish a dropped judgment from an unmade one, so fail-open violates nothing it commits to - the concern lives in the operational quality gates instead (`AMV-14`).

### 7.5 Traversal-then-fetch - reason over the light projection, fetch the heavy detail lazily

Commitment: reasoning navigates L1 natively over token-light index-cards, and crosses into L0 only at concretisation, through small typed selectors, never over a raw member set (`L1D-27/L1D-32`, `src/polymerhus/analysis/index_card.py`).

Consequence if violated: the member-set explosion bites - a single service can aggregate tens of thousands of L0 elements, and a naive concretiser that fans out over all of them drowns the handful of real targets in noise (`L1R-8`), negating the abstraction's whole promise of reduced testing noise.

The commitment is what makes N:M membership affordable: the set stays large and raw, the projections over it stay small and semantic.

---

## 8. Where the model is deliberately silent or unresolved

An honest ontology names its holes; false closure here would be worse than an open question.

**The confidence threshold is now SET; the stale-pool policy is still unset** (`L1OP-5`, `AMV-9`, updated 2026-07-30): the boundary between "judged" and "left stale" is defined for assignment - `withhold_below_bar` at 0.75, a shaping rule in the Assigner seam, with the bar swept empirically rather than argued (Section 3.2).
What remains open is what to DO with the pool that gate produces: nothing re-judges a withheld element, escalates it, or reports it as a coverage debt, so the stale pool is still a ledger nobody reads.
The related open question is whether a graded gate belongs on any other edge; today only `AGGREGATES` carries a graded judgment, so the envelope asymmetry (Section 4.3) leaves nothing else to gate.

**Absence is deliberately excluded, not unresolved** (Section 3.5, `AMV-14`): the model records what is discovered, not what was not looked at, so the probed-empty/unprobed distinction is an operational quality-gate concern by decision, not an open ontological question.

**Cross-run canonical identity is an open primitive with a defined target end-state** (`AMV-12/AMV-13`, Section 3.4): identity is stable within a project but not across runs of the same target, and the intended end-state is a cross-run-stable business-function vocabulary; to reach it the model still needs a canonical vocabulary anchor (seeded from the operator KB and/or embedding-nearest-slug reuse) and a stemming-aware normaliser.

**Reasoning-time defeasibility is absent** (`NM-4`, Section 3.6): a judgment can be repaired by a later global pass but cannot yet withdraw itself as evidence turns, and the one true retraction case (service-splitting) is deferred - this bears directly on the phase-3 fault-hypothesis, which a probe is meant to confirm or retire (Section 2.6).

**DataItem identity is a judgment with no discipline** (`L1OP-1`): "when are two data items across services the same logical item" is decided by the analyser reusing an `item_key`, with no normaliser or key rule, exactly the same shape of open problem as cross-run service identity.

**The fault-hypothesis is first-class in the ontology but ahead of the code, and it is a phase-3 primitive, not graph structure** (Section 2.6, `NM-8`): the operator has ruled that the fault-hypothesis is never a graph node and has no anchoring edge - it exists only in the reasoning of a phase-3 testing technique, which instances probes against the persisted L0/L1 substrate to discover a vulnerability. It is named here by deliberate operator choice to let the ontology lead, but only one *persisted* seed instance (the `CONSUMES` trust assumption) is built; the whole of phase 3 (technique, probe-as-hypothesis-test, vulnerability) is designed-not-built.

**`SystemAspect` is designed but not built** (`L1D-16`, `NM-3`): the spec treats reified shared facets as the mechanism that makes the inverse "which services manifest this facet" traversal one hop, but the MVP fence excludes it (FR-NFR asserts no `:SystemAspect` node), so DFS-up over shared trust loci is a designed capability, not a live one.

**The context-memory scaffold is partially built, not wholly designed-not-built** (recon design §9, `#94`): the *per-instance* reasoning memory is now real - a stateful agent resumes its own growing context from the process-wide pooled checkpointer, keyed by its collision-free session address (Section 3.7) - while the *cross-phase operational-failure* memory (`recon_signals`), grounded coverage verdicts, finding-triggered extension, and the cross-unit FUSION REASONING (a parent integrally acting on a child's persisted memory, `#85`) remain specified and not built. The fusion PRIMITIVES are built (feat/async-actor-agents): the memory-read seam `read_session_memory`/`aread_session_memory` reads a child's own thread from the shared checkpointer, and the actor delivery middleware posts each child's `{content, messages, thread_id}` into its parent's inbox; `asset_context` is threaded end to end but is always the empty string (recon design §9.1).

---

## 9. Corrections where the sources disagreed

The code is the tiebreaker; these are the places it overruled a design document, recorded so a reader of the older docs is not misled.

The `SystemKind` and `DataRelationshipKind` controlled-vocabulary *catalogue nodes* of `service-system-model-design_1.md` §2.3/§5.1 no longer exist: a System's kind is an intrinsic identity attribute `kind` validated against the `SYSTEM_KINDS` Python constant (`src/polymerhus/analysis/l1_curator.py:83-98`), and a DataRelationship's kind *is* the uppercased edge type from a fixed six-value allowlist (`src/polymerhus/analysis/l1_curator.py:105-116`) - the operator's 2026-07-20 correction, which `l1-domain-model-catalogue.md` §0 carries and the code implements.

`RENDERED_BY` and the two `RenderingSystem_*` kinds of the spec's §6/§7.6/§9.5 are deleted: a service reaches its presentation channel via `EXPOSED_VIA` a `WebPresentation` System carrying `rendering_model` and `navigation_model` as independent props (`src/polymerhus/analysis/l1_curator.py:94-95, 122-129`; `FR-MODELFIX`).
`WebPresentation` is PER (service, rendered-page cluster), not a singleton (operator-ratified 2026-08-01, #53): the navigable `text/html` pages a service renders are grouped by rendered similarity into clusters, each `(service, cluster)` one node keyed `discriminator = <business_function_slug>::<cluster>`, with the cluster's member page paths carried in a `pages` prop as the location index.
This nests per-page within the per-service discriminator the anatomy path previously used alone (#41), and for a CSR+SPA target - whose routes all serve one shell - it stays one node carrying its route refs until steel DOM-delta (#51) supplies distinct per-view evidence.

Journeys, though a DONE FR area (`FR-JOURNEY`) and still discussed in the catalogue, were withdrawn from the codebase on 2026-07-22 for judgment-quality reasons - the LLM coined single-member "journeys" that restate a service rather than group services (`AMV-11`); `CurationBatch.journeys` and its stage are removed, so the ontology treats journeys as an unbuilt, deferred extension, not a live primitive.

The spec's §9.6 assumption that "katana already yields path templates in L0" is false - katana emits concrete paths, so the endpoint-template key must be computed at assignment time and cannot be reconstructed afterward (`src/polymerhus/analysis/l1_curator.py:330-348`, whose comment records the correction directly).

Several recon-design corrections against the superseded `recon-mvp-design.md` are folded in above by reference: empty-clean-output is success not failure (commit `aabd156`), no reduced-coverage Observation is emitted for an unauthenticated `use_auth` job (recon design §6), and no explicit `recursion_limit` is configured (recon design §6).
