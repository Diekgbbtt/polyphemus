# Iteration B - white-jotter impact-elicitation experiment

*Status: completed 2026-10-26. Ticket: 422. Result: `RESULTS.md`. Baseline: `docs/experiments/white-jotter-batched-2026-10-24/TOKEN-USAGE-AND-CONTEXT-OCCUPANCY.md` and `docs/experiments/modeller-impact-quality/BASELINE.md`.*

## Hypothesis

The impact-first threat modeller produces a threat set that is more than 90% green, without collapsing the hunter's discrimination space.

The arm adds four changes on top of the 2026-10-24 arm A:

1. The threat modeller works the four trust axes: identity, spatial, temporal, and controls semantics.
2. Every threat scores end impact over the application and its users with `VC`, `VI`, and `VA`.
3. The well-formedness phase re-checks the trust assumptions against the web-vulnerability class skill bound to each vulnerability.
4. The hunter collects the discrimination-axis instances from the bound skill first.

Two system changes keep the arm honest:

- The whole skill-evolution system is off: no evolver controller, no meta-write-skill read, no `record_skill_lesson` tool, and no lesson line in the pod prompts.
- `auth_store` no longer offers `view:full`; the HTTP-history list tool uses the tightened data contract from `55d10e65`.

## Arm definition

| Attribute | Value |
|---|---|
| Branch | `hunt-enhancement-trunk` at the commit that carries ticket 423 |
| Target | `webexploitbench/white-jotter` |
| Target run id | `iterb-white-jotter` |
| Project | fresh project, created by the trial |
| Start phase | `recon` |
| Pipeline sync | `batched` (the code default, frozen in the run record) |
| Token budget | 7,000,000 capped tokens for the whole trial |
| Risk threshold | `HUNT_RISK_THRESHOLD=110` |
| SkillEvolution | `SKILL_EVOLUTION_ENABLED=0` |
| Threat modeller model | `opencode-go:deepseek-v4.1-flash` |
| Hunter model | `opencode-go:deepseek-v4.1-flash` |
| Threat modeller thinking | `xhigh`, negotiated to the provider maximum |
| Hunter thinking | `xhigh`, negotiated to the provider maximum |
| Reconv jobs | `httpx, httpx_reprofile, katana, jsluice, arjun` |

## Primary metric

The green-threat share over all stored threats.
A threat is green when its `web_vulnerability_class` is in the ratified high-yield set plus CSRF and clickjacking, rolled up to its class parent.

Success gate: more than 90% green threats.

## Secondary metrics

- The severe share: threats whose end impact is severe.
- The sharp-boundary share: threats whose trust boundary is attacker-artifact-to-security-decision.
- The class-binding rate: threats whose `web_vulnerability_class` resolves to a suite class.
- The severe threats below the medium risk bucket.
- Capped tokens per green threat.
- The token split per agent.
- The modeller's share of the capped budget.

## Narrowing metrics

- `bound_class_is_parent`: the bound class is a suite parent (`broad`), a leaf (`narrow`), or absent (`unknown`).
- `downstream.spec_count`: the specs linked to the threat by `provenance.threat_id`.
- `downstream.substantial`: at least three specs.
- `downstream.primary_axes` and `axes_overlap`.
- `downstream.well_formed`: substantial, every spec carries a discriminator, and the primary axes do not overlap.
- `narrow_without_well_formed` and `broad_without_well_formed`.

The narrowing metrics report; they do not gate the run.

## Guardrails

- The trial must stop at the 7M capped-token budget, not overrun it.
- The run must stay `batched`; a change to the frozen sync mode invalidates the comparison.
- No skill-evolution pass, lesson write, or meta-write-skill read may appear.
- `auth_store` must never receive `view:full`.
- The assessment and diagnosis nodes must reach a terminal, or escalate with a named failure.
- A failed or blocked execution is deferred to the surfer; it is never assessed.

## Procedure

1. Apply the branch to the eval instance worktree and recreate the agent container.
2. Set the arm values in the instance `.env`.
3. Run `orchestrator next-target` for `white-jotter-1`.
4. Run `orchestrator trial` with `eval/setups/white-jotter-iteration-b.yaml`.
5. Poll `/projects/{project_id}/usage` and the project data directory every 2 minutes.
6. At a terminal execution, run the post-execution monitor to convergence.
7. Run `eval/measure_utm.py` on the trial directory.
8. Write the results document with `docs/experiments/EXPERIMENT-RESULTS-TEMPLATE.md`.

## Analysis plan

- Report the primary metric with its numerator and denominator.
- Report the arm A green share recomputed from the arm A threat files with the same classifier.
- Report the paired difference on the white-jotter target.
- Report every secondary and narrowing metric as a count or a ratio, with the denominator.
- Segment by unit and by threat class.
- Report the token tax per agent and per phase.
- State the single-trial limitation: no p-value and no confidence interval is meaningful for one run; the comparison is descriptive.

## Limitations

- One trial per arm on one target.
- The arm A run used the pre-impact threat schema; its green share must be recomputed from its stored `web_vulnerability_class`.
- The provider model and the relay are fixed; a provider behavior change is a confounder.
- The 110 risk threshold changes how many units are modelled, so a lower green share can be a composition effect, not a quality regression.

## Links

- `eval/setups/white-jotter-iteration-b.yaml`
- `eval/measure_utm.py`
- `eval/prompts/measure.md`
- `docs/experiments/white-jotter-batched-2026-10-24/TOKEN-USAGE-AND-CONTEXT-OCCUPANCY.md`
- `docs/design/threat-model-impact-elicitation-adr.md`
