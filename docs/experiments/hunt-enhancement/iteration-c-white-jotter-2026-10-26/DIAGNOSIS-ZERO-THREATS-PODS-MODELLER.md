# Post-run diagnosis: zero-threat units, pod collapse, and the impact-first modeller

Run: `white-jotter-1-20261027T074905-1618c524`, project `8e2e5dc7-a880-4451-aaa5-267cedd48264`.
All claims below are grounded on the persisted artifacts, the Langfuse v2 observations API, and the code at `13ce0edb` plus the live thinking patch.

## Method and loops

Three loops, one per task, all deterministic and re-runnable:

| Task | Loop | Red signal |
|---|---|---|
| 1 zero-threat units | `audit_threat_models.py` + `lf_decisions.py` | a terminal unit with zero threats |
| 2 pod collapse | `audit_pod_lifetimes.py` | a watchdog pod whose wall time or tool share contradicts the budget |
| 3 modeller assessment | `audit_impact_model.py` | a threat with no concrete damage, or a non-damage capability not persisted |

Loop correction 1: the first pod lifetime anchor was the `variants/` directory mtime.
That directory is touched when a later variant lands, so a two-iteration pod looked 82 s long while its session had run an hour.
The anchor is now the earliest pod artifact (variant file or experiment log). After the fix no pod is shorter than 1000 s.

Loop correction 2: the Langfuse legacy trace API returns 410; the v2 observations API with `fields=io` is the only read path.
Two units were initially matched by unit name, which every prompt contains; matching now requires the model path or `unit_id`.

## Task 1: why nine units produced no threat

### The measured fact

| Group | Units | Impact rows | Placeholders | Threats | Precursors |
|---|---:|---:|---:|---:|---:|
| Zero-threat | 9 | 13 | 13 | 0 | 0 |
| Threat-bearing | 14 | 38 | 10 | 28 | 44 |
| Total | 23 | 51 | 23 | 28 | 44 |

All nine zero-threat units are `COMPLETED` and `validation.valid=true`, with empty `missing` and `unclosed` lists.

The nine: `AuthenticationMechanism`, `AuthorizationSystem`, `IdentificationSystem`, `Service:book-management`, `Service:jotter-reading`, `Service:media-asset-serving`, `WebPresentation:library-catalog::catalogue-pages`, `WebPresentation:register::registration-page`, `WebPresentation:sign-in::credential-pages`.

They account for **13 of the 23 placeholders**, which is 56.5 percent of the red rows in the primary metric.

### Trace walk: IdentificationSystem

Five traces, 21:40:08Z to 21:46:39Z, 270 observations.
No `ERROR` or `WARNING` level in any of them.

| Time | Node | Evidence |
|---|---|---|
| 21:40:08 | technical sharpening | 2 `exec` probes, one `hunts_store` write |
| 21:41:46 | prior art | three `hunts_store cmd=query` calls: threat 6,847 B, vulnerability 9,894 B, precursor 7,160 B |
| 21:42:10 | prior-art exit | note allocates every damage direction to a named owner |
| 21:44:32 | vulnerabilities | `V-1` BFLA: authentication substituted for authorization |
| ~21:45 | impact assessed | one row, `disposition: placeholder`, `capability_path: []`, `precursor_refs: []` |
| ~21:46 | completed | `threats: []`, then the validation read |

The prior-art note is the decision node:

> "This unit is the most heavily pre-owned of the run: six existing threats, seven vulnerabilities and eleven precursors already cover every damage-bearing consequence of the identification design. Identifier carriage, cleartext and fixation ... each have an owner. What is left is the design commitment this unit ..."

The impact row then states why no damage is claimed:

> "No user, application or infrastructure property is affected on this deployment as observed. The conflated boundary admits any identified account, but every service behind it re-derives the caller's authority for itself ... Nothing is disclosed and no state changes as a consequence of passing this gate alone; what an attacker gains is admission to a surface whose contents are governed elsewhere, so the loss belongs to those units and is recorded there rather than here."

The claim is factually correct.
`ReverseProxy` `IA-2` records the same boundary as damage: "An unauthenticated caller reaches the administrative mutation handlers and can create, rename, disable or delete accounts ...".

### The same decision in the other units

| Unit | Prior-art decision | Mechanism |
|---|---|---|
| IdentificationSystem | "most heavily pre-owned ... every damage-bearing consequence ... already have an owner" | ownership allocation |
| AuthenticationMechanism | "every harm this unit's probes could reach is already on the board ... a set of NEGATIVE results" | ownership allocation |
| AuthorizationSystem | "every damage this unit can reach is already owned ... what this unit adds is evidential, not additive" | ownership allocation |
| Service:book-management | "every harm this service could reach is already owned ... a qualification rather than a new row" | ownership allocation |
| Service:jotter-reading | "both of this unit's candidate findings are already owned, and precisely so ... cited and not re-filed" | ownership allocation |
| WebPresentation:sign-in pages | "the store already carries both halves of this unit's neighbourhood" | ownership allocation |
| Service:media-asset-serving | "the threat query returns nothing ... no file-serving channel is reachable" | negative-evidence closure |

Eight of nine units allocate their damage to an owner.
One unit closes on negative evidence.
`Service:library-catalog` pages and `register` page follow the same placeholder prose pattern ("the loss ... is the catalogue unit's damage row", "double-count", "already assessed").

### Functional failure modes

None fatal.
The sampled units show seven recoverable tool-schema rejections:

| Unit | Rejection |
|---|---|
| media-asset-serving | `confidence: "DOCUMENTED"` is not in the enum |
| media-asset-serving | `confidence_note` is an extra forbidden field |
| jotter-reading | three `hunts_store` calls missed the required `cmd` |
| jotter-reading | `cmd` sent as a value, literal error |
| sign-in pages | `notes` call missed the required `cmd` |

Each was retried and the model completed.
No truncation, no timeout, no degraded state, no archived unit.

This is prompt and schema drift, not a functional failure: the model reaches for vocabulary (`DOCUMENTED`, `confidence_note`, `cmd` as a flag) that the tool schema does not accept.

### Root cause

Two rules meet:

1. the impact-first model allocates each concrete damage to one owning unit, and a row without concrete damage is a placeholder by design;
2. the spec requires the capability that does not reach damage to survive as a precursor: story 3 says "a precursor entity for a capability that another threat can leverage, so that the capability is not lost when it does not reach damage by itself", and story 11 says "every precursor to live in the store after completion".

The model executed rule 1 and skipped rule 2.
All nine units have `precursors: []` and `precursor_refs: []`.
The validator does not require a precursor to be referenced by a threat, and it permits `precursor_refs` on a placeholder row, so the outcome was avoidable.
The modeller prompt says "every capability entity goes in `precursors`" but never says what to do with a capability that reaches no damage in a placeholder-only unit.

Root cause: **a prompt-contract gap for capability persistence, not a schema limit and not a functional failure.**
My earlier working note called this structurally impossible; that was wrong - the schema allows unreferenced precursors and placeholder `precursor_refs`.

Consequences:

- the enabling capability is named in prose only and cannot be queried by a later unit;
- the metric counts 13 honest, non-duplicated placeholders as red;
- `media-asset-serving` closed GT-006 on six 404s without a repeated-decoded candidate or an in-root control, so the one negative closure in the set is wrong.

## Task 2: why the pod phase collapsed

### The measured fact

| Terminal | Pods | Median probes | Median wall | Median per probe |
|---|---:|---:|---:|---:|
| `symptom-confirmed` | 12 | 11.5 | 2,723 s | 219 s |
| `pod-watchdog-timeout` | 41 | 17 | 3,728 s | 220 s |
| `no-symptom-evidence` | 1 | 9 | 2,046 s | 227 s |
| `space-exhausted` | 1 | 24 | 2,305 s | 96 s |

Fifty-five pods executed 936 probes in **686 s of tool time** inside **189,471 s of pod wall time**.
Tool execution is **0.36 percent** of the wall clock.

Watchdog wall times cluster tightly at the one-hour budget: deciles 3,597; 3,605; 3,613; 3,619; 3,629; 3,728; 3,736; 3,898; 3,923; 3,950; 3,979.

### Hypothesis 1: the watchdog clock is misbound or reused across batches

**Falsified.**

The code path is per session: `asyncio.wait_for(_run(), timeout=session_timeout_s)` with `DEFAULT_POD_SESSION_TIMEOUT_S = 3600.0`, resolved per dispatch from `state.pod_session_timeout_s`.
There is no batch-level clock and no mutation of the value.

The two pods that looked like clock bugs (82 s and 558 s) were anchor artifacts: both had `iterations: 2`, and `variants/v1.yaml` moved the directory mtime.
Their `v0.yaml` files date from the previous batch, and each export lands exactly one hour after the first variant.

The benign tail to 3,979 s is timer-callback and finalizer delay under load, not a reset: the same run has six watchdogs five to six minutes past the hour.

### Hypothesis 2: the executor environment (kali) is saturated

**Not supported as the primary cause.**

Tool calls total 686 s across 936 probes, a median of 6 s of tool time per failed pod.
The container spends 99.6 percent of the wall clock idle from the tools' point of view.

The time is in agent turns: each probe costs two to three generations, and C's generations run at 30 to 72 s median against B.a's 20 to 31 s.

### Hypothesis 3: the pods genuinely needed more than the budget

**Supported, and it is the main cause.**

The success boundary is probe count, not speed:

- confirmed pods needed 11.5 probes at 219 s each, about 2,500 s, inside the hour;
- watchdog pods needed 17 probes at 220 s each, about 3,740 s, past the hour.

Across the run, per-probe cost rose with concurrency:

| Concurrency band | Pods | Median per probe | Median probes |
|---|---:|---:|---:|
| 6 to 9 | 15 | 145 s | 25 |
| 10 or more | 40 | 239 s | 14 |
| B.a, at most 5 | 23 | 60 s | 25 |

Two independent measures agree that turns got slower:

- average context per call rose from **39,329** (B.a) to **70,385** (C), plus 79 percent;
- Langfuse generation medians rose from 19.7 to 30.9 s (B.a) to 29.7, 72.3 and 52.2 s at three C checkpoints.

The first C shell (14 concurrent) still ran at 29.7 s per generation, so concurrency alone does not explain the later 72.3 s.
The honest statement is: sustained shared-host and provider load, plus a larger per-turn context, raised turn latency 1.5 to 2.4 times, and the fixed one-hour budget then bought roughly half the probes.

### Hypothesis 4: pods wait in a queue

**Rejected for the sampled pods.**
Generations occur throughout each pod's window (latencies fluctuate turn to turn), so the pod is not blocked behind a sibling.
There is no silent queue behind the gate: the gate admits a fixed batch.

### Hypothesis 5: startup cost dominates

**Rejected.**
The watchdog pods executed 7 to 43 probes, so startup is a rounding error against the hour.

### Root cause chain

1. `pod_batch_size: 3` raised concurrent pod sessions from at most 5 (B.a) to 15.
2. Per-turn LLM latency rose 1.5 to 2.4 times, with a dose-response inside C: 145 s per probe at 6 to 9 concurrent against 239 s at 10 or more.
3. The pod budget is a fixed 3,600 s per session, while the work is an unbounded agent loop whose size is set by the spec and the runner's judgement.
4. At 220 s per probe the budget covers about 16 probes; specs that needed more returned `pod-watchdog-timeout` mid-plan.
5. The terminal is a budget terminal, not a judgement: the triager never ran, and 38 of 55 exports carry no interpretation.

Secondary defects observed:

- six watchdogs fire five to six minutes late (timer and finalizer delay under load);
- the finalizer converts "unfinished" into a domain-looking export with `verdict: unsuccessful`, so a budget stop is indistinguishable from a tested negative without reading `terminal_reason`;
- the measurement's own attribution of the collapse to batch width is directionally right but incomplete: batch width is an amplifier, the fixed budget against a growing per-probe cost is the cause.

## Task 3: assessment of the impact-first threat modeller

Rubric: the five questions the operator asked.
Evidence: all 28 threats and 44 precursors across 23 models, plus the prior-art records and the Langfuse traces for five units.

### 1. Did it define threats only with severe impact

**No.**

| Impact weight | Threats |
|---:|---:|
| 4 (high) | 8 |
| 3 | 9 |
| 2 | 4 |
| 1 (low) | 7 |

Eleven of 28 threats (39 percent) are weight 2 or below, and seven are weight 1.
Examples: `Service:sign-in` `threat-4` (username enumeration, `low/none/none`), `Service:navigation-menu` `threat-1` (BFLA, `none/none/low`), `WebPresentation:article-management` `threat-1` (CSRF sign-out, `none/none/low`), `WebPresentation:jotter-reading` `threat-1` (stored XSS, `low/none/none`).

The important distinction: the schema fence is **damage existence**, not severity.
The spec says "a placeholder is a row with no concrete end damage" and "a threat row names a concrete victim and property".
It nowhere requires severe damage.
Every one of the eleven low-weight threats does name a victim and a property, so they are correct under the written contract and wrong only under the operator's expected "severe-only" contract.

Judgement: the scope fence that was built is a damage fence.
A severity fence was not built.
The suspicion that low-yield threats leaked through is correct, but they are not violations - they are what the contract permits.

### 2. Was the damage prose sufficiently specific

**Yes.**

| Measure | Value |
|---|---|
| Damage length | 52 to 170 words, median 109 |
| Victim named | yes in every sampled row |
| Property named | yes, mapped to CIA |
| Evidence refs | present on every row; every threat carries at least one evidence (validator-enforced) |

Examples:
`ReverseProxy` `IA-2` names the persisted state, the identities, and the unverified actor.
`Service:sign-in` `threat-2` names the account, the absence of a counter, delay or challenge, and the resulting authenticated session.
`Service:operations-telemetry` `threat-2` names the end user and the activity pattern as the lost property.

The prose is not boilerplate: the five sampled units differ in victim, property, and reasoning.
The one weak spot is that the victim is sometimes implicit ("that account") rather than stated as "the victim is ...", but the referent is unambiguous.

### 3. Did it classify non-severe findings as precursors

**No.**

Two facts:

- the nine placeholder-only units wrote **zero precursors**, even where the prose names a capability ("admission to a surface whose contents are governed elsewhere");
- low-severity findings were authored as **threats**, not precursors: enumeration, the identifier oracle, the CSRF sign-out and the UI-level BFLA all became weight-1 threats with their own paths.

So the model does not use precursors as the bucket for "capability that does not reach severe damage".
Precursors are used only as steps inside a damage-bearing path.

There is one internal inconsistency worth naming: `Service:sign-in` carries enumeration twice.
`threat-4` is the enumeration finding at weight 1 with path `[P-4]`, and `P-4` ("distinguish registered account names from unregistered") is also the first step of `threat-2`, the weight-4 unbounded-guessing threat.
The same capability is both a standalone threat and a step of a stronger threat.

### 4. Did it query for precursors and reuse store threats as capability steps

**Queried: yes. Reused as structural steps: no.**

Prior-art queries across the 23 units:

| Query kind | Queries |
|---|---:|
| threat | 25 |
| vulnerability | 24 |
| precursor | 24 |
| assumption | 3 |
| impact | 3 |

Every unit ran at least one query of each of the three required kinds.
Reused records: 50 vulnerabilities, 26 threats, 27 precursors, 2 assumptions, 2 impacts.

The structural limit: `threats[].enabling_precursors` must name `precursors[].id` of the same model, and the validator compares the set to the row's `capability_path`.
A store precursor from another unit can therefore be cited in `prior_art.reused` but can never appear in a capability path.
Reuse is narrative: the model reads the owner's record and either defers to it (placeholder) or cites it in prose.

That is a real design gap against story 11 ("every precursor to live in the store after completion, so that a later unit can query it"): later units can query it, but the path cannot compose it.

### 5. Well-formedness of the capability paths

**Structurally valid, semantically uneven.**

| Path length | Threats |
|---:|---:|
| 1 | 6 |
| 2 | 20 |
| 3 | 2 |

All 28 threats carry a non-empty path, and the validator enforces `set(enabling_precursors) == set(capability_path)`, so no path is dangling.
The precursor text is capability-shaped, not request-shaped: "obtain a live session identifier without authenticating", "plant a caller-chosen session identifier into a victim's request", "set what the application records".

But a one-step path is a precondition, not a path: `threat-4` (enumeration) has `[P-4]`, and `threat-3` (identifier oracle) has `[P-5]`.
Six threats are modelled as a single capability with no route to the damage.
Order is sometimes meaningful and correct (`Service:article-management` `threat-1` uses `[P-2, P-1]`: reach the write, then persist markup), and sometimes arbitrary within a pair.

The paths are fit to hand the hunter an attacker position, which is their stated purpose.
They are not a causal chain in the DAG sense, and the design does not claim they are.

### Dedupe consistency

The same ownership rule that suppressed 13 findings did not catch a real duplicate: `ReverseProxy` `threat-3` (risk 6) and `Service:sign-in` `threat-2` (risk 8) both claim unbounded credential guessing against the only verification path.
The two rows describe the same damage in near-identical words.
Either the edge and the application are two enforcement points of one fault, in which case one row is redundant, or they are two faults, in which case the 13 suppressions rest on a stricter rule than the one applied here.
The model states no principle that distinguishes the cases.

### Critical verdict

The impact-first rewrite is functionally alive.
Every unit produced impact rows, every threat carries a concrete victim and property with evidence, the prior-art phase ran the required queries in every unit, and the CIA scoring is derived from the damage rather than asserted beside it.
That is a real capability, not a schema veneer.

Three claims in the design are not delivered:

1. **Severity fencing.** The fence is damage-existence. If the operator wants only severe findings dispatched, the low weights must be routed to precursors or dropped, and that rule does not exist.
2. **Capability persistence.** Non-damage capabilities are not persisted as precursors, so the store cannot feed a later unit's path, which is the stated reason for the precursor entity.
3. **Cross-unit composition.** Paths cannot reference store precursors, so reuse stops at citation.

Two further defects are measurable and independent of the design intent:

4. **Double counting inside a unit** (enumeration as both threat and step) and **across units** (rate-limit in two units).
5. **Placeholder dilution is structural**, not evasion: 13 of 23 placeholders come from honest ownership allocation, so the 90 percent `green_share` gate cannot be met by a full-surface run.

## Recommendations, in dependency order

1. **Prompt-contract fix: persist non-damage capabilities.**
   In `IMPACT_ASSESSED`, require a precursor for every capability the unit proves that does not reach damage, and set `precursor_refs` on the placeholder row.
   The schema already permits it; only the prompt and the examples are missing.
2. **Decide the severity fence explicitly.**
   Either accept low-weight threats (then stop calling the fence a severity fence), or add a rule that weight 1 and 2 findings are authored as precursors and not threats.
   Do not leave the intent implicit.
3. **Make the path composable.**
   Allow `capability_path` entries to name a store precursor (`<unit>::P-x`) so a later unit can build on a cited capability.
4. **Dedupe rule with a test.**
   Require a same-damage query before a threat is written and cite the owner or the distinguishing factor; the rate-limit duplicate shows the current rule is applied unevenly.
5. **Pod budget sized to the work.**
   The fixed 3,600 s is below the observed cost of a 17-probe spec at 220 s per probe.
   Either raise the budget, cap the probes per spec, or make the budget adaptive; and stop the watchdog from being the normal terminator (41 of 55).
6. **Batch width 1 until turn latency is characterised.**
   Batch 3 is the amplifier, not the root cause, but the run cannot afford the amplification.
7. **Measurement: repair the candidate matcher before the next arm** so a spec/GT name mismatch does not hide four exact matches, and report "watchdog" and "no interpretation" as quality signals, not as verdicts.

## Evidence appendix

| Artifact | What it settles |
|---|---|
| `audit_threat_models.py` | per-unit threats, impact rows, placeholders, precursors |
| `audit_impact_model.py` | per-threat weight, CIA vector, damage length, path |
| `audit_pod_lifetimes.py` | per-pod anchor, wall, probes, tool time, terminal |
| `lf_decisions.py` | prior-art note, impact write, threats write, tool errors |
| `lf_unit_trace.py` | full observation timeline for one unit |
| `lf_trace_tools.py` | tool inventory and validation issues per trace |
| `hunting/threat_modeller/*/*.yaml` | 23 models, 28 threats, 44 precursors |
| `hunting/test-executor-pod/*/*.yaml` | 55 exports, 936 probes |
| Langfuse v2 observations | 5 traces for IdentificationSystem, 8 traces in the media-asset-serving window |
| `src/polymerhus/attack/hunting/surfer.py:1078` | `asyncio.wait_for(..., timeout=3600)` per pod |
| `src/polymerhus/attack/hunting/threat_model.py:876-910` | placeholder and precursor invariants |
| `src/polymerhus/attack/hunting/prompts/threat-modeller.md:200-226` | impact and precursor prompt |
| `docs/design/impact-assessment-system-spec.md:63,71,72` | precursor persistence stories 3, 11, 12 |
