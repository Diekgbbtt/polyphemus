# ADR: hunting context dedup and attention budget

*Status: ACCEPTED (2026-10-23).
New record.
It narrows the existing per-agent contracts; it does not change the model, the compaction thresholds, the token caps, the USD guards, or the trial protocol.*

## Context

The white-jotter trial exposed four context defects.

- The hunter carried a 22,470-char loop tool surface inside the first human message.
  That surface duplicated the request tool descriptions and was uncached on the first call.
- The hunter spec body was a partial human copy of the typed spec.
  It omitted `skills`, four provenance fields, and the bound `run_id`.
- The four hunting roles carried large fixed tool descriptions and several role-local prompt copies.
- The pod runner and triager carried a writable auth store even though neither writes it.

The evidence is in:

- `docs/experiments/hunt-enhancement/THREAT-MODELLER-CONTEXT-ANALYSIS.md`
- `docs/experiments/hunt-enhancement/POD-CONTEXT-ANALYSIS.md`
- `docs/experiments/hunt-enhancement/CHANGES.md`
- `docs/experiments/unit-threat-model-eval-2026-10-20/CONTEXT-DUPLICATION-FORMAL-ANALYSIS.md`

The operator selected the minimal system-prompt cut.
The hand-written `## The tools` section and the direct-reference line stay.
The loop tool surface still goes.
The request tool schema remains the machine contract.

## Decision

### D1 - The request tool definition is the only full tool surface

The loop tool surface is removed from the hunter first human message.
The hunter prompt keeps a complete human summary in `## The tools`.
That summary names every bound tool.
The request tool definition carries the full description and the JSON schema.
No agent prompt carries a second generated copy of the descriptions.

The summary is a routing table, not a second contract.
A missing bound tool in the summary is a defect.
The tests pin the complete name set.

### D2 - Tool descriptions are dense usage projections

The top-level tool description carries only:

- the purpose;
- the operation or command semantics;
- the hard constraints;
- the coded error envelope;
- the one or two clauses a wrong call would lose.

Field-level detail belongs in the pydantic field descriptions.
The request schema remains the full machine contract.

Shared descriptions live in one module and are imported by every binding.
Role-local descriptions stay role-local only when the role's semantics differ.

The hunter's 12 top-level descriptions are bounded at 8,500 chars.
The current committed total is 8,478 chars.
The critical-clause test is `tests/attack/test_tool_description_budget.py`.

### D3 - The spec body is generated from the typed models

The hunter's `## The spec body` is generated from:

- `SpecWrite`;
- `SpecProvenance`;
- `TargetIdentity`;
- `SkillProcedure`.

The projection names every writable field, its type, and its requiredness.
It documents `skills` as the flat pod-runner skill list.
It marks `run_id` as bound and non-writable.
It marks `spec_id` as derived from the two keywords.

A partial human copy is not allowed to drift from the typed models.
The generated projection replaces the hand-written field list.

### D4 - Technical sharpening is a projection

The hunter payload's technical sharpening renders each agreement as:

- `id`;
- `statement`;
- `confidence`.

The agreement evidence entries stay out of the sharpening block.
The loop evidence already carries the request and record references.
The projection keeps every interface, control-flow, and data-flow id and statement.

### D5 - A phase hint is a transition signal

The phase hint is injected only when a pass exits and the ending tool response drives the next pass.
The prompt says this.
The hint remains guidance, never a gate.
No tool call is refused for the pass the tracked state is in.

### D6 - The first human context is pinned through compaction

The four hunting roles pin the leading messages through the first human message.
The roles are:

- `hunting_hunter`;
- `hunting_threat_modeller`;
- `pod_runner`;
- `pod_triager`.

The hunter sends one instance-context message.
It carries the application overview, the loop grounding, the current state, and the step protocol.
The modeller, runner, and triager pin their first human context.
Analysis roles keep the previous fold behavior.

The pin is `compact_pass(..., pin_first_human=True)`.
It is wired through `PIN_FIRST_HUMAN_ROLES`.
It does not change the replay tail, the threshold, or the pass cap.

### D7 - The hunting roles read the auth store, they never write it

The hunter, modeller, pod runner, and pod triager bind `auth_store` in read-only mode.
The full write contract remains for the recon gateway and the operator seed path.

The modeller's `arm_exempt_surface` path binds the read-only contract.
It also carries the project `authn` skill, so it is not the same shape as the analysis-side store-only arming.
That difference is recorded in the #364 ADR amendment.

### D8 - Cached-text removal is an occupancy change, not a miss-ratio win

The provider cache is prefix-based.
Removing cached fixed text lowers total input and cache read.
It leaves the uncached runtime input unchanged.
The miss share therefore rises when only cached text is removed.

The hunter is the exception.
The loop tool surface was uncached on the first call.
Removing it lowers both the first-call uncached input and the miss share.

The measured decomposition is:

| Role | Description text cut, same auth mode | Auth-mode cut | Total production cut |
|---|---:|---:|---:|
| Hunter | 9,648 | 4,649 | 14,297 |
| Modeller | 7,095 | 4,649 | 11,744 |
| Runner | 3,229 | 4,649 | 7,878 |
| Triager | 3,229 | 4,649 | 7,878 |

The shared text cuts are the same constants, not four independent edits.
The role subsets differ because the roles bind different tools.

The cache consequence must be read correctly in later trials.
A lower occupancy is not a lower progressive miss ratio.
The runtime payload bounds are the miss-ratio work.

### D9 - Tool-list completeness is a contract

Every bound tool is named in its role's human tool summary.
The tests pin the name sets for the hunter, modeller, runner, and triager.
The pod triager's terminal vocabulary names the five reasons the critic can decide.
`budget-timeout` is a harness terminal and is not a critic choice.

## Consequences

The hunter first call removes 22,470 chars and 5,361 uncached tokens.
The first-call miss share falls from 35.1% to about 20.9%.

The modeller first call removes about 3,158 cached tokens.
The warm miss share rises from 16.0% to about 19.7%.
The absolute uncached tokens are unchanged.

The runner first call removes about 2,189 cold uncached tokens.
The triager first call removes about 2,230 cold uncached tokens.
The warm miss shares rise slightly because the runtime evidence is unchanged.

The design specs now point at this record for the shared policy.
The per-agent specs carry the concrete surface and prompt changes.

## Residual risks

The spec body is generated at prompt load.
A missing marker fails closed.
A model change that adds a field is reflected without a second edit.

The tool-description budget is tight.
The current hunter total is 8,478 against an 8,500 ceiling.
A new tool or clause needs a compensating cut.

The compaction pin keeps the first human context at full size.
A thread whose pinned context alone exceeds the budget still cannot converge.
The existing pass cap and fail-open barrier remain the safety net.

The trial has not run.
The quality effect on confirmed symptoms is unmeasured.

## References

- `docs/design/hunting-tools-design.md`
- `docs/design/hunting-67-hunting-agent-spec.md`
- `docs/design/hunting-67-threat-modeller-spec.md`
- `docs/design/hunting-67-test-executor-pod-spec.md`
- `docs/design/context-compaction-95-decisions.md`
- `docs/design/hunting-target-front-availability-adr.md`
- `docs/design/auth-store-220-decisions.md`
- `docs/design/analysis-auth-store-view-364-adr.md`
- `docs/design/session-cache-measurement-348-adr.md`
- `docs/design/hunting-context-dedup-impact-map.md`
