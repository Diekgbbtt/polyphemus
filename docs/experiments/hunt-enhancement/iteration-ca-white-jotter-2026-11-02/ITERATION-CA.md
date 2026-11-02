# Iteration C.a - impacted chaining as a first-class reasoning concern

Status: **running** (started 2026-11-02T18:27:03Z).
This document is updated from the live monitor; the JSONL trail is authoritative.

## Question

Does the CVSS 4.0 refactor produce damage-bearing threats whose exploitability is
scored from the kill chain, whose impact chaining is explicit, and whose
high-severity directions reach a hunter, on the same white-jotter data layer,
without re-running recon or analysis?

This is a single-arm iteration, indexed C.a.
The comparison is exact counts against iteration D.
There is no p-value and no confidence interval; the report states that limitation.

## Hypothesis

The CVSS 4.0 refactor and the atomic impact write should:

- remove the victim-action penalty that scored the stored XSS at 6;
- remove the `ASSUMED` premise penalty from exploitability;
- score the XSS at `high` or `critical` and place it inside the global per-threat
  dispatch window;
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
| Local patch | `providers.py` thinking `max` for the four design roles, `high` for the two pod roles |
| `.env` pod watchdog | `HUNT_POD_SESSION_TIMEOUT_S=5400` (90 minutes) |
| `.env` skill evolver | `SKILL_EVOLUTION_ENABLED=0` |
| `.env` risk threshold | `HUNT_RISK_THRESHOLD=156.25` |
| Token budget | 7,000,000 |
| Trial clock | 24 hours; the token cap is the real bound |

The scope fence is the iteration D fence, stored verbatim on the project's
`settings.hunting.threat_model_scope`.

## Frozen policy

```
pipeline_sync            batched
pod_batch_size           2
promotion_risk_threshold 2.5
risk_threshold           156.25
token_budget             7000000
```

## Code identity and reload check

The agent container was rebuilt from `f020dafd` and recreated.
The reload checks passed:

- `HUNT_POD_SESSION_TIMEOUT_S=5400` in the container;
- `resolve_pod_session_timeout_s()` returns `5400.0`;
- the CVSS module is live: the stored-XSS vector
  `AV:N/AC:L/AT:N/PR:N/UI:P/VC:H/VI:H/VA:N` returns `9.3 critical`;
- the thinking patch is live: `hunting_threat_modeller` and `hunting_hunter`
  are `max`, the pod roles are `high`;
- the agent health endpoint returns 200.

## Monitoring

`monitor_iteration_ca.py` runs inside the agent container and polls every 120 s:

- `GET /projects/<id>/usage` for `capped_tokens` against the 7,000,000 cap;
- `GET /projects/<id>/hunting` for the run status and the risk total;
- every unit model under `hunting/threat_modeller/{produced,consumed,abandoned}`
  for the v5 assessment rows, the factors, the risk, the chains, and the fence terms.

Trail: `/tmp/monitor-ca.jsonl` inside the agent container.

## Live state (2026-11-02T18:33Z)

| Metric | Value |
|---|---|
| Run | `c84d2ada-e05c-42ba-bb12-8386119796f8` |
| State | running (modeller pass) |
| Intake | 0 of 27 (`ReverseProxy` first) |
| Risk | 0.0 / 156.25 |
| Capped tokens | 58,512 / 7,000,000 |
| Calls | 14 |
| Impact rows | 0 |
| Threats | 0 |
| Chains | 0 |
| Fence hits | 0 |

The run row confirms the frozen policy: `pipeline_sync=batched`,
`pod_batch_size=2`, `promotion_risk_threshold=2.5`, `risk_threshold=156.25`,
`threshold_basis=db`. The 27-unit intake order starts with `ReverseProxy`,
`Service:sign-in`, `RESTApi:api`, and `Service:library-catalog`.

## Results

Pending. The report will fill the primary and secondary metric tables from the
final store and the assessor's verdicts.

## Learnings

Pending.

## Recommendation

Pending.

## Next steps

Pending.
