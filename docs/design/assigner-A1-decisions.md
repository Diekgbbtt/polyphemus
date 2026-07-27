# Cross-layer Assigner (A.1) - ratified decision record

Status: DECISIONS RATIFIED by the operator (2026-07-27); BUILT on `feat/assigner-classification-only` under ticket #34.
The spec is #34; its assertion catalogue (C1-C26, E1-E2) is attached there as a comment.
Scope: the grey points left open by ticket #8 (`Agent spec: Cross-layer Assigner (A.1-only)`), resolved in an elicitation pass over the increment-2b Assigner slice (`src/polymerhus/analysis/assigner.py`).
This record is the input to the #8 specification and to the 2b wiring; it does not restate what T2 (#3), T1 (#2) and T3 (#4) already fixed.

Conventions: plain dash only; one full sentence per physical line; ubiquitous language from `src/polymerhus/analysis/CONTEXT.md`.

---

## 1. The Assigner's responsibility, restated

The Assigner has sole ownership of ONE judgment: streamed-Endpoint service-classification.
Given an Endpoint that recon has streamed into a chunk, it decides which EXISTING Service aggregates it, with a confidence and evidence refs.
It does not mint Services, it does not propose Systems, and it does not model data.

## 2. Three distinct "no edge is written" mechanisms

The codebase called two of these "withhold", which conflated a decision never taken with a decision taken and declined.
They are now named separately.

**Gate** (input side).
The element never reaches the agent, so no judgment is formed.
Realised as the per-agent admission table (D2/D7) and, on the data path only, the httpx profile gate (D1).

**Narrow** (output side, structural).
The agent is not permitted to emit a class of delta at all, regardless of what the model returned.
Realised by `narrow_to_assignment`.

**Withhold** (output side, epistemic).
The agent saw the element, formed a judgment, and declines to commit it because confidence is below the bar.
Absence IS the withholding; no "withheld" edge exists (AMV-14).
Realised by `withhold_below_bar`.

## 3. Ratified decisions

**D1 - profile gate, service path.**
The httpx profile gate is dropped for Endpoints: an unprofiled Endpoint is still assigned to a Service.
The gate survives on the data path for `Parameter`, where the profile genuinely informs whether a parameter is API input or web-form field.
Consequence: `Chunk.flagged` loses its consumer on the service path, and the "never mint on flagged-only evidence" rule is moot (superseded by D4 anyway).

**D2 - multi-layered, agent-concern-aware asset gating.**
Every asset type any recon job produces is streamed.
Each agent then gates that stream down to the types it can meaningfully consume:

- `assigner` - `Endpoint` only.
- `mechanism_typist` - broad (essentially all types).
- `data_modeller` - `Parameter` and `Header`.

This replaces the `_SERVICE_TYPES` / `_DATA_TYPES` / `_DUAL_TYPES` concern partition as the routing mechanism.

**D3 - multi-ownership is legal.**
Several aggregates to the same L0 asset may coexist; there is no single-owner invariant.
The verbatim's tie-break rule ("where two contracts both fit, prefer the one whose OWNED records the element operates on, and lower your confidence") is deleted.
The model emits one aggregate per genuinely fitting Service, each carrying its own independently honest confidence, and the bar filters each edge separately.

**D4 - the Assigner cannot mint Services.**
Minting is not its responsibility; the Bootstrapper (`bootstrap.py`) is the sole source of Services and of `service_contract`.
`existing_slugs` stops being a mint discriminator and becomes a VALIDATION set.
The output narrows from `L1DeltaBatch{services, aggregates}` to `{aggregates}` alone.

**D5 - observations do not reach the Assigner.**
`Chunk.observations` is consumed by the `mechanism_typist` and the `data_modeller`, not on the service path.

**D6 - the backlog channel is deferred.**
The Assigner produces backlog descriptions, but no transport is built in this increment.
`ProposalEnvelope` gains no `surfaced` field yet.

**D7 - the per-agent gate is a declarative table.**
One `ROLE_ADMITS: dict[Role, frozenset[str]]` lives in `chunking.py` beside the routing table, applied when a chunk is rendered for a role.
All three gates stay readable in one place and `Chunk` stays a plain job delta.

**D8 - `Chunk.concern` is dropped.**
With per-role admission doing the narrowing, `concern` and `CONCERN_ROLES` are a second mechanism doing one job.
The schedule builder pairs each chunk with all roles; a role whose admitted set is empty for that chunk yields an empty batch, which `assign` already handles.

**D9 - an out-of-inventory `service_slug` becomes a backlog description.**
The aggregate is dropped (never minted), and the model's reach for a non-existent Service is retained as evidence that a Service may be missing.

**Confidence bar.**
`ASSIGN_CONFIDENCE_BAR = 0.75` is acknowledged as pure heuristic.
It is an OUTPUT of the assertion suite, not a reasoned input, and stays env-tunable so a run can sweep it.

## 4. Prompt structure

Split by VOLATILITY so the provider prompt-cache prefix holds across a run.

**System message (stable):** the analyser skill, the role verbatim, the reflection protocol, the few-shot examples, the output-shape rules.

**User message (volatile):** the un-truncated L1 identities block FIRST (the FR-INVENTORY discipline), then the rendered chunk.

The L1 inventory stays in the USER message deliberately: it mutates as the run proceeds, so hoisting it into the system prefix would invalidate the cache every step and buy nothing.
This is the same volatility split as decision 7 of `service-decomposition-A2.md`, with the inventory landing on the volatile side.

## 5. Reflection verbatim (`mode="reflect"`)

`AgentDispatch.mode` already carries `create` / `reflect` and is currently unused.
The reflect verbatim lives in the system message and fires only on `mode="reflect"`.
It merges the load-bearing primitives of `~/.claude/skills/overthink/SKILL.md` and `~/.claude/skills/critical-thinking-logical-reasoning/SKILL.md` down to four steps, each producing a written line before any revised proposal:

1. Restate each aggregate's claim AS EVIDENCE: quote the path segment or parameter matched and the contract clause it matched against.
   An aggregate whose evidence restates the slug rather than the surface is self-refuting.
2. Argue the strongest COMPETING owner and why it lost.
   Under D3 a genuine second fit is emitted rather than discarded; an inability to name any competitor signals a thin inventory, not high confidence.
3. Calibrate against the bar explicitly: state the confidence, whether it clears the bar, and what evidence would move it.
4. Surface the residue: Endpoints that could not be placed, as backlog descriptions.

Few-shots: three, drawn from real observed surface, covering one clear assignment, one deliberate withholding, and one multi-owner case.
The withholding example is the load-bearing one, since the measured 31-38 percent over-assignment says the model does not withhold unprompted.

## 6. Backlog item shape

One short sentence describing the suspected missing Service, with the candidate slug embedded inline rather than carried in a separate field.
Example: `seller-payout-dispute: refund and chargeback paths under /api/orders/*/dispute appear unowned`.
`SteeringState.gaps` stays `list[str]`.

## 7. Supervisor <-> Assigner contract

Down: `AgentDispatch{dispatch_id, role="assigner", phase="A1", mode, chunk}` and nothing else.
Everything else the Assigner needs is re-derived LIVE from the graph at dispatch time, never carried on the dispatch, because `Chunk` is frozen and deliberately holds no L1 context.
The live inventory read yields both the rendered identities block and the validation set, so the two can never disagree.

Across: `ProposalEnvelope{deltas: L1DeltaBatch{aggregates}, status}`.

Up: `StepReceipt` as today.

Adapter: `assign()` is wrapped to the `ProposerBody = Callable[[AgentDispatch, dict], L1DeltaBatch | None]` signature the supervisor expects.

## 8. Known defect to fix while wiring

`_make_proposer` hardcodes `status="empty"` on the envelope even when the body returned real cargo (`supervisor.py`).
A step that carries content must report `written`.

## 9. Consequences worth stating plainly

D4 voids the #29 rationale currently in `assigner.py` ("a minted Service NEEDS its contract"), which landed on `feat/bootstrapper-service-contract` days before this record.
The Bootstrapper's contract-writing is untouched; only the Assigner's mint path is retired.

D4 together with D6 leaves the backlog stranded for this increment: the Assigner can no longer mint, and the channel carrying "this surface has no owner" upward is deferred.
Unassignable Endpoints therefore stay in the stale pool with their gap descriptions produced but not transported.
Coverage will look worse before it looks better, and no assertion in 2b can prove the backlog is correct.
