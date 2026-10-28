# Iteration D - capability-first impact modeller on a copied data layer

Status: **running** (started 2026-10-27T21:53:51Z).
This document is updated from the live monitor; the JSONL trail is authoritative.

## Question

Does the capability-first impact model produce chained, damage-bearing threats on a real
target, and does the new scope fence keep the modeller off the three forbidden topics,
without re-running recon or analysis?

## Design

| Item | Value |
|---|---|
| Source project | `8e2e5dc7-a880-4451-aaa5-267cedd48264` (`eval-white-jotter-1`, iteration C) |
| New project | `fe446230-1f19-41c7-bf2e-b7b4b9c6f0f5` (`eval-white-jotter-1-iter-d`) |
| Data layer copied | L0/L1 graph, auth bucket, `authn` skill |
| Excluded | `hunting/`, `usage/` |
| Copied graph | 250 nodes, 317 relationships; `Observation` ids regenerated |
| Copied auth | `overview.yaml` 4,125 B, `credentials.yaml` 4,418 B |
| Copied skill | `authn` with `SKILL.md`, two reference scripts, one revision |
| Recon settings | copied from C (`target_seed t-1618c524.target`, operator KB, application overview) |
| Start phase | `hunting` (seeded project, `existing_project_id`) |
| Target | `webexploitbench/white-jotter`, already up, never touched by the harness |
| Eval sha | `5cadea78d4a4b8a88bf5284f29db14f29f1690ac` (merged trunk) |
| Hunting run | `aac5ecac-f119-4e26-9f21-fc259153ccf3` |

The instance worktree keeps its local `providers.py` thinking-level patch; the checkout from
`13ce0edb` to `5cadea78` does not touch that file.

## Frozen policy

```
pipeline_sync            batched
pod_batch_size           1
promotion_risk_threshold 4
risk_threshold           180
token_budget             7000000
```

## Scope fence (stored verbatim in `settings.hunting.threat_model_scope`)

```text
SCOPE FENCE (strictly binding).

Do not characterise any of the following as a trust boundary, and do not write a trust assumption about it:

1. Rate limiting or any other volumetric defence: its presence, absence, thresholds, or bypass.
2. The plain-text (non-TLS) nature of a communication channel, including any credential, session, or other sensitive value exposed by that channel.
3. Any vulnerability that requires a preliminary step outside the target's own attack surface to gain full client-side code control, including phishing, a malicious attachment, or a compromised browser or extension.

A direction that depends on one of these is out of scope. Do not write it as an assumption, a vulnerability, an impact row, or a threat. If it is worth recording, record it as an evidence note on an interface agreement, and leave it out of the threat model.
```

## Monitoring

`monitor_iteration_d.py` polls every 120 s:

- `GET /projects/<id>/usage` for `capped_tokens` against the 7,000,000 cap;
- `GET /projects/<id>/hunting/<rid>` for `status`, `risk_total`, `halt`, and the intake position;
- every unit model under `hunting/threat_modeller/{produced,consumed,abandoned}` for rows,
  dispositions, capabilities, chain pairs, promotion split, and fence terms.

Trail: `/opt/polymerhus-dev/eval/runs-iteration-d-20261027/monitor.jsonl`.

## Live state (2026-10-28T06:34Z)

| Metric | Value |
|---|---|
| State | running (hunt/pod queue) |
| Intake | 27 of 27 (exhausted) |
| Impact rows | 55 (27 threat, 28 precursor) |
| Capability rows | 55 of 55 |
| Green share | 27 / 55 = 49.1% |
| Threats | 27 |
| Chain pairs | 4 |
| Promoted / demoted | 19 / 8 |
| Risk | 150 / 180 (final; below the halt) |
| Capped tokens | 4,169,246 / 7,000,000 |
| Hunter calls | 141 |
| Pod-runner calls | 664 |
| Hunt specs / pod dirs | 5 / 21 |
| Fence hits | 0 |

The modeller phase exhausted the 27-unit intake at 01:38 without reaching the 180 halt. The
batched barrier lifted at that point: the surfer built the queue by model risk sum, the
hunters started, and the first unit's three hunts are terminal. Its pod block completed
with seventeen pod specs. The second unit's non-terminal hunts are in the pod phase: five
hunt specs and twenty-one pod specs, currently the mass-assignment role-write variants. The
remaining budget is 2.83M tokens.

### Run bound

The hunting run's budget is the 7,000,000 capped-token cap. The trial's own poll budget is
12 hours from 21:53:50Z, i.e. 09:53:50Z. The trial stops the whole project when that poll
deadline arrives, which would truncate the pod phase near 6M tokens. If the queue is still
live near 09:30Z, the operator path is: stop the hunting run through the API, let the trial
record the `stopped` phase, then resume the run and enforce the 7M cap with the monitor.
The run, not the trial's clock, is the experiment's bound.

### Unit shape

At the 21-unit snapshot, the first ten units (still in `produced/`) carried all 24 threats,
and the eleven units already moved to `consumed/` were capability-only:

| Unit | Rows | Threats | Precursors |
|---|---|---|---|
| ReverseProxy | 6 | 4 | 2 |
| Service:sign-in | 7 | 4 | 3 |
| RESTApi:api | 4 | 2 | 2 |
| Service:register | 3 | 2 | 1 |
| Service:library-catalog | 3 | 3 | 0 |
| AuthenticationMechanism | 2 | 2 | 0 |
| Service:article-management | 1 | 1 | 0 |
| Service:jotter-reading | 1 | 1 | 0 |
| AuthorizationSystem | 1 | 1 | 0 |
| IdentificationSystem | 1 | 1 | 0 |
| Service:navigation-menu | 2 | 1 | 1 |
| IntegrationSystem:cross-origin-policy | 2 | 1 | 1 |
| WebPresentation:article-management | 3 | 1 | 2 |
| Service:book-management | 2 | 0 | 2 |
| Service:media-asset-serving | 1 | 0 | 1 |
| Service:role-permission-administration | 1 | 0 | 1 |
| Service:user-administration | 1 | 0 | 1 |
| WebPresentation:jotter-reading | 2 | 0 | 2 |
| WebPresentation:library-catalog | 2 | 0 | 2 |
| WebPresentation:register | 1 | 0 | 1 |
| WebPresentation:sign-in | 2 | 0 | 2 |

This is the intended effect of the disposition. Iteration C filed 13 placeholders across 9
zero-threat units; D keeps 23 capabilities that reach no end damage as `precursor` rows, and
still fails to turn them into threats. Whether they are honest capabilities or under-mined
rows is exactly what the assessor's `impact_review.yaml` must judge.

The five later units (intake 22-26) add 2 threats and 3 precursors; the live totals above
include them. The full per-unit table is assembled from the run artifacts at the end.

Four cross-unit chains are real:

- `Service:sign-in` row `IA-26` requires `ReverseProxy::P-3` (the actuator dump capability)
  and closes to threat 3 with the pair `[ReverseProxy::P-3, ReverseProxy::P-3]`.
- `Service:library-catalog` row `IA-21` requires `ReverseProxy::P-2` (the back-office write
  capability) and closes to a browser-steering threat.
- `Service:article-management` row `IA-20` requires `RESTApi:api::P-1`.
- `Service:navigation-menu` row `IA-20` requires `ReverseProxy::P-1`.

The earlier single fence hit was `Service-library-catalog` trust agreement: "fourteen rows
hold a JSON-array-shaped string and six hold plain text". It describes the author field's
data shape, not a communication channel. The monitor's channel regex was narrowed to
`plain text channel|communication|transport|connection` and restarted, so this is not a
violation. A manual audit over every completed model found 0 matches.

### The batched barrier, and its lift

`pipeline_sync: batched` is a phase barrier, not an interleave (pipeline-sync ADR
section 2). The modeller pass runs the intake one unit at a time until the risk budget is
consumed or the intake is exhausted. Nothing downstream dispatches while the pass session
is live. The surfer then builds the queue by each unit's model risk sum, descending. The
modeller pass exhausted the intake at 01:38 (risk 150), the barrier lifted, and the hunter
phase started. Zero hunter calls before that point were the contract, not a stall.

## Open issue

The driver launched with an empty `--stack-fingerprint` because the manifest computation
returned empty at that moment. It computes now as
`84d14309e4c4c4ebd9706f890f7bf04455e1068efb2ab9dfff8cc4a4d707b6e0`.
If the trial record carries no fingerprint, backfill it before the assessment or the
verdicts will be refused as an identity mismatch. The hunting run itself is unaffected.
