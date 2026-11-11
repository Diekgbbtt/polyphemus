# Pod terminal-record failure diagnosis

Status: implemented.
Date: 2026-11-11.
Scope: the test-executor pod's terminal record family.

## Root cause

The pod terminal record had no single owner.
Four write paths touched one record family, and each owned a different address:

| Write | Writer | Address | Trigger | Failure behaviour |
|---|---|---|---|---|
| `experiment_summary` | Runner model through `PodNoteTool` | `<spec_id>/experiment-log/<order>.yaml`, where the model supplied `order` | P3 final tool call | The write succeeded at whatever order the model guessed. |
| Experiment-log slice | `ExperimentLog._persist` | `<spec_id>/experiment-log/<order>.yaml`, derived from `variant_ref` | Every observation, KB observation, interpretation | Silently fail-open; it preserved a summary already on file. |
| `PodExport` | `finalize_pod` | `<spec_id>/<run_id>.yaml` | Every terminal path | Fail-open; it did not check the experiment-log slice. |
| Durable pod-export note | `_record_durable_pod_export` | `hunting/pod-export/notes.yaml`, key `<hunt_key>:pod-export:<spec_id>` | Pod completion | Warned only; it stored the full export body. |

The shared defect was that the terminal record's address and terminal completeness were not owned by the deterministic layer.
The model owned the summary address.
The finalizer owned the export but not the summary check.
The surfer duplicated the export instead of treating the pod-owned file as canonical.

## Evidence

The eval instance root is `/opt/polymerhus-dev/eval/instances/data/eval-server-2/f8b93051-b523-460e-8000-978765edecb7/`.
The evidence was read read-only.

1. Wrong summary order.
   - `default-credential-replay__attacker-chosen-phpsessid__token-bearing-replay__form-body` has only `variants/v0.yaml`.
   - Its `experiment-log/0.yaml` has 9 raw observations and a `symptom-confirmed` interpretation, but no summary.
   - Its `experiment-log/1.yaml` has zero observations, zero interpretations, and a 764-character summary.
   - The checkpoint trace for the `pod_runner` thread shows the Runner writing the P3 note with `order: 1` during the v0 stretch.
   - The store returned `key=<spec_id>:1:experiment_summary` and created a phantom order 1.
   - 13 of the 27 pod specs have a summary on an order with no matching `variants/vN.yaml`.
2. Missing summary when P3 was bypassed.
   - `mass-assignment__cate-id__none` has 35 raw observations and no summary.
   - `mass-assignment__primary-key__none` has 36 raw observations and no summary.
   - Both exports carry `evidence.terminal_reason: pod-watchdog-timeout`.
   - The finalizer wrote the export but never checked the experiment-log slice.
   - 21 of 46 orders carry no summary.
3. Full-body durable note.
   - `hunting/pod-export/notes.yaml` was 3,654,761 bytes for 27 records.
   - Every body was a full `{verdict, evidence}` JSON envelope.
   - The largest body was 318,144 characters.
   - The 16 confirmed bodies totalled about 1.87 million characters.
   - The full envelope already existed at `<spec_id>/<run_id>.yaml`.

## Ranked hypotheses and outcomes

1. The summary order was model-supplied and not bound to the current stretch. CONFIRMED.
   Falsified if the write were bound, or if each wrong-order summary had a matching variant file.
2. The summary was only model-written on the P3 path, and a bypass left no summary. CONFIRMED.
   Falsified if every terminal path verified the slice and recovered a missing summary.
3. The durable note was a second copy of the export, not a stub. CONFIRMED.
   Falsified if it were compact and pointed at the export file.
4. The experiment-log slice and the summary had different writers with no single owner. CONFIRMED as the shared architectural cause.
   Falsified if one module owned the address, the merge, and the terminal check.
5. The surfer's note handler and the pod finalizer disagreed about the canonical artifact. PARTLY CONFIRMED.
   The current code wrote the durable note at pod completion through `_record_durable_pod_export`; `_verdict_stub_handler` was already a live-feed consumer that wrote nothing.
   The disagreement was between the canonical export file and the durable note.

## Chosen fix

The fix gives each terminal fact one deterministic owner.

- The harness binds the summary order.
  `PodNoteTool` and `PodNotesHandle` derive the current order from `ExperimentLog.variant_specs` and the harness `variant_ref`.
  The tool contract no longer has an `order` field; a model-supplied `order` is a coded rejection.
  Reads are scoped to the current stretch; the model cannot range another order.
- The finalizer is the last-layer checker.
  Every domain terminal verifies the current variant's non-empty `experiment_summary`.
  An empty summary triggers one recovery turn on the same `pod_runner` session, with only the `notes` tool bound.
  The repair turn cannot run new probes.
  A hard infrastructure teardown (node, tool, context, graph, or watchdog timeout) skips the recovery turn because its live context may be gone.
  The finalizer logs a remaining gap and never fabricates a summary.
- `PodMemoryStore` is the one writer of the experiment-log file.
  `update_experiment_log` performs the read-modify-write under a per-file lock.
  The capture middleware and the summary write therefore cannot lose each other's update.
- The pod-owned `<spec_id>/<run_id>.yaml` is the only terminal `PodExport`.
  The `PodExportStore` and `hunting/pod-export/notes.yaml` are removed.
  The within-run `pod_export` inbox message remains an optional live feed only.

Rejected options:

- Reject a mismatching model order and ask the model to retry.
  This keeps the model in the address path and turns a deterministic fact into a tool-call round trip.
- Add a terminal summary-status field.
  The status restates whether `experiment_summary` is present.
  The structural remedy is the recovery turn, not a new field.
- Write a synthetic summary on timeout.
  A timeout has no Runner consolidation; a synthetic summary would fabricate evidence.
- Keep the durable note as a compact stub.
  No production reader consumed it, and the pod export file already carries the terminal fact.
  A stub would keep a second write path for no functional gain.
- Keep the full durable body and lower the bound.
  The bound does not remove the duplicate canonical artifact or the write amplification.

## Compatibility and migration

- Tool schema: `order` is removed from `NoteToolSpec`.
  A caller that still sends it receives the coded `notes_args_rejected` with `order` in the fields list.
- Experiment-log slice: the layout is unchanged.
  No status field is added.
  A missing summary is observable by the absence of `experiment_summary`.
- Durable pod-export note: the store and write path are removed.
  Existing `hunting/pod-export/notes.yaml` files remain on disk as historical data and are not read.
  The hunter's legacy `provenance.verdict_stub` protection remains for old `hunting/hunter/notes.yaml` records.
- Addresses, keys, and the pod export file layout are unchanged.
- Module ownership: `PodMemoryStore` owns the experiment-log file; `finalize_pod` owns the last-layer check; the graph terminal gate owns the recovery turn; the surfer no longer owns a second export record.

## Tests that prove the fix

- `test_summary_write_rejects_a_model_supplied_order_and_uses_the_bound_order`.
- `test_domain_terminal_repairs_a_missing_summary_on_the_bound_order`.
- `test_production_runner_repair_turn_writes_the_missing_summary`.
- `test_hard_teardown_does_not_fabricate_a_summary`.
- `test_experiment_log_updates_cannot_lose_each_others_fields`.
- `test_run_pod_session_writes_no_durable_pod_export_note`.
- The updated pod, hunting, integration, and e2e suites.

## Documentation updated

- `docs/design/hunting-84-pod-memory-system-spec.md`.
- `docs/design/hunting-67-test-executor-pod-spec.md`.
- `docs/design/hunting-memory-growth-341-adr.md`.
- `docs/design/hunting-pipeline-wiring-adr.md`.
- `src/polymerhus/attack/hunting/CONTEXT.md`.
- `docs/design/domain-model.md`.

## Decision gate

Approved by the operator on 2026-11-10.
The approved direction removed the model-supplied order, removed the terminal summary-status field, and retired the durable pod-export note entirely.
The two on-disk effects are the narrower notes-tool contract and the removal of `hunting/pod-export/notes.yaml`.
