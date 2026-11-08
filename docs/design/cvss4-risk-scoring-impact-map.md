# CVSS 4.0 risk scoring - impact map

*Status: spec-phase artifact, 2026-10-31. Companion to `cvss4-risk-scoring-spec.md`.*
*This map is the index of every component the change touches. It is an input to `/to-tickets`; it is not an implementation.*

## 1. The change axis

The change replaces one scoring model with another:

- the threat's `likelihood` and `impact` fields are deleted;
- the assessment row gains `factors`, `risk`, and `risk_vector`;
- the `assess_impact` tool becomes the sole writer of an assessment row;
- the threat's `risk` becomes a derived mirror of the assessment score;
- `confidence` leaves `Threat` and `Vulnerability`;
- the dispatch queue becomes per-threat risk descending;
- the two thresholds become floats;
- the schema becomes v5, with a v4 raw read.

Every component below either writes, reads, renders, validates, tests, or documents one of those facts.

## 2. Core schema and scoring

| Component | Owning spec | Change | Tests |
|---|---|---|---|
| `attack/hunting/threat_model.py` | `hunting-67-threat-model-artifact-spec.md` 5.1, 5.6, 7 | Remove `Likelihood`, `RISK_WEIGHTS`, `Impact`, `ImpactLevel`, `ImpactSeverity`, `IMPACT_METRIC_WEIGHTS`, `impact_weight`, `impact_severity`. Add `SeverityBand`, `RiskMetrics`, `ThreatWrite`. Change `ImpactAssessment`, `Threat`, `RiskProfile`, `ModelSections`, `GATE_SECTIONS`, `PRIOR_ART_PATHS`, the completion checker, and `normalise_threats`. Set `SCHEMA_VERSION = 5`. | `tests/attack/test_threat_model_impact.py`, `tests/attack/test_threat_model_store.py` |
| `attack/hunting/risk_score.py` (new) | `cvss4-risk-scoring-spec.md` 1 | The thin `cvss==3.6` wrapper: enums, `RiskMetrics`, `RiskResult`, `build_vector`, `compute_risk`, `severity_band`, `validate_metrics`, `FACTOR_DESCRIPTIONS`. | `tests/attack/test_risk_score.py` (new) |
| `attack/hunting/threat_model_store.py` | `hunting-67-threat-model-artifact-spec.md` 4.3, 5.4, 5.7, 10 | Add `write_impact_assessment`; compute the score at commit; merge by row id; advance the state; refuse a v4 write; read v4 raw; mirror the assessment risk onto the threat at `COMPLETED`; update the prior-art paths. | `tests/attack/test_threat_model_store.py` |
| `attack/hunting/threat_model.py` completion checker | `hunting-67-threat-model-artifact-spec.md` 5.7 | Add the assessment coverage, the factor presence, the risk mirror equality, the precursor all-none rule, and the capability path checks. | `tests/attack/test_threat_model_impact.py` |
| `attack/hunting/threat_model.py` prior-art catalog | `impact-assessment-system-spec.md` 7 | Add `risk`, `risk_vector`, `factors.*`, `impact_description`, `exploitability_description`; keep the v4 paths. | `tests/attack/test_threat_model_store.py` |

## 3. Modeller pass and tools

| Component | Owning spec | Change | Tests |
|---|---|---|---|
| `attack/hunting/threat_modeller_tools.py` | `unit-threat-model-tools-adr.md`; `hunting-67-threat-modeller-spec.md` 5 | Add the `assess_impact` `BaseTool`; remove `impact_assessment` from `ModelSections`; keep the `hunts_store` read/write/query surface for the other sections. | `tests/attack/test_threat_modeller.py` |
| `attack/hunting/threat_modeller.py` | `hunting-67-threat-modeller-spec.md` 5, 6 | Add the tool to `TOOL_SURFACE`; update the gate hints; keep the seven-state sequence; the first assessment advances `IMPACT_ASSESSED`. | `tests/attack/test_threat_modeller.py`, `tests/attack/test_threat_modeller_prompt.py` |
| `attack/hunting/prompts/threat-modeller.md` | `hunting-67-threat-modeller-spec.md` 5, 6 | Replace the likelihood section with the exploitability factors; add the `PR/AC/AT` chain semantics and the examples; add the `UI` passive/active rule; add the `VC/VI/VA` `high/low/none` rule with examples; add the no-confidence rule; describe `assess_impact`. | `tests/attack/test_threat_modeller_prompt.py` |
| `attack/hunting/threat_modeller.py` gate hints | `hunting-67-threat-modeller-spec.md` 5 | Replace the `IMPACT_ASSESSED` hint with the `assess_impact` call; replace the `COMPLETED` CIA hint with the "the score is derived" rule. | `tests/attack/test_threat_modeller_prompt.py` |
| `attack/hunting/CONTEXT.md` | this change | The risk vocabulary block is canonical; the old entries are marked superseded. | Documentation review |

## 4. Store, prior art, and model layout

| Component | Owning spec | Change | Tests |
|---|---|---|---|
| `attack/hunting/threat_model_store.py` `_merged_document` | `hunting-67-threat-model-artifact-spec.md` 4.3 | Accept a v5 document; refuse a v4 write; the `IMPACT_ASSESSED` section is tool-only. | `tests/attack/test_threat_model_store.py` |
| `attack/hunting/threat_model_store.py` `_commit` | `hunting-67-threat-model-artifact-spec.md` 4.4 | No change to the atomic write; the new row is part of the same document. | `tests/attack/test_threat_model_store.py` |
| `attack/hunting/threat_model_store.py` threat files | `hunting-67-threat-model-artifact-spec.md` 8.1 | Write `risk` as a float; drop `likelihood`, `likelihood_rationale`, `risk_factors`, `confidence`, `impact`, `impact_weight`. | `tests/attack/test_threat_model_store.py` |
| `attack/hunting/threat_model_store.py` query | `impact-assessment-system-spec.md` 7 | The `threat` view merges the file with the row; the `precursor` view returns v5 rows; the v4 paths still match raw. | `tests/attack/test_threat_model_store.py` |
| `attack/hunting/threat_model_store.py` v4 read | `hunting-67-threat-model-artifact-spec.md` 5.8 | Read v4 raw; never re-score; the v5 writer refuses a v4 document. | `tests/attack/test_threat_model_store.py` |

## 5. Dispatch and run lifecycle

| Component | Owning spec | Change | Tests |
|---|---|---|---|
| `attack/hunting/mover.py` | `hunting-pipeline-sync-spec.md`; `hunting-67-threat-model-artifact-spec.md` 8.3 | `threat_risk` returns `float | None`; accept a v4 int; the severity band replaces the likelihood bucket; the dispatch validity predicate reads the float risk. | `tests/attack/test_hunting_mover.py`, `tests/attack/test_hunting_threat_dispatch.py` |
| `attack/hunting/pipeline_sync.py` | `hunting-pipeline-sync-spec.md` | `promotion_risk_threshold` becomes a float; `risk_is_promoted` compares floats; `order_threats` replaces `order_units` for dispatch; `decide` and `batch_state` work the global threat frontier; no per-unit cap. | `tests/attack/test_hunting_pipeline_sync.py`, `tests/attack/test_hunting_pipeline_sync_gate.py` |
| `attack/hunting/surfer.py` | `hunting-pipeline-sync-spec.md` | The frozen threshold type becomes float; the gate passes the new queue. | `tests/attack/test_hunting_surfer_tick.py` |
| `attack/hunting/runtime.py` | `hunting-67-threat-model-artifact-spec.md` 9.2 | Resolve the float threshold; stamp the float on the run record; pass the float to the gate. | `tests/attack/test_run_lifecycle.py` |
| `attack/hunting/run_lifecycle.py` | `hunting-67-threat-model-artifact-spec.md` 7.4, 9.2 | `RiskAccumulator` uses floats; the record drops `risk_weights`, `impact_weights`, `impact_breakdown`; `risk_breakdown` is by band; `DEFAULT_RISK_THRESHOLD = 156.25`; `HUNT_RISK_THRESHOLD` parses a float. | `tests/attack/test_hunting_run_lifecycle.py` |
| `attack/hunting/hunting_agent.py` | `hunting-67-hunting-agent-spec.md` 8 | The payload read path resolves the assessment by `impact_ref`; no likelihood or threat confidence. | `tests/attack/test_hunting_agent_prompt.py` |

## 6. Payload and hunter prompt

| Component | Owning spec | Change | Tests |
|---|---|---|---|
| `attack/hunting/hunter_payload.py` | `hunting-67-hunting-agent-spec.md` 8.2 | Render `risk`, `severity_band`, `risk_vector`, `factors`, `impact_description`, `exploitability_description`, the capability chain, the enabling precursors, and the assumption confidences. Drop `likelihood`, `likelihood_rationale`, `confidence`, `impact_weight`, `risk` from the old blocks. | `tests/attack/test_hunting_agent_prompt.py` |
| `attack/hunting/llm.py` | `hunting-67-threat-modeller-spec.md` 6 | Render the model projection with the assessment rows and the risk profile in the new vocabulary. | `tests/attack/test_hunting_agent_prompt.py` |
| `attack/hunting/prompts/hunting-agent.md` | `hunting-67-hunting-agent-spec.md` 8 | Update the threat ontology: exploitability, factors, score, band, assessment, assumption confidence. | `tests/attack/test_hunting_agent_prompt.py` |

## 7. Settings and API

| Component | Owning spec | Change | Tests |
|---|---|---|---|
| `project_management/api.py` | `hunting-pipeline-sync-spec.md`; `project_management/CONTEXT.md` | `risk_threshold: float | None`, `promotion_risk_threshold: float | None`; the field descriptions state the scale. | `tests/project_management/test_hunting_config_api.py` |
| `project_management/repository.py` | `hunting-pipeline-sync-spec.md` | Parse and validate floats; keep `pod_batch_size` an integer; the stored read returns floats. | `tests/project_management/test_hunting_config_api.py`, `tests/integration/test_settings_deep_merge.py` |
| `project_management/CONTEXT.md` | this change | The two thresholds are floats; the defaults are the scaled values. | Documentation review |
| `eval/orchestrator/setup.py` | `eval-multi-instance-spec.md` | The setup reader accepts float thresholds. | `tests/eval/test_orchestrator_hunting_config.py` |
| `eval/orchestrator/trial.py` | `eval-multi-instance-spec.md` | The trial launch passes float thresholds. | `tests/eval/test_orchestrator_trial.py` |
| `eval/setups/white-jotter-iteration-c.yaml` | `eval-multi-instance-spec.md` | The thresholds are the scaled floats. | `tests/eval/test_orchestrator_hunting_config.py` |

## 8. Eval

| Component | Owning spec | Change | Tests |
|---|---|---|---|
| `eval/measure_utm.py` | `impact-assessment-system-spec.md` 9 | Add the v5 path: read the float risk, the band, and the assessment rows; keep the v4 raw path; keep the reviewed green share. | `tests/eval/test_measure_utm.py` |
| `eval/orchestrator/assessment.py` | `eval-multi-instance-spec.md` | The assessment gate accepts the v5 model; the impact review reads the new rows. | `tests/eval/test_orchestrator_trial.py` |
| `eval/orchestrator/impact_review.py` | `impact-assessment-system-spec.md` 9 | The review schema uses `impact_description`, `exploitability_description`, `factors`, `risk`, `risk_vector`. | `tests/eval/test_measure_utm.py` |
| `eval/prompts/assessment.md` | `eval-multi-instance-spec.md` | The assessor judges the new assessment rows and the new impact review labels. | Prompt snapshot |
| `eval/prompts/measure.md` | `eval-multi-instance-spec.md` | The measurer reads the v5 score and band. | Prompt snapshot |
| `eval/orchestrator/cli.py` | `eval-multi-instance-spec.md` | The metric command accepts the v5 store. | `tests/eval/test_measure_utm.py` |

## 9. Tests to change or add

| Test | Change |
|---|---|
| `tests/attack/test_risk_score.py` (new) | Known CVSS vectors, the band edges, the vector build, the mirrored `SC/SI/SA`, the precursor all-none rule. |
| `tests/attack/test_threat_model_impact.py` | The new row shape, the invariants, the score mirror, the v4 raw read. |
| `tests/attack/test_threat_model_store.py` | The tool-only assessment write, the state advance, the v5 commit, the v4 refusal, the threat file shape, the prior-art paths. |
| `tests/attack/test_threat_modeller.py` | The tool surface, the gate hints, the first-call transition, the completion findings. |
| `tests/attack/test_threat_modeller_prompt.py` | The factor semantics, the examples, the no-likelihood rule, the no-confidence rule. |
| `tests/attack/test_hunting_mover.py` | The float risk, the band, the v4 int fallback, the promotion floor. |
| `tests/attack/test_hunting_pipeline_sync.py` | The float threshold, the per-threat queue, the ties, the no-cap rule. |
| `tests/attack/test_hunting_pipeline_sync_gate.py` | The global frontier, the batch state, the pod block. |
| `tests/attack/test_hunting_surfer_tick.py` | The float gate wiring. |
| `tests/attack/test_hunting_run_lifecycle.py` | The float accumulator, the band breakdown, the run-record keys. |
| `tests/attack/test_hunting_agent_prompt.py` | The payload shape and the hunter prompt. |
| `tests/project_management/test_hunting_config_api.py` | The float validation and round-trip. |
| `tests/integration/test_settings_deep_merge.py` | The float deep merge. |
| `tests/eval/test_measure_utm.py` | The v5 metric, the v4 raw metric, the impact review. |
| `tests/eval/test_orchestrator_hunting_config.py` | The float setup. |
| `tests/eval/test_orchestrator_trial.py` | The float launch. |
| `tests/hunting_fixtures.py` | The shared fixture builds v5 models and assessments. |

## 10. Documents to converge

| Document | Action |
|---|---|
| `docs/design/impact-assessment-system-spec.md` | Add the 2026-10-31 amendment; point the typed model, invariants, workflow, payload, metric, run record, and migration to the new spec. |
| `docs/design/hunting-67-threat-model-artifact-spec.md` | Add the 2026-10-31 amendment; point the schema, threat entity, risk scoring, payload, and run-record sections to the new spec. |
| `docs/design/hunting-pipeline-sync-spec.md` | Add the amendment for float thresholds and the per-threat queue. |
| `docs/design/hunting-pipeline-sync-adr.md` | Record the float threshold and the queue amendment. |
| `docs/design/unit-threat-model-tools-adr.md` | Add the `assess_impact` binding and the `hunts_store` section removal. |
| `docs/design/unit-threat-model-workbench.md` | Mark the likelihood-only risk recommendation superseded. |
| `docs/design/unit-threat-model-risk-scoring-research.md` | Mark the recommendation superseded; the CVSS 4.0 option is now adopted. |
| `docs/design/threat-model-impact-elicitation-adr.md` | Mark the risk formula superseded. |
| `docs/design/unit-threat-model-spec-impact-map.md` | Add the 2026-10-31 amendment and the impact map link. |
| `src/polymerhus/attack/hunting/CONTEXT.md` | The risk vocabulary block is canonical. |
| `src/polymerhus/project_management/CONTEXT.md` | The float thresholds. |
| `docs/design/domain-model.md` | The hunting entities: the assessment row, the threat, the confidence scope. |
| `docs/design/cvss4-risk-scoring-spec.md` | The authoritative spec. |
| `docs/design/cvss4-risk-scoring-impact-map.md` | This map. |

## 11. Migration and rollout

1. Expand: add the risk module and the v5 schema beside the v4 schema. The store reads both; the writer still accepts v4.
2. Add the tool and the store method. The tool writes v5 rows; the `hunts_store` section stays for one release.
3. Switch the modeller prompt and the tool surface. The pass writes v5 models.
4. Switch the store normalisation, the threat files, the prior-art paths, and the v4 raw read.
5. Switch the payload and the hunter prompt.
6. Switch the queue and the run lifecycle.
7. Switch the settings surface.
8. Switch the eval metric and the assessment prompt.
9. Contract: delete the likelihood and impact code, the old tests, and the `hunts_store` section.

The v4 artifacts stay read-only throughout.
The iteration D evidence is not re-scored.

## 12. Out of scope

- The pod and triager verdict, persistence, and export-flush workstream.
- The recon and Steel crawl.
- The CVSS threat, environmental, and supplemental metrics.
- A FIRST validation pass.
- The frontend.
- The `threat_model_scope` fence.
