# ADR: remove the confidence score from the L0-L1 `AGGREGATES` edge

Date: 2026-10-15.
Status: accepted.
Supersedes: the confidence half of `docs/design/assigner-A1-decisions.md` D2
(`ASSIGN_CONFIDENCE_BAR = 0.75`) and the "Confidence" / "Withholding gate"
sections of `src/polymerhus/analysis/CONTEXT.md`.

## Context

The Assigner judged ownership on a graded `confidence` and `withhold_below_bar`
dropped every aggregate below `ASSIGN_CONFIDENCE_BAR` (0.75). The bar was
documented as "an EMPIRICAL PLACEHOLDER, not a reasoned number" and was never
swept in production, so the one epistemic brake against the measured 31-38%
over-assignment was an unexamined constant. The scale was not even stable: 213 of
675 live `AGGREGATES` edges carried percentages (30.0-95.0), each one silently
clearing the bar before `normalise_confidence` was placed ahead of it. A score
whose only consumer is one unmeasured threshold is cost without a guarantee.

## Decision

Remove the confidence score from the `AGGREGATES` edge, completely, and write
every structurally-valid aggregate (admit-all).

1. The proposal carries `service_slug`, `l0` and `evidence_refs` - and nothing
   gradable. `AggregatesProposal.confidence` is gone.
2. The edge carries `status`, `provenance`, `ts` and `evidence_refs`.
   `JudgmentEnvelope.confidence` is gone; `evidence_refs` stays as the grounding
   anchor on both the proposal and the edge.
3. `normalise_confidence`, `withhold_below_bar`, `ASSIGN_CONFIDENCE_BAR` and the
   `bar` threading through `shape_proposal` / `assign` / `make_assigner_body` are
   gone.
4. `AssignmentStats` loses the `rescaled` and `withheld` counters. The structural
   counters (`admitted`, `proposed`, `unresolvable`, `out_of_inventory`, `kept`)
   stay.
5. `evaluation` loses `bar_sweep` and the `confidences` / `mean_confidence` read,
   and `ASSIGNMENT_INTEGRITY_KEYS` loses `withheld_rate` and `mean_confidence`.
6. The observability record no longer persists raw per-aggregate confidences or
   the bar.
7. All prompt verbatim about confidence, scores, bars and anchors is removed; the
   scored worked examples are rewritten scoreless.

Structural gates STAY. An out-of-inventory `service_slug`, an unresolvable `l0`
reference, and a malformed proposal are dropped exactly as before: these name a
reference to nothing, not a weak judgment, and no confidence ever rescued them.

`anatomy.py`'s High/Medium/Low confidences are a DIFFERENT classification feature
and are explicitly out of scope.

## Impact map

Source (changed):

- `src/polymerhus/analysis/assigner.py` - the withholding gate, the scale gate,
  the bar constant and its threading, the `AssignmentStats` counters, the prompt
  verbatim, the observability persistence.
- `src/polymerhus/analysis/analyser_types.py` - `AggregatesProposal.confidence`,
  the `proposals_to_deltas` envelope build, the module docstring.
- `src/polymerhus/analysis/l1_types.py` - `JudgmentEnvelope.confidence`.
- `src/polymerhus/analysis/l1_curator.py` - the `confidence` edge property in
  `build_aggregates_cypher`.
- `src/polymerhus/analysis/evaluation.py` - `bar_sweep`, the confidence columns
  and integrity keys, `read_assignment`, `assignment_metrics`, `evaluate_assigner`.
- `src/polymerhus/analysis/prompts/assigner.md` - the HOW file's calibration and
  scored examples.
- `src/polymerhus/app/observability/analyser_tracing.py` - docstring examples
  that cited the assigner's confidence persistence.

Tests (changed): `tests/analysis/test_evaluation.py`,
`tests/analysis/test_analyser_pod.py`, `tests/analysis/test_l1_curator_builders.py`,
`tests/analysis/test_l1_template_key.py`, `tests/integration/test_assigner_contracts.py`,
`tests/integration/test_assigner_eval_live.py`,
`tests/integration/test_l1_curator_merge.py`,
`tests/integration/test_l1_curator_reconcile.py`,
`tests/integration/test_index_card_merge.py`,
`tests/integration/test_sweep_merge.py`,
`tests/integration/test_bootstrap_merge.py`,
`tests/integration/test_analyser_pod_merge.py`,
`tests/integration/test_delivery_merge.py`,
`tests/integration/test_decoupling_contracts.py`,
`tests/e2e/test_assigner_walkthrough.py`, `tests/e2e/test_walkthrough_nfr.py`,
`tests/test_analyser_tracing.py`.

Out of scope, listed as a work item: `tests/analysis/test_data_modeller.py`,
`tests/integration/test_data_modeller_contracts.py` and
`tests/e2e/test_data_modeller_walkthrough.py` still pass a `confidence=` kwarg
when they build an `AggregatesProposal`. Pydantic ignores the now-unknown field,
so these tests stay green, but the kwargs are dead weight and should be deleted
when the data_modeller files are next touched.

`eval/` has no match in scope: its `confidence` field is the assessor/diagnoser
verdict confidence, a different feature.

Historical design docs that describe the old mechanism (NOT rewritten here; this
ADR supersedes the relevant parts):

- `docs/design/domain-model.md` (Confidence section, the withholding
  meta-claim, the `normalise_confidence` correction).
- `docs/design/assigner-A1-decisions.md` (D2 bar).
- `docs/design/service-sourced-analysis-adr.md` /
  `docs/design/service-sourced-analysis-spec.md` (the five shaping gates, the
  withheld census).
- `docs/design/recon-analysis-decoupling.md` (the withheld-rate columns).
- `docs/design/dataplane-A1-decisions.md` (the typist's missing `AssignmentStats`
  analogue).
- `docs/design/analysis-unit-enrichment-assigner-subproblems.md` (the gate order).
- `docs/design/typesafe-system-one-evaluation.md` (the bar-sweep experiment).
- `src/polymerhus/analysis/CONTEXT.md` (Confidence, Withholding gate, Shared
  ownership, Assigner shaping) - applied by the coordinator at merge.

## Consequences

- **Stale-pool semantics change.** The stale pool used to be partly an epistemic
  ledger: an element the model judged and doubted stayed stale. It is now purely a
  structural residual: an element stays stale only when no proposal named it, or
  when its proposal named a non-existent Service or an unknown Endpoint. The
  `stale_pool` column is therefore no longer a proxy for model doubt, and
  `withheld_rate` is gone with the gate that produced it.
- **Over-production caveat (recorded, unresolved).** The codebase documents
  over-production as the assigner's MEASURED failure mode: live runs assigned
  roughly a third of surface on topical affinity, and the same surface drew wildly
  different assignment volumes run to run. The withholding bar was that failure's
  only epistemic brake. Admit-all removes it. The structural gates stay, but they
  are not epistemic: they drop references to nothing, never a judgment the model
  was unsure of. Assignment precision now depends on the prompt's judgment
  discipline alone, so the prompt is the load-bearing control and the comparative
  eval harness must be read with that in mind.
- `AssignmentStats.rescaled` and `withheld` disappear; the surviving counters are
  the structural ones. `withheld_rate` and `mean_confidence` disappear from
  `ASSIGNMENT_INTEGRITY_KEYS`, so the harness's assignment-volume-integrity
  columns are now `coverage`, `stale_pool`, `stale_rate`, `out_of_inventory_rate`,
  `unresolvable_rate` and `multi_owner_endpoints`.
- The prompt-cache prefix changes shape: the assigner's `_ROLE_VERBATIM`,
  `_FEW_SHOTS` and `assigner.md` lose their confidence text, so the baseline arm
  and the skill arm both move. The existing byte-identity tests pin the new
  content by construction.
