# Planned Experiments - Unit Threat Model Eval

## Purpose

This document catalogs concrete edits and extensions that can be measured after the canonical defects are fixed.
Each experiment names the failure or quality defect that motivates it.
Each experiment states the intended solution goal and the measurement that decides it.
No experiment in this document is approved for the white-jotter trial until the operator selects it.

## E-01 - Risk Budget Calibration

**Change:** set `HUNT_RISK_THRESHOLD` to one of three values:
- `36`, the literal `3 x` the default `12`.
- `132`, the `3 x` the observed canary first-unit `risk_total` of `44`.
- A coverage floor that keeps the intake open until every expected service unit is modelled.

**Failure or quality defect:** F-018.
The canary halted at `intake_position=1` with `risk_total=44` against threshold `12`.
The manager units at positions 24, 28, and 29 were never modelled.
The retest used `1000` as a coverage override, not a calibrated value.

**Intended goal:** model every service unit that the target profile declares before the progressive halt can fire.
Keep the halt as a real control for pathological models.
Do not turn the threshold into an unbounded coverage switch.

**Measurement:**
- The intake position of the halt, if any.
- The number of manager units modelled.
- The number of loops and specs produced per unit.
- The pod confirmations per unit.
- The false-positive pod count.

**Risk:** a high threshold can spend the full budget on low-value units.
A threshold of `36` is still below the observed first-unit total of `44`, so it may not fix the coverage miss.
The decision must state whether `default x3` means `36` or `3 x` the observed total.

## E-02 - Statusless Specs, All Ratified by Default

**Change:** remove the `hypothesised` lifecycle state from the write surface.
Every spec is persisted as `ratified`.
The hunter can still record a `dropped` decision explicitly.

**Failure or quality defect:** F-020.
The `/view` SVG draft was written as `hypothesised` and the terminal write omitted it.
The pod dispatch gate only accepts `ratified`, so the draft was never dispatched.
The canary scored comfyui-003 as a complete miss even though the hunter had the right hypothesis.

**Intended goal:** make every written spec pod-eligible.
Measure whether the extra coverage finds real faults or floods the pod path with research-space noise.

**Measurement:**
- Ratified specs per loop.
- Pod runs per spec.
- Pod confirmations.
- Non-ground-truth confirmations.
- Terminal exports per loop.
- Token spend per confirmation.

**Risk:** this is the research-space-noise hypothesis in its strongest form.
It removes the hunter's ability to mark a claim as provisional.
It can increase pod cost and false positives.
It does not by itself fix a hunter that never writes the missing spec.

## E-03 - Hypothesised Specs as Surfer Inputs

**Change:** add `hypothesised` to the surfer's valid consumption states.
The pod session carries the spec with an explicit provisional flag.
A separate ratification step runs before the pod's evidence is promoted.

**Failure or quality defect:** F-020.
The surfer currently consumes only `ratified` specs.
The 16 retest drafts were left in `produced/` and never reached a pod because their hunters were stopped.

**Intended goal:** give a provisional draft a bounded pod probe without treating its evidence as confirmed.
Separate "worth probing" from "confirmed".

**Measurement:**
- Provisional pods started.
- Provisional pods that produce a terminal export.
- Provisional specs promoted to ratified.
- Provisional specs dropped after the probe.
- Confirmed faults that would have been missed by the ratified-only gate.
- Additional token spend.

**Risk:** provisional pods can spend the budget on weak hypotheses.
The pod runner and triager must know the flag and must not report a provisional probe as a confirmed vulnerability.

## E-04 - Forced Loop Terminalization

**Change:** add a symbolic-layer terminalization sweep for every hunter session.
When a hunter stops, fails, or the run quiesces, every produced `hypothesised` spec is either:
- promoted to `ratified` with the hunter's last decision, or
- dropped with a recorded reason such as `run_ended_without_terminal`, or
- re-queued to a fresh hunter with the draft as input.

The sweep runs outside the model and cannot be skipped by a model omission.

**Failure or quality defect:** F-020 and F-022.
The terminal guard catches an omission only when the hunter writes a terminal set.
A stopped hunter leaves drafts and consumed loops with no terminal decision.
The retest had 16 such drafts and 13 consumed loops at the provider pause.

**Intended goal:** make the loop lifecycle complete even when the model or the provider stops early.
Prove that no spec can remain in an undecided state at a run terminal.

**Measurement:**
- Undecided specs at every quiesce point.
- Re-queued hunters.
- Drafts promoted or dropped by the sweep.
- Any duplicate pod dispatch.
- The run's terminal completeness.

**Risk:** a sweep can make a wrong automatic decision.
A re-queue can duplicate work.
The sweep must be idempotent and must preserve the original draft.

## E-05 - Service Link and Route Inventory Seed

**Change:** create the missing L1 service-to-API links and seed the manager route family into L0.
Candidate edits:
- Add the target profile's manager route inventory to the recon job plan.
- Link the L1 `workflow-library` service to `RESTApi:manager-http`.
- Add an `AGGREGATES` or `EXPOSED_VIA` edge for the service alias.
- Seed `/userdata` and `/manager` endpoints when the route inventory is known.

**Failure or quality defect:** F-019.
`workflow-library`, `extension-manager-configuration`, and `model-installation` have zero links in L1.
`RESTApi:manager-http` is a bare data-dependency node.
L0 has zero `/userdata` and zero `/manager` endpoints.
The retest still has 0 of 6 strict unit-level candidates, although class-level coverage reached 5 of 6.

**Intended goal:** bind a hunting spec to the service unit that owns the route, not to the generic `RESTApi:core-http` unit.
Make the manager route family visible to the analysis and the hunter.

**Measurement:**
- L1 links per service.
- L0 route families per service.
- Strict unit-level candidates.
- Specs bound to the correct unit.
- Pod confirmations on the manager routes.

**Risk:** a hard-coded route seed can overfit the comfyui target.
The seed must come from the target profile or the observed recon inventory, not from the ground truth.
The link rule must be general to other multi-service targets.

## E-06 - One Spec per Write

**Change:** make `hunts_store` accept exactly one spec per write.
Add a separate terminal command that finalizes the set.
The symbolic layer fills the run id and the loop provenance.
The model authors only the spec body and its status.

**Failure or quality defect:** F-015 and F-025.
The first canary call was about 16 KB and failed at a delimiter.
The retest call was 13,338 characters and left a nested object open at the first spec boundary.
The typed contract validates only after the relay parser accepts the JSON.

**Intended goal:** make every spec write small, resumable, and independent.
A malformed write loses one spec, not the whole batch.

**Measurement:**
- Tool-call parse failures.
- Specs written per loop.
- Retried calls.
- Terminal set completeness.
- Token spend per spec.

**Risk:** more calls can cost more context.
The terminal finalize must remain atomic.
The store must keep the whole-set completeness guard.

## E-07 - Flatten the Spec Write Payload

**Change:** remove nested optional objects from the model-authored write.
The model sends flat fields for the fault keyword, strategy keyword, target URL, unit id, symptoms, and skills.
The symbolic layer builds the typed `target_identity` and `provenance`.
The store still persists the canonical typed spec.

**Failure or quality defect:** F-025.
The malformed nested object is in the model-authored payload.
The typed schema is good for validation but expensive for the model to serialize by hand.

**Intended goal:** keep the typed store contract while reducing the model's JSON surface.
Measure whether the parse-failure rate falls without weakening validation.

**Measurement:**
- Parse failures.
- Validation rejections.
- Specs accepted per loop.
- Any missing provenance fields.

**Risk:** the symbolic layer must make the same decisions the model made.
Do not drop a field that the pod needs.
The store's `extra="forbid"` contract must stay.

## E-08 - Reasoned Empty Replay

**Change:** when an assistant tool-call message has no reasoning field, emit `reasoning_content: ""` in the outbound request.
Keep the exact reasoning when it is present.

**Failure or quality defect:** F-009.
The retest logged 28 provider 400s because the reasoning field was absent from the replayed tool-call message.
A direct provider probe accepted the empty field.

**Intended goal:** stop the provider rejection without weakening the reasoning replay path.
Measure the 400 count and the readability gap count.

**Measurement:**
- Provider 400 count.
- Reasoning-gap warnings.
- Degraded hunter turns.
- Any provider rejection caused by the empty value.

**Risk:** some provider deployments may require the exact prior reasoning.
The fallback must be limited to absent fields and must be easy to disable.

## E-09 - Graph Schema Guide Hardening

**Change:** teach `USES_TECHNOLOGY`, the Observation identity, and the rule that `label` is not a property.
Add one worked query that enumerates a service's technology and observations.

**Failure or quality defect:** F-010 and F-012.
The model authored `l0.label`, `HAS_TECHNOLOGY`, and `key` against the live graph.

**Intended goal:** reduce model-authored schema errors at the graph tool boundary.
Measure the Neo4j warnings in the next analysis run.

**Measurement:**
- `UnknownPropertyKey` count.
- `UnknownRelationshipType` count.
- Query rows returned.
- Analyst use of the correct edges.

**Risk:** a guide cannot validate every query.
A cheap validator could be a follow-up if the warnings persist.

## E-10 - Gateway Key Log Filter

**Change:** redact `key=` values in the `httpx` logger.
Keep the request contract unchanged unless the gateway supports a body or header form.

**Failure or quality defect:** F-014.
The app wrote a gateway key into its INFO log.

**Intended goal:** remove the secret from the app log without changing gateway behavior.
Measure the log format in a unit test and in one live startup.

**Measurement:**
- The redacted log line.
- The gateway `/key/info` result.
- No key material in the startup log.

**Risk:** a filter can miss a different URL encoding.
The test must cover both `?key=` and `?key=%...` forms.

## Experiment Order

1. Run E-08, E-09, and E-10 as local hardening before the white-jotter trial.
2. Decide E-01 before the trial, because it controls the intake coverage.
3. Decide E-05 before the trial if strict unit binding is a gate.
4. Decide E-02, E-03, or E-04 for the F-020 status model.
5. Decide E-06 or E-07 for the F-025 write contract.
6. Do not combine E-02 and E-03 in one trial; they answer different questions.
7. Do not combine E-06 and E-07 in one trial; they are two independent reductions of the same failure.
