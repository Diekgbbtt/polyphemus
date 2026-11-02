# Iteration C.a plan: impacted chaining as a first-class reasoning concern

*Status: ready to launch, 2026-11-02.*
*Baseline: iteration D (`docs/experiments/hunt-enhancement/iteration-d-white-jotter-2026-10-27/ITERATION-D.md`).*
*Spec: `docs/design/cvss4-risk-scoring-spec.md`.*
*Code identity: `feat/cvss4-risk-scoring` at `f020dafd12f3f8f525fad2496c64141b6e4f8fc8`.*

## Question

After the CVSS 4.0 refactor, does the threat modeller produce damage-bearing threats whose exploitability is scored from the kill chain, whose impact chaining is explicit, and whose high-severity directions reach a hunter, on the same white-jotter data layer, without re-running recon or analysis?

This is a single-arm iteration, indexed C.a.
It is not an A/B test: the comparison is exact counts against iteration D, and the report states that limitation.

## Hypothesis

The CVSS 4.0 refactor and the atomic impact write should:

- remove the victim-action penalty that scored the stored XSS at 6;
- remove the `ASSUMED` premise penalty from exploitability;
- score the XSS at `high` or `critical` and place it inside the global per-threat dispatch window;
- make the capability chain explicit on more GT-relevant threats;
- reduce pod watchdog timeouts through the 90-minute configurable boundary.

## Design

| Item | Value |
|---|---|
| Source project | `8e2e5dc7-a880-4451-aaa5-267cedd48264` (`eval-white-jotter-1`, iteration C) |
| New project | `cbd28a7d-30cb-498b-8e7a-eaa9bc8f37c8` (`eval-white-jotter-1-iter-ca`) |
| Data layer copied | L0/L1 graph, auth bucket, `authn` skill |
| Excluded | `hunting/`, `usage/` |
| Copied graph | 250 nodes, 317 relationships |
| Copied auth | `overview.yaml` 4,125 B, `credentials.yaml` 4,418 B |
| Copied skill | `authn` |
| Start phase | `hunting` (seeded project, `existing_project_id`) |
| Target | `webexploitbench/white-jotter`, `t-1618c524.target`, health `composite ready` |
| Code identity | `f020dafd12f3f8f525fad2496c64141b6e4f8fc8` on `eval-ca` |
| Local patches | `providers.py` thinking `max/high`; no `surfer.py` patch (the watchdog is the `.env` variable) |
| `.env` pod watchdog | `HUNT_POD_SESSION_TIMEOUT_S=5400` (90 minutes) |
| `.env` skill evolver | `SKILL_EVOLUTION_ENABLED=0` |
| `.env` risk threshold | `HUNT_RISK_THRESHOLD=156.25` (the project setting also carries 156.25 and wins) |
| Token budget | 7,000,000 |
| Trial clock | 24 hours; the token cap is the real bound |

The scope fence is the iteration D fence, stored verbatim on the project's
`settings.hunting.threat_model_scope`.

## Frozen hunting policy

```
pipeline_sync            batched
pod_batch_size           2
promotion_risk_threshold 2.5
risk_threshold           156.25
token_budget             7000000
```

Both thresholds are CVSS 4.0 points on the 0..10 scale.
The promotion floor is inclusive.

## Metrics

The metrics are derived from the defect signals in iteration D, not invented.

### Primary

**GT impact-chain coverage**: the number of ground-truth vulnerabilities whose threat row is produced, carries a non-empty capability path or enabling chain, and reaches a hunter, out of 7.

Iteration D baseline: 4 GT threats produced (002, 003, 005, 007); 3 dispatched (002, 005, 007); 003 produced but not dispatched.
Target C.a: at least 5 of 7, with 003 dispatched.

### Secondary

| Metric | Signal it measures | D baseline | C.a target |
|---|---|---|---|
| `gt_produced` | impact binding and fault coverage | 4 / 7 | >= 5 / 7 |
| `gt_dispatched` | global per-threat queue | 3 / 7 | >= 5 / 7 |
| `gt_identified` | assessment verdicts | 2 identified, 2 partial | >= 3 identified |
| `xss_risk` | victim-action penalty | 6.0 (medium) | >= 7.0 (high) |
| `xss_rank` | unit-sum crowding | outside the 12-hunt window | inside the dispatched window |
| `xss_dispatched` | promotion + queue | no | yes |
| `assumed_penalty_count` | confidence feeding exploitability | 2 explicit demotions | 0 |
| `victim_action_penalty_count` | passive UI misread as active | 1 (stored XSS) | 0 |
| `impact_chain_rate` | chain-first impact reasoning | compute from D | >= D + 10 points |
| `cross_unit_chain_count` | cross-unit capability chaining | 4 | >= 4 |
| `chain_depth` | multi-step chaining | 1-2 | report distribution |
| `score_saturation` | CVSS base-score spread | 15 / 27 >= 9.2 (reconstructed) | report actual |
| `assessment_coverage` | every vulnerability assessed | 100% of 7? | 100% |
| `factor_completeness` | 8 of 8 factors per row | n/a (v4) | 100% |
| `tool_rejections` | `assess_impact` contract adherence | n/a | report count |
| `fence_hits` | scope discipline | 0 | 0 |

### Guardrails

| Metric | Threshold |
|---|---|
| Tokens | <= 7,000,000 |
| Pod watchdog timeouts | <= 8 (D: 17) |
| Missing pod exports | <= 5 (D: 5) |
| Provider 401/400 recorded as domain verdicts | 0 |
| Trial terminal | `complete` or `stopped` at the cap |

## Stop policy

The 7M capped token total is the bound.
The trial clock is 24 hours.
No stop/resume takeover unless the clock hits.
If the clock hits, stop through the API and resume once, as in D.

## Execution

1. Deploy `f020dafd` to the instance, preserve the `providers.py` patch, set the `.env`, rebuild the agent, verify the resolver and the agent health. Done.
2. Bring up white-jotter. Done.
3. Create the project and copy the data layer. Done.
4. Set the hunting config. Done.
5. Write the setup and the driver.
6. Start the trial.
7. Poll every 120 seconds: `/usage`, run status, unit models, assessment rows, chains, fence terms.
8. Update `ITERATION-CA.md` at every poll.
9. At terminal: run the eval monitor, close-verify, store materialize, measure.
10. Write the results and the recommendation.

## Risks

- The triager model-identity and provider-401 failures are not fixed on this branch; they can still lose pod verdicts. The report isolates them from the scoring result.
- The CVSS base score saturates; the report distinguishes severity from rank.
- The per-threat queue changes throughput; the report reports the dispatch frontier and the wall-clock.
- The 90-minute watchdog is a reliability intervention, not a scoring one; its effect is reported separately.

## Status

| Step | Status |
|---|---|
| Deploy `f020dafd` | done |
| Target up | done |
| Project copy | done |
| Hunting config | done |
| Setup and driver | in progress |
| Trial | pending |
| Monitor and assessment | pending |
| Measurement | pending |
| Report | pending |
