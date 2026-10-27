# Iteration C - white-jotter, impact assessment as a first-class citizen

*Status: pre-registered 2026-10-26. Extends `../iteration-b-white-jotter-2026-10-25/RESULTS.md` (iteration B) and `ITERATION-BA.md` (iteration B.a). Run state and results are filled progressively.*

## What this iteration changes

Iteration C is a design change, not a knob change: the threat model now carries an explicit **impact assessment**, and the eval measures damage rather than class membership.

The merged trunk (`1b83126c`, eval head `8da28a6f`) adds:

- an `impact_assessment` section to the unit threat model, with one row per damage claim and a `disposition` of `threat` or `placeholder`;
- a CIA vector (`confidentiality`, `integrity`, `availability`) on every damage-bearing threat, scored by the store into the impact sub-score, the ordinal impact weight, and the combined risk;
- the impact block rendered into the hunter payload as context, so the hunter knows the end damage its symptoms must reach;
- a **promotion floor** (`promotion_risk_threshold`) that keeps below-floor threats in `produced/` as evidence and does not dispatch a hunter for them;
- a **pod batch width** (`pod_batch_size`) that dispatches that many hunts' pods together in `batched`.

The eval configuration for this arm:

| Attribute | Value |
|---|---|
| Analysis thinking | assigner and mechanism typist `max` -> wire `max` |
| Threat modeller / hunter | `max` -> wire `max` |
| Pipeline sync | `batched` |
| Pod batch size | 3 |
| Promotion risk threshold | 0 (stored, inclusive: promotes every threat) |
| Risk threshold (cumulative halt) | 180 |
| Recon jobs | `httpx, httpx_reprofile, katana, jsluice, arjun, ffuf, kiterunner` |
| Token budget | 7,000,000 capped |
| Wall clock | 43,200 s (12 h) |
| SkillEvolution | off |

The promotion floor is deliberately inert in C.
This is the control arm for the impact system: every produced threat reaches a hunter, so the filter is proven wired without changing which threats are hunted.
A later arm varies the floor with the impact system held constant.

## Hypothesis

Promoting the impact assessment to a first-class model section should make the threat set describe damage rather than technique family, and should make the hunter's symptoms aim at end damage.

The expected effects are:

- a high `green_share` on impact rows, because a threat row is damage-bearing by construction and only placeholder rows are red;
- a severe share that tracks the impact distribution rather than the class mix;
- the same or better official discovery than iteration B.a, because damage-bearing threats carry a concrete end state into the hunter payload;
- no collapse in class binding or in spec depth.

The promotion gate is not exercised in C, so no token saving is predicted from it.
The pod batch width of 3 may raise pod concurrency and should raise effective parallelism without breaking the one-unit barrier.

## Primary metric

The impact-bearing share, also called `green_share`, defined by `docs/design/impact-assessment-system-spec.md` section 9 over every `impact_assessment` row of every modelled unit:

- `impact_rows` = every `impact_assessment` row;
- green when any CIA value is not `none`;
- red when every CIA value is `none`;
- a placeholder row is red by the invariant;
- `green_share = green / impact_rows`.

Success gate: `green_share` greater than 90%.

The retired class-based green share (class in the high-yield set) is computed and reported as a **continuity note**, marked superseded.
It is not a gate.
The class-binding rate is a diagnostic only.

## Secondary metrics

- The severe share: `threats with impact_weight >= 3 / damage-bearing threats`.
- The placeholder share, and the count of placeholder rows.
- The CIA distribution per metric and level.
- The impact-weight distribution.
- Capped tokens per green row, per severe threat, and per identified ground truth.
- The token split per agent, and the modeller's share of the capped spend.

## Narrowing metrics

- `downstream.spec_count` per threat, and `substantial` at three or more specs.
- `downstream.primary_axes` and `axes_overlap`.
- `downstream.well_formed`: substantial, every spec carries a discriminator, and the primary axes do not overlap.
- `narrow_without_well_formed` and `broad_without_well_formed`.
- The class-binding rate as a diagnostic.

The narrowing metrics report.
They do not gate the run.

## Analysis-specific metrics

- Assigner capped tokens, calls, and reasoning share.
- Mechanism-typist capped tokens, calls, and reasoning share.
- Analysis wall clock from recon drain to analysis drain.
- Endpoint placement count and share of the L0 surface.
- Systems with a witness edge.

## Promotion and batch checks

- `threats_promoted` equals `threats_stored`, because the floor is 0.
- `threats_demoted` is 0; any non-zero value is a finding against the filter or the risk scoring.
- The hunting run record carries the frozen `pod_batch_size`, `promotion_risk_threshold`, and `risk_threshold`.
- The live hunt count never exceeds 3.
- The live unit count never exceeds 1.
- A batch advances only when every consumed spec in it has a terminal export.

## Guardrails

- The 7M capped token budget is the authority; the run stops on it or at 12 h.
- SkillEvolution stays off.
- The target is a fresh project on the same `webexploitbench/white-jotter` image.
- No `auth_store view:full`.
- The terminal must be a success (`complete`, or `stopped` at the cap or the deadline) for assessment to run.

## Procedure

1. Bring up `white-jotter-1` with `next_target`.
2. Run `orchestrator trial` with the C setup, `--budget-s 43200`.
3. Monitor `/projects/{id}/usage`, the unit models' impact rows, the promotion split, the hunting status, and the pod batch width.
4. At the terminal, run the monitor to convergence (assessment, then diagnosis).
5. Run `close-verify`, `store materialize`, and `measure_trial.sh`.
6. Run `measure_iteration_c.py` for the impact metrics, and copy every artifact into `artifacts-c/`.

## Analysis plan

The primary is compared against the 90% gate and reported standalone, because iterations B and B.a carry no `impact_assessment` rows and their `green_share` is undefined.

Comparisons against B and B.a use the metrics that are defined in both schemas:

- official discovery: `identified`, `partial`, `missed`;
- the severe share, with the same impact-weight definition;
- tokens by agent and by phase;
- coverage: units modelled, units consumed, threats specced, specs, pods;
- the retired class-based green share, as a continuity note.

Two baselines are reported:

| Baseline | Commit | What it controls |
|---|---|---|
| B | `81522a71` | the last arm before impact became first class |
| B.a | `553e33c2` | the same analysis max-thinking thread on the pre-impact trunk |

## Limitations

- One trial per arm on one target.
- The arm carries the impact system, the promotion wiring, the batch width, the higher risk halt, and the two extra recon jobs at once. Only the impact system is the design variable; the rest are configuration, and the report separates them where the evidence allows.
- The promotion floor is inert by design, so C cannot answer whether promotion saves tokens.
- `green_share` is near 1.0 by construction unless placeholders are produced, so the metric's discriminating power is the placeholder rate, not class quality.
- Iterations B and B.a cannot supply a `green_share` baseline.

## Run state

*Filled during the run.*

| Attribute | Value |
|---|---|
| Eval head | `13ce0edb` (impact merge `1b83126c` plus the eval hunting-config schema) |
| Thinking patch | assigner and mechanism_typist `max`; live check: all four roles wire `max`, `exact-match` |
| Setup | `eval/setups/white-jotter-iteration-c.yaml` |
| Target | `webexploitbench/white-jotter` |
| Target id | `white-jotter-1` |
| Target run id | `iterc-white-jotter` |
| Trial command start | `2026-10-26T20:03:33Z` |
| Target backend | `127.0.0.1:32979` (re-provisioned, clean database) |
| Stack fingerprint | `112e9c3b05bc155d8a087d4131764d6ffc532af8c8a47bc645ddb053babd2407` |
| Runs root | `/opt/polymerhus-dev/eval/runs-iteration-c-20261026` |
| Project id | `8e2e5dc7-a880-4451-aaa5-267cedd48264` |
| Project created | `2026-10-26T20:07:29Z` |
| Frozen hunting config | `batched`, `pod_batch_size=3`, `promotion_risk_threshold=0`, `risk_threshold=180` (verified live) |
| Hunting run id | `65ec294b-e5cf-49c6-9f7c-4664a73aa557` |
| Run record check | `pipeline_sync=batched`, `risk_threshold=180`, `threshold_basis=db`, `pod_batch_size=3`, `promotion_risk_threshold=0` (verified live) |
| Trial record | pending |

### Harness lineage finding

The eval harness checkout (`/opt/polymerhus-dev`, branch `dev`) and the eval arm code (`/opt/polymerhus-dev/eval/instances/eval-server-1`, the trunk) are separate git worktrees on separate lineages.
The harness plugin that runs `next_target` and `eval_monitor` hardcoded `PYTHONPATH=eval`, so the tool parsed the arm setup with the harness schema, not the arm schema.
The first launch failed with `unknown field(s): hunting`.

The fix is configuration-layer only:

- the plugin now reads `process.env.EVAL_ORCHESTRATOR_PYTHONPATH ?? "eval"`;
- the driver exports `EVAL_ORCHESTRATOR_PYTHONPATH="$INSTANCE_DIR/eval:eval"` and the same path on its own `PYTHONPATH`.

The plugin file is backed up at `eval-monitor.ts.bak-iterc`.
After the fix, `next_target` parsed the setup and brought the target up.


## Progressive findings

### The risk halt fires on the back-office surfaces

The intake is 27 units in risk-descending order.
The page-presentation tail adds almost nothing: at 15 units the cumulative risk was 124, and the next five page units added 0, 0, 1, 0, and 1.
An intermediate projection read that as a run that could not reach 180.

That projection was wrong.
The two back-office REST surfaces carry the remaining risk:

| Unit | Risk |
|---|---:|
| `Service:user-administration` | 12 |
| `RESTApi:actuator-management` | 23 |
| `Service:operations-telemetry` | 24 |

The total went from 138 to **185** on `Service:operations-telemetry`, so the halt fired at 23 of 27 units.
`Service:password-recovery` is the blocked unit.

The lesson is about the intake ordering, not the threshold: a risk-descending order that puts page presentations before the actuator and telemetry surfaces makes the intermediate total look saturated long before the real crossing.

### Batch width three overloads the pod host

`pod_batch_size: 3` dispatches three hunts' pod sets together.
On `ReverseProxy` that produced 25 pods in two shells: 14 at dispatch, then 11.

| Arm | Batch | Concurrent pods | Watchdog terminals |
|---|---:|---:|---:|
| B.a | 1 hunt | at most 5 | 1 of 33 |
| C | 3 hunts | 14 | **16 of 25** |

The timeout exports carry `iterations: 1`, `clean: false`, and no interpretation, so the pods hit the watchdog during their first variant and returned nothing.
The second shell was worse (9 of 11) than the first (7 of 14), which is consistent with accumulating load on the agent container rather than a per-spec defect.

The batch therefore buys wall-clock parallelism at a 64% pod failure rate on the first unit, and every failed pod still spends its budget.
This is the clearest configuration regression in the arm and it is independent of the impact system.

### Coverage is the dominant cost

The arm modelled 23 units against 5 in iteration B and 5 in iteration B.a.
The modeller spent 1,945,435 capped on those units, which is 84,584 per unit and 46% of everything spent before the first pod ran.

Every produced threat is promoted, because the floor is 0.
The hunter therefore faces the whole 23-unit queue, and the 7M budget cannot drain it.

### The new primary metric dilutes with coverage

`green_share` is computed over every `impact_assessment` row of every modelled unit, and a placeholder row is red by construction.

| Units completed | Impact rows | Green | `green_share` |
|---:|---:|---:|---:|
| 7 | 22 | 17 | 77.3% |
| 9 | 26 | 18 | 69.2% |
| 13 | 30 | 20 | 66.7% |
| 15 | 34 | 20 | 58.8% |

Every zero-impact unit adds rows and no green.
The presentation units (`AuthorizationSystem`, `IdentificationSystem`, `navigation-menu`, `jotter-reading`, the `WebPresentation` page systems) contribute 14 red rows and one green between them.

The 90% gate is therefore unreachable on a full-surface run: it can only be met by a run that stops early enough to exclude the non-damage-bearing tail.
That is a property of the metric and the halt together, not a quality regression in the threat models.

## Results

*Filled after the trial terminal.*

### Primary metric: green_share

| Metric | Value |
|---|---:|
| Impact rows | 51 |
| Green (any CIA value not `none`) | 28 |
| Red (all `none`) | 23 |
| Placeholder rows | 23 |
| `green_share` | **54.9%** |
| Gate | 90% |
| Gate met | **no** |

The whole red count is placeholder rows: all 28 damage-bearing rows are green by the invariant, so `green_share` equals `threat_share` exactly, as the spec predicts.
The metric therefore reports the placeholder rate of the modelled surface, which is 45.1%.

Iterations B and B.a carry no `impact_assessment` rows, so this metric has no baseline in this experiment line.
The 90% gate cannot be met by a run that models the whole surface, because 10 of the 23 modelled units carry no damage of their own and contribute placeholders.

### Severe share

| Metric | Value |
|---|---:|
| Damage-bearing threats | 28 |
| Severe (impact weight 3 or 4) | 17 |
| `severe_share` | **60.7%** |

For comparison on the same definition, iteration B.a had 15 of 23 severe (65.2%) over its five modelled units.
C is 4.5 points lower over 23 units, which is the expected direction when the surface expands into units with no damage.

### Official discovery result

| Verdict | B | B.a | C |
|---|---:|---:|---:|
| `identified` | 0 | 1 | **3** |
| `partial` | 1 | 1 | 1 |
| `missed` | 6 | 5 | 3 |
| Identification rate | 0% | 14.3% | **42.9%** |
| Partial-or-identified | 14.3% | 28.6% | 57.1% |

The three identifications:

| Vuln | Unit | Class | Confidence |
|---|---|---|---:|
| `white-jotter-002` | `ReverseProxy` | `bfla-alternate-path` | 0.95 |
| `white-jotter-005` | `RESTApi:api` | `sql-injection` | 0.95 |
| `white-jotter-007` | `Service:register` | `mass-assignment-nested-relation-write` | 0.95 |

`white-jotter-001` is partial at confidence 0.45, the same verdict as both earlier arms.
`003`, `004`, and `006` are missed at confidence 0.95.

Two of the three identifications (`005` SQL injection on `RESTApi:api`, `007` mass assignment on `Service:register`) are in units that iteration B's risk halt at 110 never reached.
That is the coverage effect of the 180 halt, not a per-threat quality effect.

### Impact assessment inventory

The 51 rows distribute across the CIA axes as follows:

| Level | Confidentiality | Integrity | Availability |
|---|---:|---:|---:|
| high | 15 | 10 | 0 |
| medium | 3 | 5 | 1 |
| low | 7 | 0 | 3 |
| none | 26 | 36 | 47 |

Availability is almost unused: 47 of 51 rows are `none`, and no row scores `high` or `medium` availability above one.
Confidentiality dominates the damage claims, which matches a web application whose ground truths are disclosure and authorization bypass.

Rows per unit range from 1 to 7.
`ReverseProxy` carries 7 rows (6 green), `Service:sign-in` 4 (4 green), `RESTApi:api` 4 (3 green), and ten units carry exactly 1 or 2 rows, most of them placeholders.

### Promotion and batch checks

| Check | Result |
|---|---|
| Stored threats | 28 |
| Promoted | 28 |
| Demoted | **0** |
| Promotion floor frozen in the record | 0 |
| `pipeline_sync` frozen | `batched` |
| `pod_batch_size` frozen | 3 |
| `risk_threshold` frozen | 180 (`basis db`) |

The inert floor behaved exactly as specified: every stored threat reached a hunter, and nothing was demoted.

The batch width did not behave as intended.
The hunting status surface reports `live_hunts: 0` while a shell of pods runs, so the monitor's width assertion could not fire; the width must be read from pod dispatch times.
Observed shells: 14 pods, then 11, then 9, then 6, then 4, with a peak of 15 concurrent pods.

### Narrowing metrics

| Metric | Value |
|---|---:|
| Specs total | 69 |
| Specs ratified | 55 |
| Substantial threats (3 or more specs) | 14 of 28 (50%) |
| Well-formed sets | **0** |
| Class-binding rate | 100% |

Well-formedness is zero for the second arm in a row.
Every substantial set repeats at least one primary axis.
The spec count is higher than B.a's 46, but more of it is spread across units rather than concentrated per threat.

### Continuity: the retired class-based green share

| Metric | C |
|---|---:|
| Green narrow (high-yield set) | 19 of 28 (67.9%) |
| Green broad | 20 of 28 (71.4%) |
| Class binding | 28 of 28 (100%) |

Marked superseded.
It is reported only so the arm can be placed beside B (38.5%) and B.a (69.6%) on the metric those arms gated on.
On that axis C sits between the two, with a larger denominator and a much larger modelled surface.

### Token tax

| Agent | Capped | Share |
|---|---:|---:|
| `job_orchestrator` | 44,309 | 0.6% |
| `triager` | 88,821 | 1.3% |
| `assigner` | 57,844 | 0.8% |
| `mechanism_typist` | 362,107 | 5.2% |
| `hunting_threat_modeller` | 1,945,435 | 28.1% |
| `hunting_hunter` | 1,746,311 | 25.2% |
| `pod_runner` | 2,302,123 | 33.3% |
| `pod_triager` | 372,188 | 5.4% |
| **Total** | **6,919,138** | **100%** |

By phase: analysis 553,081 (8.0%), modelling 1,945,435 (28.1%), hunt authoring 1,746,311 (25.2%), pods 2,674,311 (38.7%).

Against B.a the analysis block rose from 404,995 to 553,081, driven by a longer recon (seven jobs) and a larger L1 surface.
The modeller doubled from 947,902 to 1,945,435, which is the price of 23 units instead of 5.

### Segment analysis

| Ratio | Value |
|---|---:|
| Capped per modelled unit | 300,832 |
| Capped per stored threat | 247,112 |
| Capped per confirmed pod | 576,595 |
| Capped per identified ground truth | **2,306,379** |

The last row is the honest headline: three identifications for the whole budget.

The pod phase is the efficiency failure.
55 pods produced 12 confirmations, 21.8%, against B.a's 23 of 33 (69.7%).
The pods consumed 2,674,311 capped, so each confirmation cost 222,859 in pod spend alone and each watchdog terminal cost about 48,000 of wasted budget.

Modelling 23 units was cheaper per unit than B.a (84,584 against 189,580) because most units are small.
Coverage was therefore affordable; the hunt was not.

### Budget outcome

| Budget | Target | Actual | Outcome |
|---|---:|---:|---|
| Risk | 180 | **185** | **exceeded** |
| Tokens | 7,000,000 | 6,919,138 | 98.8%, not exceeded |
| Wall clock | 43,200 s | 42,332 s | operator stop 7m before the deadline |

The risk budget was exceeded and the halt fired on `Service:operations-telemetry`.
The token budget was not exceeded: at the observed burn the deadline would have fired first, and a deadline terminal is `timeout`, which the monitor defers instead of assessing.
The operator stop at 07:48:56Z secured a `stopped` terminal with 80,862 tokens unspent.

## Workflow and contract findings

Four defects surfaced in the harness while C ran.
None is caused by the impact system, and all four cost time rather than verdict quality.

### The lineage split broke the diagnosis dispatch

The harness checkout (`/opt/polymerhus-dev`, branch `dev`) and the arm checkout (`/opt/polymerhus-dev/eval/instances/eval-server-1`) are separate worktrees on separate lineages.

The arm setup now parses correctly because the plugin reads `EVAL_ORCHESTRATOR_PYTHONPATH`.
The prompt path does not: the monitor's diagnosis dispatch passed `eval/prompts/diagnoser.md` as a relative path, which resolved against the harness checkout where that file is absent or different.

The monitor bounded its retries and escalated with a named failure instead of hot-looping or editing code, which is the specified behaviour.
`close-verify` then repaired the node at the configuration layer: it re-ran the assessment (attempt 2, identical verdicts) and re-dispatched the diagnoser with the absolute instance path.

The trial record shows both assessment attempts and no failure:

| Field | Value |
|---|---|
| `assessment.status` | `present` |
| `assessment.attempts` | 2 (`07:55:23`, `08:11:35`) |
| `assessment.failure` | null |
| `diagnosis` | filled by the re-dispatch |

Recommended fix, in preference order:

1. Launch the eval orchestrator with `--dir` at the instance worktree, so relative prompt paths resolve in the arm lineage.
2. Make `assessment.launch_message` and the diagnosis equivalent use `request.prompt` (absolute) instead of the relative `eval/prompts/...` string.
3. Align the canonical harness `eval/` with the arm sha.

This is the second occurrence of the same split: the first broke `next_target` with `unknown field(s): hunting`.

### The deadline terminal is not assessable

`SUCCESS_TERMINALS` in `eval/orchestrator/monitor.py` is `{complete, stopped}`, and a trial that reaches its wall-clock deadline writes `timeout`.
The monitor therefore defers a deadline-bounded run and never assesses it, even when the phases completed cleanly and the evidence is intact.

C was 28 minutes from its 12h deadline at 6.86M of a 7M cap.
Continuing would have produced `timeout` and skipped assessment, diagnosis, and measurement.
The operator stopped the project at 07:48:56Z so the trial wrote `stopped`.

This is a contract gap: a wall-clock-bounded arm cannot be assessed without an operator intervention.
Two candidate repairs are for the configuration or code owner to choose:

- treat `timeout` with a completed phase set as assessable, as the surfer already treats `interrupted`; or
- have the deadline write `stopped` with a `deadline` cause on the phase, parallel to the budget stop.

### The hunting status surface hides live pods

`GET /projects/{id}/hunting/{run_id}` reported `live_hunts: 0` and `live_units: []` for the whole pod phase, while 14 to 15 pods were running and exporting.

The monitor's batch-width assertion could therefore not fire from the status field.
Width has to be inferred from pod directory mtimes or resume files, which is what the final measurement did.

A status surface that reports zero live work while a batch is in flight also hides a stuck batch from an operator.

### The batch width is not asserted anywhere

`pod_batch_size: 3` is frozen into the run record and honoured by the hunter, but no component checks the resulting concurrency against the host capacity.
The observed peak was 15 concurrent pods on a host that B.a exercised with at most 5.

The failure mode is silent: pods dispatch, exceed the agent-container capacity, and return `pod-watchdog-timeout` with `iterations: 1`.
The run pays for each one.

## Evidence appendix

- Eval change: `eval/orchestrator/setup.py`, `eval/orchestrator/trial.py`, `eval/orchestrator/api.py`, `eval/orchestrator/cli.py`, `tests/eval/test_orchestrator_hunting_config.py`
- Setup: `eval/setups/white-jotter-iteration-c.yaml`
- Driver: `drive_iteration_c.sh`
- Monitor: `monitor_iteration_c.py`
- Measurement: `measure_iteration_c.py`
- Baselines: `../iteration-b-white-jotter-2026-10-25/RESULTS.md`, `../iteration-b-white-jotter-2026-10-25/ITERATION-BA.md`
