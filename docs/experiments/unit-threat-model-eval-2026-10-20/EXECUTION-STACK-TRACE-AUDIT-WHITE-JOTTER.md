# Execution stack trace and artifact audit: white-jotter 7M trial

## Scope

This report covers the execution surface of the successful 7M white-jotter trial.
The trial is `white-jotter-1-20261022T030303-1618c524`, project `4786aefc-c3fd-46c1-a2ab-45b05cc38e25`, run `5c9590ff-9a83-4cea-9aff-be1bd51e2667`.
The measured code is `5789ad3f`.
The trial record is `trial.yaml` in the run directory.
The store is the project data root on the eval server.
The app log is `/tmp/wj-app.log`.
The Langfuse sessions are the generation records for the same window.
The stop time is 2026-10-22T03:03:03Z, the trial's `finished_at`.

## Trial record

The trial terminal is `stopped`.
The phases are `recon: complete`, `analysis: drained`, and `hunting: stopped`.
No phase carries a failure.
The token snapshot is `spent_tokens=7,002,218` and `spend_overshoot=3,405`.
The settled client ledger is `7,077,163` capped.
The project-comparable Langfuse total is `7,554,580` capped.
The token reconciliation is in `TOKEN-ACCOUNTING-WHITE-JOTTER.md`.

The trial record has two stale fields:

- `assessment` is `null` although `verdicts.yaml` has 7 entries;
- `diagnosis.entries_written` is `0` and `issues_matched` is `0` although `diagnoses.yaml` has 6 entries.

The diagnosis file was written at 04:26Z and the trial record was updated at 04:27Z.
The file has the entries; the record does not reflect them.
This is a tracking defect, not an execution failure.

## Artifact inventory

The store has 23 loop files and 6 model documents.

| Family | Consumed | Produced | Total |
|---|---:|---:|---:|
| Loop files | 17 | 6 | 23 |
| Model documents | 4 | 2 | 6 |

The produced loops are `RESTApi-api/loop-2`, `loop-3`, and `loop-4`, plus `Service-article-management/loop-1`, `loop-2`, and `loop-3`.
The produced models are `RESTApi-api` and `Service-article-management`.
The `abandoned/` directory is empty.
No loop file was refused.

The hunter test-spec store has 11 terminal sets and 6 loops without a terminal set.

| Loop | Spec files | Status | Terminal set |
|---|---:|---|---|
| IntegrationSystem-cross-origin-policy loop-1 | 3 | ratified | yes |
| IntegrationSystem-cross-origin-policy loop-2 | 3 | 2 ratified, 1 dropped | yes |
| IntegrationSystem-cross-origin-policy loop-3 | 4 | 1 ratified, 3 dropped | yes |
| ReverseProxy-nginx-1.31.6 loop-1 | 3 | 2 ratified, 1 dropped | yes |
| ReverseProxy-nginx-1.31.6 loop-2 | 3 | 2 ratified, 1 dropped | yes |
| ReverseProxy-nginx-1.31.6 loop-3 | 3 | ratified | yes |
| Service-navigation-menu loop-1 | 2 | ratified | yes |
| Service-navigation-menu loop-2 | 3 | ratified | yes |
| Service-sign-in loop-1 | 5 | 4 ratified, 1 dropped | yes |
| Service-sign-in loop-2 | 3 | ratified | yes |
| Service-sign-in loop-3 | 4 | 2 ratified, 2 dropped | yes |
| Service-navigation-menu loop-3 | 2 | hypothesised | no |
| Service-navigation-menu loop-4 | 2 | hypothesised | no |
| Service-sign-in loop-4 | 2 | hypothesised | no |
| Service-sign-in loop-5 | 0 | no spec files | no |
| Service-sign-in loop-6 | 0 | no spec files | no |
| RESTApi-api loop-1 | 0 | no spec files | no |

The 6 hypothesised specs are `role-disabled-flag-ignored_stale-session-tree`, `role-disabled-flag-ignored_fresh-login-tree`, `role-cardinality_live-session-transition`, `role-cardinality_derived-tree`, `account-revocation_self-reinstate-write`, and `account-revocation_live-session-reach`.

The pod store has 27 pod directories and 23 terminal exports.

| Pod family | Count | Evidence |
|---|---:|---|
| Successful exports | 20 | `symptom-confirmed` |
| Unsuccessful exports | 3 | `no-symptom-evidence` |
| No export | 4 | experiment log active at 03:01-03:02 |

The three unsuccessful pods are `account-state-disclosure_disabled-verdict`, `forwarded-address-gate_address-gated-decision`, and `forwarded-address-record_audit-address-echo`.
All three terminate with `no-symptom-evidence` and `clean=False`.
None carries `technical-infeasibility`, `runner-failure`, or `runner-divergence`.

The four no-export pods are `filter-tier-verdict-gap_permission-denial-envelope`, `parent-grant-expansion_self-nav-tree`, `role-enabled-flag-ignored_disabled-role-nav-source`, and `role-id-unbound_nav-catalogue-disclosure`.
Their last experiment-log writes are 03:01:27, 03:01:32, 03:02:04, and 03:02:49.
The stop is 03:03:03.

## Functional failures

### E-1 - The modeller writes after the trial has stopped

This is the one clear execution defect.

The trial finished at 03:03:03Z.
The modeller session continues until 03:09:19Z.
The `Service-article-management` model and its three loops are written at 03:08:56-03:08:57Z, almost six minutes after the trial record stopped.
The post-stop modeller work accounts for 26 calls.
The three Langfuse-only generations in the prior token reconciliation are separate: they are the 02:26 and 02:34 compaction-boundary calls, not the post-stop calls.

The post-stop model document and its three loops are structurally complete.
Its loops are not hunted.
The hunter has no session for the unit.
The produced model and loops are outside the trial terminal.

The root cause is the deferred F-024 pre-emptive cap enforcement.
The stop ends the hunting phase and the trial client stops polling, but it does not cancel the in-flight modeller turn.
The modeller completes its unit, writes the model and loops, and the project store accepts the write.
The trial record and the official metrics do not include the post-stop artifacts as hunted work.

The failure chain is:

1. The cap is reached and the trial sends the stop.
2. The stop ends the phase and the trial client stops polling.
3. The in-flight modeller turn is not cancelled.
4. The modeller completes and writes the next unit model and loops.
5. The mover has already stopped, so the new model and loops are never consumed.
6. The trial record is closed, so the artifacts are orphaned.

The fix is part of F-024.
The stop must cancel or fence the in-flight stateful sessions.
A write that arrives after the stop must be rejected or marked abandoned, not accepted as produced work.
The trial record must record the final settled usage after the project is idle.

### E-2 - The `Service-sign-in__loop-5` provider failure was handled

At 02:38:12Z the hunter `Service-sign-in__loop-5` hit a provider failure.
The surfer requeued it after backoff and kept its siblings live.
The run did not pause and the cause was not fatal.
This is the F-026 behavior working as designed.

The loop-5 hunter is active again by 02:59:34Z.
It has no terminal set at the 03:03 stop.
The F-022 recovery would re-dispatch the consumed loop on a resume.
The run stopped before that recovery was needed.

This is a functional failure that was contained, not a persistent failure.
No sibling hunter was lost.

### E-3 - The reasoning-content 400 was recovered

At 03:01:03Z the LiteLLM proxy returned a 400 with `reasoning_content` in the thinking mode must be passed back.
The app logged the F-009 fallback and replayed the request once with the empty fallback field.
The replay is the designed recovery.

The `reasoning gap` warnings at 03:08-03:09Z are after the stop.
They belong to the post-stop modeller calls, not to a live hunting session.
They are a response-shape warning, not a lost turn.

The 400 is a recovered provider-shape failure.
It is not a persistent execution failure.

### E-4 - Six specs are left hypothesised at the stop

The six hypothesised specs are in the last five minutes before the stop:

- 02:58:12 to 03:01:24 for `Service-navigation-menu__loop-3`;
- 02:58:37 to 03:01:42 for `Service-navigation-menu__loop-4`;
- 02:58:47 to 03:02:59 for `Service-sign-in__loop-4`.

The hunters for those loops were alive at the stop.
The ledger last entries are 03:01:19, 03:01:37, and 03:02:55.
The specs are intermediate state, not a failed finalize.

The classification is expected cap-stop leftover.
The mover does not dispatch a `hypothesised` spec, so the specs stay in `produced/`.
The hunter would have finalized or dropped them in a later turn.

### E-5 - Three consumed loops have no terminal set

`Service-sign-in__loop-5`, `Service-sign-in__loop-6`, and `RESTApi-api__loop-1` are consumed loops with no test-spec directory and no terminal set.

Their hunter sessions are active at the stop:

- loop-5 at 02:59:34;
- loop-6 at 03:00:44;
- RESTApi loop-1 at 03:00:41.

The loop-5 session is the one that was requeued after the provider failure.
The other two are normal in-flight sessions.

The classification is expected cap-stop leftover.
The F-022 recovery reads a consumed loop with no current-run terminal set and re-dispatches it.
The run stopped before the recovery tick.

### E-6 - The RESTApi loops 2-4 are paused, and the Service-article loops are post-stop

`RESTApi-api/loop-2` to `loop-4` are produced but not consumed.
`RESTApi-api/loop-1` is consumed and its hunter is active.
The mover sequences the loops of one unit, so the later loops wait while loop-1 is live.
This is expected dispatch sequencing, not a mover defect.

The `Service-article-management` model and loops 1-3 are produced after the stop.
They are the E-1 post-stop artifact.
They are not a mover defect.

### E-7 - Four pods have no terminal export

The four no-export pods wrote their last experiment-log entries at 03:01-03:02.
They were active at the stop.
The pod exports are written at pod completion, so an in-flight pod has no export.
The F-017 recovery would re-dispatch a consumed ratified spec with no terminal pod export on a resume.
The run stopped before that recovery.

The classification is expected cap-stop leftover.

The largest no-export pod is `filter-tier-verdict-gap_permission-denial-envelope`.
Its runner session has 52 calls and 3.3M tokens, with a 94k maximum input.
Its `experiment-log/1.yaml` was written at 03:02:49 with 19 new observations and a 641-char experiment summary.
The pod was active and producing evidence, not hung.

### E-8 - The three unsuccessful pods are valid negatives with a quality flag

All three unsuccessful pods terminate with `no-symptom-evidence`.
None is a technical infeasibility, a runner failure, or a runner divergence.
They are the pod's honest negative result for their specs.

The quality flag is `clean=False`.
The triager terminated with no-symptom evidence but did not report a clean exhaustion.
That is a quality signal about the evidence space, not a degraded runner or triager.
It should be carried into the measurement record, not treated as a functional failure.

### E-9 - The mover has no defect

The store shows the mover's moves:

- 17 loops and 4 models in `consumed/`;
- 6 loops and 2 models in `produced/`;
- 0 files in `abandoned/`;
- no refused loop.

The 6 consumed loops with no terminal set are the F-022 recovery candidates.
The 4 pods with no export are the F-017 recovery candidates.
Both recoveries are designed for a resume.
The run stopped before either recovery could run.

The mover did not fail.
The paused RESTApi loops are the sequence rule.
The post-stop Service-article artifacts are the E-1 stop failure, not the mover.

### E-10 - The trial record is stale relative to the assessment and diagnosis files

`verdicts.yaml` has 7 entries.
`trial.yaml` has `assessment: null`.

`diagnoses.yaml` has 6 entries.
`trial.yaml` has `diagnosis.status: dispatched`, `entries_written: 0`, `issues_matched: 0`, and `issues_proposed: 0`.

The files are the source of truth for the assessment.
The trial record's fields are stale.
The token section is also the terminal snapshot, not the settled ledger, as the prior reconciliation shows.

This is a tracking defect.
It is separate from the execution defect.
It matters because a reader of the trial record would conclude that no assessment or diagnosis exists.

## Classification

| Artifact or event | Count | State | Time relative to stop | Classification |
|---|---:|---|---|---|
| Hypothesised specs | 6 | produced, no terminal | 02:58-03:02, before stop | expected cap-stop |
| Consumed loops without terminal | 3 | consumed | active at 03:00-03:03 | expected cap-stop |
| RESTApi loops 2-4 | 3 | produced | 02:50, before stop | expected pause |
| Service-article model and loops | 4 | produced | 03:08, after stop | E-1 defect |
| Pods with no export | 4 | active | 03:01-03:02, before stop | expected cap-stop |
| Unsuccessful pods | 3 | terminal no-symptom | 01:07-02:14 | valid negative, clean=False |
| Terminal hunter sets | 11 | terminal | 00:23-02:19 | complete |
| Loop-5 provider failure | 1 | requeued | 02:38, before stop | handled by F-026 |
| Reasoning-content 400 | 1 | replayed | 03:01, before stop | handled by F-009 |
| Post-stop modeller calls | 26 | executed | 03:03-03:09 | E-1 defect / F-024 |
| Assessment and diagnosis record | 7 and 6 | files present | 04:01 and 04:26 | E-10 tracking defect |

## What the user asked about

The runner and triager pods did not show a degraded state.
The three unsuccessful pods are valid no-symptom negatives.
The four no-export pods were active at the stop, not failed.
The pod exports contain no `technical-infeasibility` and no `runner-failure`.

The hunters did not show a persistent degraded state.
One hunter hit a provider failure and was requeued by F-026.
The six loops without a terminal set were active at the stop.
The six hypothesised specs are their in-flight state.

The mover worked.
It consumed 17 loops and 4 models and refused none.
The F-022 and F-017 recoveries are pending because the run stopped.
The RESTApi loops 2-4 are correctly paused behind their live loop-1.
The Service-article artifact is the post-stop defect, not a mover defect.

The functional failures are the post-stop execution and the stale trial record.
The provider failure and the 400 were recovered.

## Fixes

### F-024 stop fencing

The stop must fence the in-flight stateful sessions.
The app must reject a produced write after the stop, or mark the unit abandoned.
The trial record must settle the client usage after the project is idle.
The post-stop model and loops must not appear as normal produced work.

### F-022 and F-017 on resume

The resume must run the consumed-loop recovery and the pod-export recovery before it counts the run as quiescent.
The recovery should report the recovered loops and pods in the run record.
The cap-stop leftovers must be visible as recovered work, not as silent losses.

### Pod clean flag

The three unsuccessful pods carry `clean=False`.
The pod triager should record why the space was not cleanly exhausted.
The measurement should treat the flag as a quality signal, not as a functional failure.

### Tracking record

The monitor should stamp `assessment` and `diagnosis` from the files it writes.
The trial record should not report `entries_written: 0` when `diagnoses.yaml` has 6 entries.
The token section should be the settled ledger, not the terminal snapshot.

## Reproduction

The app log:

```
ssh -i <key> root@<host> 'docker logs ph-dd131acc-agent-1 > /tmp/wj-app.log'
grep -nE "provider failure|reasoning_content|ERROR|mover:|surfer:" /tmp/wj-app.log
```

The store inventory:

```
python3 - <<'PY'
# walk the project data root
# parse status, run_id, terminal sets, pod exports
PY
```

The pod evidence:

```
python3 - <<'PY'
# load each pod export and print terminal_reason, clean, iterations
PY
```

The trial record:

```
python3 - <<'PY'
import yaml
# load trial.yaml, verdicts.yaml, diagnoses.yaml
PY
```

The Langfuse session query is the same as in the context report.

## Limitations

The loop files have no `status` field.
The loop completion marker is the terminal set, not a status on the loop file.
The model documents have no status field in the parsed docs.
The pod export carries `verdict`, `terminal_reason`, `clean`, `iterations`, and the evidence, but not a wall-clock end time.
The `mtime` is the file write time and is used as the activity time.
The post-stop classification uses the trial `finished_at` 03:03:03Z.
The three no-symptom pods are classified from their own `terminal_reason` and `clean` fields.
The F-022 and F-017 recovery behavior is read from the code and the store layout; the run stopped before either recovery was exercised.
