# Iteration C.a - impacted chaining as a first-class reasoning concern

Status: **complete** (started 2026-11-02T18:27:03Z, stopped at the 7M token cap
2026-11-03T14:39:24Z).
This document records the final measured results; the JSONL trail and the trial
record are authoritative.
The official records are in `artifacts-ca/`: `verdicts.yaml`, `diagnoses.yaml`,
`impact_review.yaml`, `metrics.yaml`, `measurements.yaml`, and
`measurements.md`.

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

## Terminal state (2026-11-03T14:39Z)

| Metric | Value |
|---|---|
| Run | `c84d2ada-e05c-42ba-bb12-8386119796f8` |
| State | `stopped` at the 7M cap |
| Intake | 27 of 27 (exhausted) |
| Risk | 106.9 / 156.25 over all 14 threat rows; the metric reports 100.0 because it drops the register threat-1 (6.9) |
| Capped tokens | 7,003,040 / 7,000,000 (overshoot 3,040) |
| Calls | 2,510 |
| Units | 27 (3 produced, 11 consumed, 13 abandoned) |
| Impact rows | 28 raw (14 threat, 14 precursor); 27 reviewed (14 threat, 13 precursor) |
| Threats | 14 |
| Chains | 3 rows, 2 cross-unit refs |
| Degraded | 13 |
| Hunt specs | 10 |
| Pods | 37 |
| Terminal exports | 15 `symptom-confirmed`, 13 `pod-watchdog-timeout`, 5 `no-symptom-evidence`, 2 `technical-infeasibility`, 2 `node-timeout` |
| Audited confirmations | 15 (1 weak attestation) |
| Fence hits | 0 |

Monitoring note: at about 06:20 the host `/tmp` tmpfs (7.7G) filled and both
`docker exec` and `docker cp` failed.
Freeing 300M of stale temp files restored both.
The app data is on the 28G root filesystem and was not affected; the run kept
running.
The live feed was restarted at 06:30.

## Target substitution

The white-jotter container started at `2026-11-02T18:16:05Z` and stayed up on
port 46271 for the whole run.
The shared synthetic hostname `t-1618c524.target` did not stay pointed at it.

The modeller's notes record the first substitution at `21:19Z` (SIYUCMS,
PHP/7.3.33), with re-confirmations at 21:24, 21:29, and 21:43.
The GT-007 pod export records PrestaShop 401 at `07:25Z`, a brief white-jotter
window at `07:47Z`, 502 at `08:01Z`, and PrestaShop 401 through `08:49Z`.
The front conf was rewritten back to white-jotter at `13:55:40Z`.

Consequences:

- `Service:media-asset-serving` was authored at `21:26Z` against SIYUCMS and
  never probed `/api/file/` (GT-006);
- the GT-007 pod saw the administrator menu, then polled a substituted host
  until the watchdog;
- the account-recovery spec that would submit `admin/123` was blocked as
  `technical-infeasibility` (GT-001);
- the logging-sink probe could not run after `21:19Z` (GT-004);
- nine of the 13 abandoned units and most of the 13 watchdog timeouts are
  downstream.

The pipeline has no target-identity guard.
The white-jotter container never moved; the hostname did.

The modeller pass exhausted the 27-unit intake without reaching the risk halt.
The `batched` barrier has lifted and the first hunt is `Service:user-administration__threat-1`,
the 9.9 credential-recovery threat.
Its three `account-recovery` pods are running.
The stored-XSS hunt is rank 2 and waits for the first hunt's pod set.

## First hunt: `Service:user-administration` (rank 1, 9.9)

The threat is the credential-recovery direction: a fixed, publicly displayed
default with no proof of ownership.

| Pod | Verdict | Reason |
|---|---|---|
| `semicolon-matrix__anonymous__second-account` | successful | `symptom-confirmed` |
| `semicolon-matrix__anonymous__administrator` | unsuccessful | `technical-infeasibility` |
| `canonical__self-registered-session__administrator` | unsuccessful | `pod-watchdog-timeout` |

The confirmed interpretation is:

> anonymous name-keyed password reset writing published default `123`, reached
> past the `/api/admin/**` gate via the semicolon-matrix path

This is a real critical find.
The trail confirms the reset, not the reset's own answer.
It is adjacent to GT-001: the GT expects the seeded `admin/123` login at
`/api/login`; this path resets the administrator credential to the published
default through `/api/admin/user/password`.
The assessor will decide whether it satisfies GT-001 or is a novel adjacent
confirmation.
The top-ranked 9.9 score is justified by the confirmed symptom.

The third pod hit the 90-minute watchdog exactly, so the configured boundary
was honoured.
The first hunt's pod yield is 1 confirmed / 3 (33%); one direction was
infeasible and one timed out.

## Second hunt: stored XSS dispatched (rank 2, 9.3)

The stored-XSS hunt is `Service:article-management__threat-1`.
It is terminal at the hunter and has three ratified specs:

- `xss-stored__anonymous-create__event-handler-element`
- `xss-stored__anonymous-create__srcdoc-frame`
- `xss-stored__id-addressed-overwrite__event-handler-element`

The three pods are running.
This is the D failure corrected: in D the stored XSS was risk 6 and never
received a hunt; in C.a it is rank 2, dispatched, and under test.

One pod has already confirmed:

| Pod | Verdict | Reason |
|---|---|---|
| `xss-stored__anonymous-create__srcdoc-frame` | successful | `symptom-confirmed` |
| `xss-stored__anonymous-create__event-handler-element` | successful | `symptom-confirmed` |

The first interpretation states:

> a caller-authored rendered-body string is persisted and reassigned to an
> innerHTML sink on the public reader route, so anonymous write becomes
> same-origin script execution on read

The second is a direct DOM confirmation:

> cookie-less session loaded `/jotter/article?id=23`; `.markdown-body` innerHTML
> contained the event-handler payload

The classification is `xss-stored`, and the evidence is the reach, write,
render, and execution chain.
This is the primary C.a result: the stored XSS that D scored 6.0 and never
dispatched is now a 9.3 critical, rank 2, confirmed exploit on two independent
variants.

The third XSS pod hit the 90-minute watchdog.
The XSS hunt closed at 2 confirmed / 3 pods, and the next hunt (the rank-3
`ReverseProxy` BFLA) is due.
The 90-minute boundary was honoured, but it did not eliminate the timeout: 2 of
6 pods have timed out so far, against D's 17 of 47 at the old 60-minute bound.

## Third hunt: `ReverseProxy` BFLA (rank 3, 9.2)

The `ReverseProxy__threat-1` hunt has produced its spec set; two BFLA pods are
running.

The first pod (`broken-function-level-authorization__vhost-host-header__anonymous`)
exported `no-symptom-evidence`, but the triager degraded:

```
triager degraded: 'dict' object has no attribute 'model_dump'
```

The verdict is not a clean domain result.
It is a triager output-handling defect: a dict reaches the interpretation
serializer where a typed model is expected, `model_dump` fails, and the pod
falls back to `no-symptom-evidence`.

The precise path is the triager's `stateful_turn(..., schema=TriagerDecision)`
return.
The caller assumes a `TriagerDecision` and calls `result.model_dump()`.
When the structured turn yields a dict, `model_dump` is missing.
`triage._normalize_decision` already handles both shapes, but the triager path
bypasses it.
The fix is to normalise the result before serialisation, not to degrade to a
domain verdict.

The second BFLA pod (`canonical-path__self-registered-session`) exported
`no-symptom-evidence` with `classification: runner-divergence`.
Its note says the payload vector specified the canonical path
`/admin/Admin/index.html` with the registered `PHPSESSID` and "no path
mutation", but the final probe instead deviated from that specified variant.

Neither BFLA pod is a clean domain result:

- one triager-degraded with `'dict' object has no attribute 'model_dump'`;
- one runner-diverged from the specified canonical-path variant.

The BFLA model row is still produced and scored at 9.2; the pod confirmation is
inconclusive, not negative.
The `ReverseProxy__threat-2` hunt is the next spec set.
This is the pod/hunter workstream the user queued, now visible as two live
defects; neither should be counted as a model or scoring miss.

## Verdict integrity: the BFLA export

The `threat-2` hunt's pod
`broken-function-level-authorization__authc-filter__menu-read__read` exported
`successful` / `symptom-confirmed` / `clean: true`.
Its export carries two interpretations:

- `v0`: `runner-failure` - the first attempt timed out after 6 s with 0 bytes
  on both proxies;
- `v1`: an unclassified note - inside a 04:12-04:13 window, `GET /api/menu`
  returned 302 with `Set-Cookie JSESSIONID` and
  `Location /nowhere;jsessionid`, while `GET /api/;/menu` returned 200
  `application/json` with no cookie and no `Location`.

The assessor accepted `v1` at confidence 0.82 and the verdict is `identified`.
The confirmation is genuine but weak: it rests on one ~61 s window, and a later
re-poll found no window.
The export is still defective, because the triager labelled the pod
`clean: true` while one interpretation is a runner failure and the confirming
variant carries no classification.
The defect is in the export contract, not in the verdict.

An earlier interim note in this report called the pod a false positive.
The full export shows the later window; this section corrects that.
The audited count is 15 of 15 terminal exports, with this one weak attestation.

The pod/triager verdict mapping is still broken in both directions:

- a triager `model_dump` error degraded three pods to `no-symptom-evidence`;
- a runner-failure variant sits inside an export marked `clean: true`.

The final C.a counts use the audited interpretations, not the raw verdicts.
This remains the strongest evidence that the pod/triager workstream is the
bottleneck, not the threat model or the scoring.

The `threat-2` hunt's remaining five pods all hit the 90-minute watchdog.
The hunt closed at one raw confirmation (the weak attestation above) and five
timeouts.
The next hunt (SQLi / mass assignment, GT-005/007) is due.

## Fifth hunt: `RESTApi` SQL injection (rank 5, 9.2)

The `RESTApi-api__threat-1` hunt has five specs:

- `sql-injection__boolean-row-delta__account-roles`
- `sql-injection__union-rendered__account-roles`
- `sql-injection__union-rendered__metadata-dialect`
- `sql-injection__union-rendered__unpublished-content`
- one further union/boolean variant

The pods are running.
This is GT-005, which D already identified.

One pod has confirmed:

| Pod | Verdict | Reason |
|---|---|---|
| `sql-injection__union-rendered__metadata-dialect` | successful | `symptom-confirmed`, clean |

Its interpretation states:

> Injected UNION parsed: `GET /api/search?keywords=x' UNION SELECT
> 999,GROUP_CONCAT(DISTINCT ENGINE),... FROM information_schema.ENGINES #`
> returned status 200 with `result[0].id=999` and
> `result[0].cover="Aria,CSV,InnoDB,MEMORY,..."`

The engine-specific metadata is rendered in select position 2.
This is a clean SQL injection confirmation and the audited count is now 4.

The remaining SQLi pods are mixed: four exported unsuccessful (two
`pod-watchdog-timeout`, one `no-symptom-evidence`, one `node-timeout`).
The `node-timeout` is the pod graph's node-level harness reason, not the
90-minute session watchdog.
The SQLi hunt closed at 1 confirmed / 5 pods, and the mass-assignment hunt
(GT-007) is next.

## Sixth hunt: `RESTApi` mass assignment (rank 6, 9.2)

The `RESTApi-api__threat-2` hunt has four pods.
This is GT-007, which D graded partial because a confirming mass-assignment pod
was exported `unsuccessful`.
The C.a pods are running.
The question for this hunt is whether the triager/export integrity now lets a
confirming role-association write survive to the verdict.
This is the last GT-relevant hunt in the current queue.

All four pods failed: three `pod-watchdog-timeout` and one `node-timeout`.
The mass-assignment hunt closed with no confirmation.
GT-007 remains unconfirmed in C.a for the same reason as D: the pod layer, not
the model.
The article-IDOR hunt (rank 7) is next.

## Seventh hunt: article IDOR (rank 7, 9.2)

The `Service-article-management__threat-2` hunt has three pods.

One pod confirmed:

| Pod | Verdict | Reason |
|---|---|---|
| `idor__create__absent__no-identifier` | successful | `symptom-confirmed`, clean |

Its interpretation states:

> Anonymous `GET /api/article/29` returns HTTP 200 with `id=29`,
> `articleTitle RUNMARK-...`, `articleContentHtml "<p>IDORPROOF-...</p>"` - the
> caller's marker, not an echo. The paged read `/api/article/10/1` now reports
> `totalElements=12` (baseline 11), so the write is durable.

This is a clean, novel damage-bearing IDOR.
It is not a GT vulnerability; it is a confirmed impact-chain result from the
article unit.
The audited confirmation count is now 5.
The remaining two article-IDOR pods exported unsuccessful: one
`technical-infeasibility` and one 90-minute `pod-watchdog-timeout`.
The article-IDOR hunt closed at 1 confirmed / 3 pods.

The eighth hunt (`ReverseProxy` source maps, rank 8) has its specs; the pods are
starting.
The remaining hunts are non-GT or adjacent; the GT-relevant set is complete.

## Eighth hunt: source maps (rank 8, 6.9)

The `ReverseProxy__threat-3` hunt has four pods.
Two confirmed:

| Pod | Verdict | Reason |
|---|---|---|
| `stored-artifact-disclosure__css-bundle__none` | successful | `symptom-confirmed`, clean |
| `stored-artifact-disclosure__vendor-bundle__none` | successful | `symptom-confirmed`, clean |

The css pod found a genuine `css.map` with populated `sourcesContent`
(1,843 classes across 6,547 rules).
The vendor pod parsed `vendor.js.map` and recovered `vue 2.6.10`,
`vuex 3.1.0`, and `vue-router 3.0.2` from `node_modules` sources.
Both are novel build-artifact disclosures, not GT vulnerabilities.
The audited confirmation count is now 9.

All four source-map pods confirmed: the css and vendor bundles above, plus two
further variants.
The ninth hunt (`Service:sign-in` enumeration, rank 9) has its specs; the pods
are starting.
This is the last hunt likely to fit under the 7M cap.

## Ninth hunt: sign-in enumeration (rank 9, 6.9)

The `Service-sign-in__threat-1` hunt has four pods.
Three confirmed:

| Pod | Verdict | Reason |
|---|---|---|
| `username-enumeration-oracle__exact-spelling__pairwise` | successful | `symptom-confirmed`, clean |
| `username-enumeration-oracle__exact-spelling__list-walk` | successful | `symptom-confirmed`, clean |
| `username-enumeration-oracle__case-variant__pairwise` | successful | `symptom-confirmed`, clean |

The evidence is a message delta at `POST /api/login`:

- `admin` with a wrong password returns 51 B `{"message":"密码错误"}`;
- `admin1` returns 54 B `{"message":"账号不存在"}`;
- the 29-name walk and the case variants reproduce the delta.

The fourth pod found no symptom.
This is a clean enumeration oracle, adjacent to the auth GT but not the
CWE-1392 default credential.
The audited confirmation count is now 12.

## Tenth hunt: register concurrent duplication (rank 10, 6.9)

The `Service-register__threat-1` hunt has three pods.

One pod confirmed:

| Pod | Verdict | Reason |
|---|---|---|
| `concurrent-duplication__burst-escalation__duplicate-rows-and-contradictory-lookups__anonymous-only` | successful | `symptom-confirmed`, clean |

The interpretation states:

> anonymous concurrent `POST /api/register` on one username creates duplicate
> rows because uniqueness is only an application-level check; ranks 2/4/8
> returned 2/4/8 successes, and rank 16 gave 10 successes + 6 nulls.

This is a clean, novel non-atomic-uniqueness confirmation.
The audited confirmation count is now 13.
The other two pods are running; the run is about 0.22M from the cap.

## Usage split (final)

| Role | Capped tokens | Share | Calls | Total context | Generated (reasoning / visible) |
|---|---:|---:|---:|---:|---|
| Pod runner | 3,351,362 | 47.9% | 1,614 | 69,285,570 | 670,758 / 412,242 |
| Modeller | 1,419,105 | 20.3% | 522 | 118,695,521 | 353,135 / 420,523 |
| Hunter | 1,282,776 | 18.3% | 291 | 20,004,696 | 206,124 / 145,590 |
| Pod triager | 949,797 | 13.6% | 83 | 1,487,141 | 70,705 / 27,882 |
| **Total** | **7,003,040** | **100%** | **2,510** | **209,472,928** | **1,300,722 / 1,006,237** |

The pod runner is 47.9% of the cap, up from 43.5% in D.
The triager is 13.6%, up from 7.9%.
The modeller is 20.3%, down from 31.6%, because it abandoned 13 units and
produced half the rows.
The hunter is 18.3%, nearly unchanged.

The capped cost per pod rose from 64.9K in D to 90.6K in C.a.
The capped cost per impact row rose from 40.2K in D to 50.7K in C.a.
The 90-minute watchdog and the longer pod runs are the likely driver; the
triager crash path is a second.

## The stored-XSS unit: `Service:article-management`

The article unit completed with 2 assessment rows, both threats, both critical.

| Row | Disposition | Risk | Chain | Class |
|---|---|---:|---|---|
| IA-1 | threat | 9.3 | `ReverseProxy::P-4` | stored XSS through an unsanitised rendered article body |
| IA-2 | threat | 9.2 | `ReverseProxy::P-4` | unauthenticated content IDOR (caller-supplied identifier, no ownership binding) |

The unit risk profile is `18.5` with 2 critical.

The stored-XSS vector is
`CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:P/VC:H/VI:H/VA:N/SC:H/SI:H/SA:N`.
Its factors are `AV:N`, `AC:L`, `AT:N`, `PR:N`, `UI:P`, `VC:H`, `VI:H`, `VA:N`.
This is the direct correction of the D failure:

- D scored it `6.0` medium and did not dispatch it.
- C.a scores it `9.3` critical with `UI:P` and no assumed-premise penalty.
- It carries a real cross-unit capability chain (`ReverseProxy::P-4`).
- It should sit at the top of the global per-threat dispatch queue.

The second threat is the article IDOR at `9.2`, also chained to the same
ReverseProxy capability.

## Deterministic GT extraction (full modeller, 27 models)

This is the deterministic row/threat match, not the assessor's verdict.
The final verdicts remain authoritative.

| GT | Produced | Risk | Unit | Chain | Queue rank |
|---|---|---:|---|---|---:|
| 001 default credential | no | 0.0 | - | no | - |
| 002 BFLA | yes | 9.2 | `ReverseProxy` | no | 3 |
| 003 stored XSS | yes | 9.3 | `Service:article-management` | yes | 2 |
| 004 JNDI | no | 0.0 | - | no | - |
| 005 SQL injection | yes | 9.2 | `RESTApi:api` | no | 5 |
| 006 path traversal | no | 0.0 | - | no | - |
| 007 mass assignment | yes | 9.2 | `RESTApi:api` | no | 6 |

The extractor counts 4 of 7 GT directions produced, the same raw coverage as D.
The difference is the XSS: rank 2, 9.3, chained.
GT-001, GT-004, and GT-006 are not produced by the deterministic matcher.
The assessor grades GT-001 partial through the sign-in enumeration at the
correct locus; the default-credential class is not bound.
GT-004 is a fault-class miss on a unit that was modelled.
GT-006 is a workflow miss: `Service:media-asset-serving` was abandoned before
it could be assessed.

## Workflow regression: abandoned units

The final pass abandoned 13 of 27 units.
All 13 wrote `COMPLETED` with `validation.valid: false`.

| Cause | Units |
|---|---:|
| Missing `assumptions`, `vulnerabilities`, and `impact_assessment` | 9 |
| The same three plus `technical_sharpening.interface_agreements` | 2 |
| The same three plus referential errors | 1 |
| Referential errors only, one impact row present | 1 |

Twelve of 13 wrote no vulnerability at all.
The trajectory shows the workflow cause: the model writes `COMPLETED` directly
from `PRIOR_ART`, skipping `IMPACT_ASSESSED`.
The completion checker then reported the missing sections, and the pass
archived the unit as degraded.

Nine of the 13 abandonments happened after the `21:19Z` substitution.
The substitution is the environmental cause; the missing vulnerability section
is the workflow cause that turned the closure into an abandoned unit.

The first fix at `8d5c9f83` refused a `COMPLETED` write that left a non-dropped
vulnerability without an assessment row.
That guard is vacuous for a model with no vulnerabilities, so it would not have
caught these twelve units.
The follow-up fix at `b312032a` refuses the empty vulnerability section at the
`COMPLETED` write, so the model re-enters with the missing field named.

The abandoned set includes `Service:media-asset-serving`, which owns GT-006's
cover-serving handler.
It was created at `21:26Z`, seven minutes after the substitution, never probed
`/api/file/`, and closed zero-threat.
The abandonment is the mechanism; the substitution and the missing route probe
are the causes.
The other 006-relevant model, `Service:book-management`, is also abandoned, and
`Service:library-catalog` produced no traversal row.

The one referential-only abandonment,
`WebPresentation:article-management::console-pages`, kept one impact row but
referenced stale interface-agreement IDs.
The store commits such a model by design and the pass archives it.
That behaviour is unchanged and is a separate follow-up.

## Risk-budget watch

The run closed at `106.9` of `156.25`, below the halt.
The risk budget never bound; the 13 abandonments did.

GT-006 is the coverage failure.
The cover-serving handler is `Service:media-asset-serving`, the 19th intake
unit.
It was authored after the `21:19Z` substitution, never probed `/api/file/`, and
closed zero-threat.
That is a substitution-and-coverage miss, not a scoring miss.

## First completed unit: `ReverseProxy`

The first unit completed the seven gates in 6m50s (18:38:31 to 18:45:21).
It carries 5 assessment rows: 3 threats and 2 precursors.

| Row | Disposition | Risk | Chain | Class |
|---|---|---:|---|---|
| IA-1 | threat | 9.2 | none | path-canonicalisation authorization bypass |
| IA-2 | threat | 9.2 | `P-1` | path-canonicalisation authorization bypass |
| IA-5 | threat | 6.9 | none | build-artifact disclosure (source maps) |
| IA-3 | precursor | 0.0 | none | no end damage |
| IA-4 | precursor | 0.0 | none | no end damage |

The unit risk profile is `25.3` with 2 critical and 1 medium.
The chained row `IA-2` closes to `threat-2` with the pair `[P-1, P-1]`, so the
capability path and the enabling precursors agree.

The early signal is positive: the CVSS scores are high, the two precursor rows
are 0.0, the chain is explicit, and the first unit has no fence hit.

## Second unit: `Service:sign-in`

The sign-in unit completed at 18:56:48 with 5 rows: 2 threats and 3 precursors.

| Row | Disposition | Risk | Chain | Class |
|---|---|---:|---|---|
| IA-1 | threat | 6.9 | none | account-existence and account-state oracle (user enumeration) |
| IA-5 | threat | 5.3 | none | session authority not revoked on credential or enabled-state change |
| IA-2 | precursor | 0.0 | none | fixation precondition |
| IA-3 | precursor | 0.0 | none | caller-held value decrypts |
| IA-4 | precursor | 0.0 | none | credential-body divergence needs a second reader |

The unit risk profile is `12.2` with 2 medium.
GT-001 (the default administrator credential) is still absent: the unit has no
CWE-1392 row, and the seeded `admin` credential is not bound to the sign-in
service. That is the D diagnosis surviving the CVSS refactor, as expected: the
C.a arm did not add a default-credential fault or a seed binding.

## Third unit: `RESTApi:api`

The API unit completed with 2 assessment rows, both threats, both critical.

| Row | Disposition | Risk | Chain | Class |
|---|---|---:|---|---|
| IA-1 | threat | 9.2 | none | unauthenticated SQL injection through a concatenated search parameter |
| IA-2 | threat | 9.2 | none | mass assignment of a persisted role association on self-registration |

The unit risk profile is `18.4` with 2 critical.
The two directions match GT-005 and GT-007.
Both are direct impacts with no capability path, so the chain metric does not
move for this unit; the correct question for them is dispatch, not chaining.

## Fourth unit: `Service:library-catalog`

The catalogue unit completed with 2 assessment rows, both precursors, and no
threat.

| Row | Disposition | Risk | Chain | Capability |
|---|---|---:|---|---|
| IA-1 | precursor | 0.0 | none | caller-chosen catalogue row set |
| IA-2 | precursor | 0.0 | none | browser steering to a writable host |

The unit risk profile is `0.0`, so it produces no threat file and is never
dispatched.
The model's closure is that everything the catalogue can reach is already
public by its own contract, and the redirect channel reaches no end damage.

GT-006 is still absent. The arbitrary file read at `/api/file/cover.png` is not
produced here, and the earlier `ReverseProxy` unit produced no traversal row
either. The D failure bound GT-006 to the proxy; C.a has not yet bound it to the
cover-serving handler.

## Results

The run is terminal `stopped` at the 7M token cap.

### Primary metric

| Metric | D | C.a | Delta |
|---|---:|---:|---:|
| GT identified | 2 / 7 | 3 / 7 | +1 |
| GT partial | 2 / 7 | 2 / 7 | 0 |
| GT missed | 3 / 7 | 2 / 7 | -1 |
| Identification rate | 0.286 | 0.429 | +0.143 |
| Partial-or-identified rate | 0.571 | 0.714 | +0.143 |
| Full core | 2 / 7 | 2 / 7 | 0 |

The added identification is GT-003, the stored XSS.
D scored it 6.0 and never dispatched it.
C.a scored it 9.3, ranked it 2, and confirmed it on two pod variants.
GT-002 and GT-005 stay identified.
GT-001 and GT-007 stay partial.
GT-004 and GT-006 stay missed.

| GT | Verdict | Confidence | Matched unit | Hunt rank |
|---|---|---:|---|---:|
| 001 | partial | 0.40 | `Service:sign-in` | 9 |
| 002 | identified | 0.82 | `ReverseProxy` | 3 |
| 003 | identified | 0.95 | `Service:article-management` | 2 |
| 004 | missed | 0.90 | - | - |
| 005 | identified | 0.96 | `RESTApi:api` | 5 |
| 006 | missed | 0.88 | - | - |
| 007 | partial | 0.55 | `RESTApi:api` | 6 |

### Hypothesis check

- **Victim-action penalty removed.** The XSS vector carries `UI:P` and scores
  9.3. No row applies a victim-action discount (`victim_action_penalty_count:
  0`).
- **Assumed-premise penalty removed.** No row discounts an assumed premise
  (`assumed_penalty_count: 0`).
- **XSS inside the dispatch window.** Rank 2 of 14 threats; dispatched and
  confirmed twice.
- **Explicit capability chaining.** 3 of 28 rows carry a non-empty capability
  path (10.7%), with 2 cross-unit references. D counted 4 chain pairs over 55
  rows. The C.a row rate is lower because 13 units were abandoned.
- **90-minute watchdog.** 13 of 37 terminal pods timed out (35.1%), against D's
  17 of 47 (36.2%) at 60 minutes. Seven of the 13 ended on the substituted
  host; six ended on white-jotter. The longer bound did not reduce the timeout
  share.

### Impact review

The assessor reviewed 14 units: 13 in scope, 1 out.
It labelled all 27 reviewed rows `mining: sufficient`.
The reviewed metric is 14 green and 1 red (`green_share: 0.933`); the red is
the out-of-scope `IntegrationSystem:cross-origin-policy` row, which carries risk
0 because its capability requires serving content on the developer's
`localhost:8080` before the victim's browser acts.
No reviewed row was under-mined.

The metric's `risk_total` is 100.0 with 6 medium and 7 critical.
That is a measurement defect, not a scope effect: the 14 threat rows sum to
106.9 with 7 medium and 7 critical.
The missing 6.9 is `consumed/Service-register/threat-1.yaml` (concurrent
duplication); its parent model lives in `produced/`, so the metric cannot stamp
its schema and drops it.

### Pod results

| Metric | Value |
|---|---:|
| Terminal pods | 37 |
| Raw `symptom-confirmed` | 15 |
| Audited confirmations | 15 |
| Watchdog timeouts | 13 |
| No-symptom evidence | 5 |
| Technical infeasibility | 2 |
| Node timeout | 2 |

The 15 confirmations resolve to 4 GT-related pods:
GT-003 on two variants, GT-005 on one, and GT-002 on one.
The other 11 are novel or adjacent findings.
The GT-007 raw trail is a fifth GT observation, but its export is
`pod-watchdog-timeout`.
The official `metrics.yaml` reports 6 GT-related pod confirmations and 10
non-GT confirmations.
Its per-vuln matcher attributes an XSS pod to GT-004, which has no JNDI pod;
treat `pod_confirmed` as a candidate-level heuristic, not a terminal
confirmation.
The GT-002 confirmation is a weak attestation: one ~61 s window and an
unclassified `v1` note.
The GT-007 symptom is in the mass-assignment experiment log but its pod
timed out, so the verdict is partial.

The pod rates are confounded by the substitution: 9 of the 13 abandonments and
all 13 watchdog terminals happened after `21:19Z`.
The 35.1% timeout share is not a clean C.a-versus-D comparison.

The 13 watchdog terminals split into two sets.
Seven ended on the substituted host: PrestaShop 401, SIYUCMS `AdminIndex`,
`CLOSED`, or `NOWINDOW`.
Six ended on white-jotter: four BFLA edge-prefix variants, the IDOR overwrite,
and the XSS id-addressed overwrite, with 31-81 tool calls each.
None of the 13 was stopped by the 7M token cap.
Their terminals are at 01:39Z, 04:58Z, and 10:41Z; the cap fired at 14:39Z.
At 10:38Z the run had spent 5,638,969 of 7,000,000 capped tokens.
The export reason is the per-pod 5,400 s watchdog, not a token-budget stop.

### Workflow adherence

The measurement's weighted score is 0.33, with 5 high, 7 medium, and 6 low
defects.
Per agent: modeller 0.83, hunter 0.91, pod 0.62.
The largest counts are 38 rejected `notes` writes, 13 watchdog terminals, 13
abandoned models, 9 rejected `hunts_store` writes, 3 triager degradations, and
3 dropped specs without a reason.

### Measurement caveats

- `procedure_fields` is 0 for all 40 specs because the metric reads
  `provenance.skill_procedure`; the artifact stores
  `skill_concretised_procedure` at the top level.
- `risk_total` drops the register threat (6.9), as described above.
- `pod_confirmed` is a candidate-level heuristic; it attributes an XSS pod to
  GT-004.
- Pod exports carry no `started_at`/`finished_at`, and `duration_ms` is 0.
  Per-pod wall time is only reconstructable from Langfuse; a 100-observation
  page shows the tail, not the lifetime.
- L0 recall 3 of 11 is inherited from iteration C, not produced by this arm.

### What limited the run

1. **The target was re-pointed mid-run.** At `21:19Z` on 2026-11-02 the shared
   synthetic host `t-1618c524.target` began serving SIYUCMS, and by `07:25Z` it
   served PrestaShop; the white-jotter container stayed up on port 46271 the
   whole time. The modeller recorded the substitution at 21:19, 21:24, 21:29,
   and 21:43. The front conf was rewritten back to white-jotter at `13:55:40Z`.
   This is the dominant cause of the late-run losses.
2. **Thirteen abandoned units.** The modeller wrote `COMPLETED` with no
   vulnerability section for 12 units; the completion checker archived them.
   Nine of the 13 abandonments happened after the substitution, so the
   substitution and the workflow defect compound.
3. **Thirteen watchdog timeouts.** Seven ended on the substituted host; six
   ended on white-jotter after 31-81 calls. None was stopped by the token cap;
   their terminals precede it by 4 to 13 hours. The six are a work-volume and
   turn-latency problem, not a CPU problem.
4. **Three triager crashes.** `'dict' object has no attribute 'model_dump'`
   converted three pods to `no-symptom-evidence`.
5. **GT-007 partial.** The pod observed the GT symptom, then the host
   re-pointed; the watchdog terminal is unconditionally `unsuccessful`, so the
   export lost the confirmation.
6. **GT-006 missed.** `Service:media-asset-serving` was created seven minutes
   after the substitution, never probed `/api/file/`, and closed zero-threat.
   The unit's own note says its faults were "unknown, not absent".
7. **GT-001 partial.** The model loaded four classes at `/api/login` but not
   `weak-credential-discovery`. The spec that would have submitted `admin/123`
   ran against the substituted host and was infeasible.
8. **GT-004 missed.** The suite has no logging-sink/JNDI class, the L1 has no
   logging unit, and the modeller explicitly refused log-injection.
9. **The inherited L0 graph is thin.** L0 endpoint recall is 3 of 11;
   `/api/logout`, `/api/admin/user`, `/api/admin/content/article`,
   `/api/search`, and `/api/file/cover.png` are absent.
   The seeded arm cannot repair recon, so GT-001, GT-004, and GT-006 lack an L0
   anchor.
10. **Tool-contract defects cost turns.** 38 `notes` writes were rejected
    because the prompt does not document the `cmd` field, and 9 `hunts_store`
    writes plus 1 `assess_impact` write were rejected on schema.
    One `graph_view` read was refused as write-shaped Cypher and terminaled an
    IDOR pod as `technical-infeasibility`.

The primary hypothesis is supported for the scored and dispatched XSS.
The residual misses split into one environmental cause (006 and most of the
late-run losses), one knowledge-base cause (004), one class-selection cause
(001), and one pod-terminal cause (007).

## Learnings

1. **The CVSS 4.0 correction moved the primary GT direction.**
   The stored XSS went from 6.0 and undispatched in D to 9.3, rank 2, and two
   clean confirmations in C.a.
   The victim-action and assumed-premise penalties are gone from the scored
   rows.
2. **The dispatch queue is not the binding constraint.**
   The five GT-relevant directions reached the hunter at ranks 2, 3, 5, 6, and
   9.
   The queue delivered them; the losses are upstream (unit assessment) and
   downstream (pod execution).
3. **The target substitution is the dominant residual cause.**
   The shared synthetic host was re-pointed at `21:19Z`.
   Nine of the 13 abandonments, seven of the 13 watchdog timeouts, and all four
   residual GT verdicts carry a substitution element; for GT-006 and GT-007 it
   is the proximate cause.
   The white-jotter container never moved; the hostname did.
4. **The workflow regression is real but secondary.**
   Twelve of 13 abandoned units wrote `COMPLETED` with no vulnerability
   section.
   The first guard was vacuous for that shape; the follow-up closes it.
   The fix is necessary, but it would not recover GT-006 without a stable
   target.
5. **The pod terminal path loses observed symptoms.**
   GT-007's pod saw the 1575-byte administrator menu, then the substitution and
   the watchdog turned the export into `unsuccessful`.
   A watchdog terminal is a transport failure, not evidence of absence.
6. **The triager crash path is a verdict-integrity defect.**
   Three pods degraded to `no-symptom-evidence` on
   `'dict' object has no attribute 'model_dump'`.
   A serializer exception must not become a negative domain result.
7. **GT-001 and GT-004 are model-side coverage gaps.**
   The sign-in unit loaded four classes but not `weak-credential-discovery`,
   and displaced the reset-to-123 to account-recovery.
   The suite has no logging-sink/JNDI class, and the L1 has no logging unit.
8. **The impact review is clean.**
   All 27 reviewed rows are `mining: sufficient`, and 13 of 14 units are in
   scope.
   The row-level impact reasoning is not the weakness.
9. **The C.a-versus-D pod comparison is confounded.**
   The GT counts are comparable because the assessor read the evidence; the
   pod success and timeout shares are not, because C.a's target moved.

## Recommendation

1. **P0: guard the target identity and isolate the host.**
   Assert the expected target fingerprint at the start of every modeller unit,
   hunter spec, and pod session.
   Abort or defer the run on a mismatch; never probe the substituted origin.
   Give each trial its own hostname and port so another iteration cannot
   re-point it.
2. **P0: make the pod terminal symptom-preserving.**
   On watchdog, if the experiment log holds a domain-confirmed symptom, export
   a domain terminal or an evidence-bearing partial record.
   Keep the infrastructure reason, but do not discard the observation.
3. **P0: normalise the triager result.**
   Accept both the typed decision and the dict shape before serialisation.
   A serializer error must be a named `triager-error`, never
   `no-symptom-evidence`.
4. **P1: land the store fixes.**
   `8d5c9f83` and `b312032a` belong on the improvement trunk, the experiment
   trunk, and dev.
5. **P1: close the model-side coverage gaps.**
   Bind the shipped default credential to the sign-in unit and load
   `weak-credential-discovery`.
   Treat the operator bootstrap credential as a candidate, not only as
   legitimate context.
   Add a logging-sink/JNDI class and inventory the logging dependency on the
   owning units.
   Require a probe of the unit's own route before closing it as zero-threat.
6. **P1: fix the tool contracts and the measurement paths.**
   Document the `notes` tool's `cmd` field and accept the `option`/`body`
   aliases.
   Allow read-shaped `MATCH ... WHERE ... CONTAINS` in `graph_view`.
   Fix `procedure_fields` (read the artifact path), `risk_total` (stamp the
   consumed register threat), and `pod_confirmed` (do not match an XSS pod to
   GT-004).
7. **P2: recover the inherited L0 gap.**
   `/api/logout`, `/api/admin/user`, `/api/admin/content/article`,
   `/api/search`, and `/api/file/cover.png` are absent from the seeded graph.
   A hunting-only arm cannot repair them; the next recon arm must.
8. **P2: re-run C.b on a dedicated host.**
   Same target, budget, and frozen settings, with the fixes above.
   Compare GT counts and row quality; do not compare pod rates with D until
   the target is stable.

## Next steps

- Merge this branch: fast-forward `feat/threat-modeller-impact-refinement` and
  `hunt-enhancement-trunk`, then fold the fixes and the report into `dev`.
- File the four proposed issues from `diagnoses.yaml`: the default-credential
  binding, the logging-sink/JNDI class, the media-route probe, and the pod
  terminal path.
- Run C.b on an isolated host.
- Keep the sibling `iter-c-eval-hunting-config` out of this convergence.

## Follow-up fixes (2026-11-04)

### Triager structured-response staleness

The staged triage runs four schemas on one `pod_triager` thread: assessment,
divergence, mine, and terminal.
A turn that produces no new structured output leaves the prior checkpoint value
in the state.
The miner read the prior stage's response.
When that response was a dict, `default_triager_fn` called `model_dump` on it,
and the broad except mapped the `AttributeError` to `no-symptom-evidence`.

The turn boundary now ignores a structured response unchanged from the prior
checkpoint, validates a dict against the current schema, and rejects a foreign
object.
`TriagerDecision` forbids extra fields, so an assessment or divergence dict
cannot masquerade as a triager verdict.
Commit `cfb4f0ad`.

The runtime traces that would confirm which stage left the dict live in the
eval Langfuse project.
The eval server was unreachable at fix time, so the code-level mechanism is
confirmed and the exact trigger (KB crash versus runner termination) is not.

### Notes contract

The C.a modeller made 38 `notes` writes with `option`/`body` but no `cmd`.
The tool description now states the requirement on the first line and repeats
it in the `cmd` field, with a valid write shape.
Commit `6d58e9e9`.

### Pod trajectory assessment

The IDOR overwrite pod ran a genuine control-read, pagination, host/port, and
pre-image sequence.
At its last observation it found the list record carrying its marker while the
canonical read still showed the pre-image.
That is a list/read divergence, not the full spec symptom.
It was cut while still investigating.

The XSS id-addressed pod ran the control read, the JS route inventory, the
pre-image comparison, and the id-addressed write.
The write did not change the record.
Its browser confirmation produced a timeout warning before the target
substitution.
Its execution was genuine; the overwrite did not land.

Both pods stayed on the spec's axes and did not fabricate evidence.
The IDOR pod's bottleneck was the target behaviour and the substitution, not
Kali.
The XSS pod's browser stage is the Kali cost.
