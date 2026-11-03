# Iteration C.a - measurement preview

Status: deterministic metrics computed 2026-11-03T15:00Z, before the diagnosis node.
The official `metrics.yaml`, `measurements.yaml`, and `measurements.md` follow the
driver's close-verify, store materialisation, and measurement steps.
This file records the numbers those steps must reproduce.

## Trial identity

| Item | Value |
|---|---|
| Trial | `white-jotter-1-20261103T143924-1618c524` |
| Project | `cbd28a7d-30cb-498b-8e7a-eaa9bc8f37c8` |
| Run | `c84d2ada-e05c-42ba-bb12-8386119796f8` |
| Start | `2026-11-02T18:27:04Z` |
| Finish | `2026-11-03T14:39:24Z` |
| Terminal | `stopped` at the 7M token cap |
| Eval SHA | `f020dafd12f3f8f525fad2496c64141b6e4f8fc8` |
| Stack fingerprint | `3d396661b0ad9bb7f96101d102feaeba216b9189cef5c57ece87b9f69b56ede5` |

Wall clock: 20 h 12 min.
The token cap bound the run; the 24 h trial clock did not.

## Official GT counts

Source: `/opt/eval-tmp/metrics-ca-preview.yaml`, produced by `eval/measure_utm.py`
from `trial.yaml` and the official `verdicts.yaml`.

| Metric | Value |
|---|---:|
| GT total | 7 |
| Identified | 3 |
| Partial | 2 |
| Missed | 2 |
| Identification rate | 0.4286 |
| Partial-or-identified rate | 0.7143 |
| Core floor | 7 / 7 |
| Full core | 2 / 7 |

Verdicts:

| GT | Verdict | Confidence | Matched unit | Class |
|---|---|---:|---|---|
| `white-jotter-001` | partial | 0.40 | `Service:sign-in` | username-enumeration-oracle |
| `white-jotter-002` | identified | 0.82 | `ReverseProxy` | broken-function-level-authorization |
| `white-jotter-003` | identified | 0.95 | `Service:article-management` | xss-stored |
| `white-jotter-004` | missed | 0.90 | - | - |
| `white-jotter-005` | identified | 0.96 | `RESTApi:api` | sql-injection |
| `white-jotter-006` | missed | 0.88 | - | - |
| `white-jotter-007` | partial | 0.55 | `RESTApi:api` | mass-assignment |

The three identified directions are 002, 003, and 005.
Against D, C.a gains 003 (the stored XSS D scored 6.0 and never dispatched) and
loses no identified direction.
001 and 007 stay partial; 004 and 006 stay missed.

GT graph binding from the same metrics file:

| GT | Expected unit | Present | L0 | Core | Verdict |
|---|---|---|---:|---:|---:|---|
| 001 | `Service:account-sign-in` | yes | yes | 1.00 | partial |
| 002 | `AuthorizationSystem:__singleton__` | yes | no | 0.67 | identified |
| 003 | `Service:article-publishing` | yes | no | 0.67 | identified |
| 004 | `AuthorizationSystem:__singleton__` | yes | no | 0.67 | missed |
| 005 | `Service:book-search` | yes | no | 0.67 | identified |
| 006 | `Service:book-cover-serving` | yes | no | 0.33 | missed |
| 007 | `Service:account-registration` | yes | yes | 1.00 | partial |

Every expected unit is present in the copied graph.
The misses are not unit-recall misses.

## Token budget and call split

| Role | Capped | Share | Calls | Total context | Generated |
|---|---:|---:|---:|---:|---:|
| Pod runner | 3,351,362 | 47.9% | 1,614 | 69,285,570 | 1,083,000 |
| Threat modeller | 1,419,105 | 20.3% | 522 | 118,695,521 | 773,658 |
| Hunter | 1,282,776 | 18.3% | 291 | 20,004,696 | 351,714 |
| Pod triager | 949,797 | 13.6% | 83 | 1,487,141 | 98,587 |
| **Total** | **7,003,040** | **100%** | **2,510** | **209,472,928** | **2,306,959** |

Overshoot: 3,040 tokens (0.04%).
The trial record's earlier snapshot was stale; the driver log and the usage
endpoint agree on 7,003,040.

Against D:

| Role | D capped | D share | C.a capped | C.a share | Delta |
|---|---:|---:|---:|---:|---:|
| Pod runner | 3,049,457 | 43.5% | 3,351,362 | 47.9% | +301,905 |
| Threat modeller | 2,210,283 | 31.6% | 1,419,105 | 20.3% | -791,178 |
| Hunter | 1,189,035 | 17.0% | 1,282,776 | 18.3% | +93,741 |
| Pod triager | 555,156 | 7.9% | 949,797 | 13.6% | +394,641 |

The modeller spent 36% less and produced half the rows.
The runner spent 10% more over 37 pods than D spent over 47 terminal pods, so
the capped cost per pod rose from 64.9K to 90.6K.
The triager spent 71% more with 26% more calls.

## Model production

Raw model, before the impact review scope filter:

| Metric | Value |
|---|---:|
| Unit models | 27 |
| Produced | 3 |
| Consumed | 11 |
| Abandoned | 13 |
| Units with threats | 8 |
| Impact rows | 28 |
| Threat rows | 14 |
| Precursor rows | 14 |
| Chain rows | 3 |
| Cross-unit references | 2 |
| Impact chain rate | 10.7% |
| Risk total | 106.9 / 156.25 |
| Critical / medium | 7 / 7 |
| Saturation at 9.0+ | 7 |
| Assumed-premise penalties | 0 |
| Victim-action penalties | 0 |
| Fence hits | 0 |

Reviewed model, from the official `metrics.yaml`:

| Metric | Value |
|---|---:|
| Impact rows | 27 |
| Threat rows | 14 |
| Precursor rows | 13 |
| Capability rows | 27 |
| Green / red | 14 / 1 |
| Green share | 0.933 |
| Risk total (metric) | 100.0 / 156.25 |
| Risk total (14 threat rows) | 106.9 / 156.25 |
| Critical / medium | 7 / 6 in the metric; 7 / 7 over all 14 rows |
| Class-binding rate | 1.00 |

The reviewed set excludes the one out-of-scope
`IntegrationSystem:cross-origin-policy` row, which carries risk 0.
The metric's 100.0 is a path defect: it drops
`consumed/Service-register/threat-1.yaml` (6.9) because the parent model lives
in `produced/`; the 14 threat rows sum to 106.9.

Against D:

| Metric | D | C.a |
|---|---:|---:|
| Impact rows | 55 | 28 |
| Threat / precursor | 27 / 28 | 14 / 14 |
| Chain rows | 4 | 3 |
| Risk | 150 / 180 | 106.9 / 156.25 |

D's chain count is a pair count in its report; C.a counts rows with a non-empty
capability path.
The 10.7% C.a row rate is the comparable figure.

## The abandonment defect

All 13 abandoned units are in state `COMPLETED` with `validation.valid: false`.

| Cause | Units |
|---|---:|
| Missing `assumptions`, `vulnerabilities`, `impact_assessment` | 9 |
| Missing the same three plus `technical_sharpening.interface_agreements` | 2 |
| Missing the same three plus referential errors | 1 |
| Referential errors only (one impact row present) | 1 |

Twelve of 13 units wrote no vulnerability at all.
The assessment-coverage guard landed at `8d5c9f83` only checks non-dropped
vulnerabilities, so it is vacuous for those twelve.
That is why the guard did not prevent this failure, and it is the reason for the
follow-up fix in this branch.

The abandoned set includes `Service:media-asset-serving`, the unit that owns
GT-006's cover-serving handler.
That abandonment is the direct cause of the 006 miss.
The other 006-relevant model, `Service:book-management`, is also abandoned, and
`Service:library-catalog` produced no traversal row.

## Pod audit

Source: the 37 terminal pod exports under
`hunting/test-executor-pod/*/c84d2ada-...yaml`, audited per interpretation.

| Metric | Value |
|---|---:|
| Terminal pods | 37 |
| Raw `symptom-confirmed` | 15 |
| Audited confirmations | 15 |
| Audited rate | 100% |
| Watchdog timeouts | 13 |
| No-symptom evidence | 5 |
| Technical infeasibility | 2 |
| Node timeout | 2 |

The 13 watchdog timeouts are 35.1% of terminal pods.
D had 17 of 47 = 36.2% at the 60-minute bound.
Raising the bound to 90 minutes did not reduce the timeout share.

Audited confirmations by family:

| Family | Audited | GT relation |
|---|---:|---|
| `xss-stored` | 2 | GT-003 |
| `sql-injection` | 1 | GT-005 |
| `broken-function-level-authorization` | 1 | GT-002, weak attestation |
| `account-recovery` | 1 | GT-001 adjacent |
| `username-enumeration-oracle` | 3 | GT-001 adjacent |
| `concurrent-duplication` | 2 | novel |
| `stored-artifact-disclosure` | 4 | novel |
| `idor` | 1 | novel |
| `mass-assignment` | 0 | GT-007, symptom in trail, watchdog |

The audited count includes one weak attestation: the BFLA pod's `v1` note has no
classification and rests on a single ~61 s window.
The assessor accepted it at 0.82 for GT-002.
No export is wholly unsupported.

The official `metrics.yaml` records 6 GT-related pod confirmations and 10
confirmed non-GT findings.
Its per-vuln matcher attributes an XSS pod to GT-004, which has no JNDI pod, so
treat `pod_confirmed` as a candidate-level heuristic.
The strict audit finds 4 terminal GT confirmations plus the GT-007 raw trail.

## Pod-layer defects observed

1. **Triager crash degrades to absence.**
   Three pods carry `triager degraded: 'dict' object has no attribute 'model_dump'`
   and were exported `no-symptom-evidence`:
   `broken-function-level-authorization__vhost-host-header__anonymous`,
   `concurrent-duplication__parallel-burst__roster-read-model-degraded__minted-session-required`,
   and `username-enumeration-oracle__disabled-vs-enabled__exact-spelling__pairwise`.
   A serializer exception is treated as a negative domain result.

2. **Export contract contradicts its interpretations.**
   The GT-002 pod exports `clean: true` with one `runner-failure` interpretation
   and one unclassified confirmation.
   The verdict survives, but the export cannot be audited mechanically.

3. **Watchdog loses a confirmed GT-007 symptom.**
   The mass-assignment pod's experiment log shows the admin menu at 1,575 bytes
   after a `roles:[{"id":1}]` registration.
   The pod terminal is `pod-watchdog-timeout`, so the official verdict is
   partial rather than identified.
   The 90-minute bound still cuts a run that had the symptom in hand.

## GT direction details

| GT | Model produced | Hunt rank | Pod outcome | Verdict |
|---|---|---|---:|---|
| 001 | no; sign-in enumeration at 6.9 | 9 | 3 clean enumeration variants | partial |
| 002 | yes, 9.2 | 3 | 1 weak in-window confirmation | identified |
| 003 | yes, 9.3, chained | 2 | 2 clean XSS variants | identified |
| 004 | no; `AuthorizationSystem` row is a precursor | - | - | missed |
| 005 | yes, 9.2 | 5 | 1 clean UNION confirmation | identified |
| 006 | no; `media-asset-serving` abandoned | - | - | missed |
| 007 | yes, 9.2 | 6 | symptom in trail, watchdog terminal | partial |

The GT-relevant directions that reached the hunter were dispatched at ranks 2,
3, 5, 6, and 9.
The dispatch queue was not the binding constraint.

## Caveats

- This preview is deterministic and read-only.
- The official measurement adds the eval-measurer's judgement from the corpus,
  Langfuse, and the live usage endpoint.
- The diagnosis node was still running when these numbers were computed.
- The 006 abandonment is a workflow cause, not a scoring cause.
- The 004 miss is a fault-class miss on a present unit.
- The 001 miss is a class miss at the correct locus.
