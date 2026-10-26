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
| Eval head | `8da28a6f` (impact merge `1b83126c` plus the eval hunting-config schema) |
| Setup | `eval/setups/white-jotter-iteration-c.yaml` |
| Target | `webexploitbench/white-jotter` |
| Target id | `white-jotter-1` |
| Target run id | `iterc-white-jotter` |
| Runs root | `/opt/polymerhus-dev/eval/runs-iteration-c-20261026` |
| Project id | pending |
| Hunting run id | pending |
| Trial record | pending |

## Results

*Filled after the trial terminal.*

### Primary metric: green_share

Pending.

### Severe share

Pending.

### Official discovery result

Pending.

### Impact assessment inventory

Pending.

### Promotion and batch checks

Pending.

### Narrowing metrics

Pending.

### Continuity: the retired class-based green share

Pending.

### Token tax

Pending.

### Segment analysis

Pending.

### Workflow and contract findings

Pending.

### Failure and error findings

Pending.

### Learnings

Pending.

### Recommendation

Pending.

## Evidence appendix

- Eval change: `eval/orchestrator/setup.py`, `eval/orchestrator/trial.py`, `eval/orchestrator/api.py`, `eval/orchestrator/cli.py`, `tests/eval/test_orchestrator_hunting_config.py`
- Setup: `eval/setups/white-jotter-iteration-c.yaml`
- Driver: `drive_iteration_c.sh`
- Monitor: `monitor_iteration_c.py`
- Measurement: `measure_iteration_c.py`
- Baselines: `../iteration-b-white-jotter-2026-10-25/RESULTS.md`, `../iteration-b-white-jotter-2026-10-25/ITERATION-BA.md`
