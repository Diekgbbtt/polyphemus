# Report: the L0/L1 pipeline split

Status: done (2026-10-14).
Trunk: `rollback/l0-trunk` at `05fe5fa` (the L0-chunk-sourced pipeline).
Experiment: `exp/service-sourced` at `097211e` (the service-sourced pipeline, all fixes).
Plan: `docs/design/l0-l1-pipeline-split-plan.md`.
ADR: `docs/design/l0-l1-pipeline-split-adr.md`.

## 1. What changed

The trunk was built by a splice at the analysis package, not a history rewrite.
The trunk starts from `dev` (`097211e`) and swaps `src/polymerhus/analysis/` plus `recon/control/pipeline.py` for the pre-service-sourced (`93d213e`) L0 code.
The ten service-sourced modules and the `service_sourced` mode are removed.
The non-analysis subsystems stay at their newest `dev` state.
The shared analysis churn is re-applied on top.

## 2. Where each changed component lands

| Component | Origin | Pipeline | Lands in |
|---|---|---|---|
| `analysis/service_sourced.py` | `51d6042` | service-sourced | exp |
| `analysis/service_slice.py` | `60d45b8` | service-sourced | exp |
| `analysis/graph_tools.py` | `88dc902` | service-sourced | exp |
| `analysis/memory.py` | `bbf8a80` | service-sourced | exp |
| `analysis/reasoning_workflow.py` | `ab99d30` | service-sourced | exp |
| `analysis/prompt_variant.py` | `dc994b0` | service-sourced | exp |
| `prompts/*-batched-l1unit-first.md` | `dc994b0`+ | service-sourced | exp |
| `assigner.WORKFLOW` / `_unit_context_block` / `surface_block` | `ab99d30`/`dd8d376`/`aecac71` | service-sourced | exp |
| `assigner.WORKFLOW_LEGACY` (T5 guard) | `af5fb84` | service-sourced | exp |
| `feed.resolve_analysis_mode` / `resolve_analysis_pass_fn` / `ANALYSIS_MODES` | `51d6042` | service-sourced | exp |
| `supervisor.PassCensus` service-sourced fields | `51d6042` | service-sourced | exp |
| `l0_stream.read_surface_sites` | `3ba4fb2` | service-sourced | exp |
| `eval` `--analysis-mode` / `TrialConfig.analysis_mode` | `0dd64f7` | service-sourced | exp |
| `app/llm/checkpoints` `AnalysisTurn` allow-list entry | `3f2041f` | service-sourced | exp |
| `assigner.assign` one-shot body | `93d213e` (arm A) | L0-chunk | dev |
| `mechanism_typist` / `data_modeller` one-shot bodies | `93d213e` | L0-chunk | dev |
| `feed` streamed schedule / `supervisor` chunk-major schedule | `93d213e` | L0-chunk | dev |
| `analysis/CONTEXT.md` (L0 proposer terms) | pre-`3547a3d` | shared | both |
| `app/memory/*` | `99ba10a` | shared (hunting) | both |
| `analysis/proposer_turn.py` (stateful seam) | shared; `96f7787` | shared | both |
| `kali/http_history/*` | `15c2aed` | shared | both |
| `app/llm/sync.py`, `gateway/*` | `5e30332` | shared | both |
| `project_management/api.py` (stop-project) | `fe7593e` | shared | both |
| `feed.resolve_hunt_after_analysis`, `lifecycle._chain_hunting_on_drained` | `55054aa` | shared | both |
| `scaffold.parse_overview`, `l1_inventory.application_overview`, `bootstrapper.md` | `63334d2` | shared | both |
| `pod.overview_block` + the three proposer prepends | new (W-d re-apply) | shared | both |
| `eval/` shared churn (jumper removal, trial drives analysis) | `c97750a`/`55054aa`/`fe7593e` | shared | both |
| batched-L1-unit-first design docs | `3547a3d`+ | service-sourced | exp (retained as records) |

## 3. Design diagnoses

### D-1 Tool surface: does the assigner need `graph_view`?

REVISED 2026-10-14 after the httpx:0 forensics (this section's first version is
retained below as the superseded reading). The evidence overturns the verdict
but keeps one of its premises - see the assessment.

**The forensics.** The httpx:0 assigner session
(`a1c1f6ea-fe80-4d8e-ae83-0dd73bcf69c8:httpx_0:assigner`, 08:58:17-09:06:27Z,
`opencode-go/deepseek-v4-flash`) ran a 21-turn loop: 9 `graph_view` calls, 63
`search_http_history` calls, 7 `notes` calls, input tokens growing 7.6k to
205k (~1.9M input tokens total, ~8 minutes) for ONE chunk whose admitted slice
was a single endpoint (`GET /`, the ComfyUI front page).

**Proposal quality: 37/37 correct.** Every proposed endpoint exists verbatim in
the project graph (290 endpoints, verified against Neo4j - zero
hallucinations); every slug is a real inventory Service; every pairing is
contract-correct by inspection (`/object_info` to node-registry, `/prompt` +
`/queue` + `/free` to workflow-submission, `/upload/image` + `/upload/mask` to
image-upload, `/cloud/login` + `/signup` + `/forgot-password` to sign-in +
register + password-recovery, and so on). Each carries a path segment, a quoted
contract clause, an HTTP artifact id, and where relevant a prior note witness.
The two root-`/` judgments were correctly WITHHELD at 0.3-0.35; the speculative
tail (`/internal`, trailing-slash variants, an EXPR-templated path) is honestly
scored 0.5-0.65. `out_of_inventory` was 0 - no invented slugs.

**Thought-process coherence: exemplary.** The nine graph queries are the sound
discovery sequence (BaseURLs, full endpoint+parameter enumeration, existing
`AGGREGATES`, orphan check, static/non-static split). The model recorded
surface claims before judging ownership, consulted the notes priors (quoting
back "path existence is not route existence"), retried the flaky history store,
and ran the candidate-owner differential endpoint by endpoint. The reasoning is
the strongest part of the run.

**The real defect: scope mismatch by design, plus silent loss.** The workflow
prompt MANDATES project-wide enumeration ("BROAD L0 SCAN - ... enumerate the L0
`Endpoint`s this target exposes") while `resolve_l0_refs` resolves
chunk-locally, so all 37 correct proposals died as `unresolvable`. The model
obeyed its work order; the pipeline contradicts itself. And the backlog is
carried but NOT transported (#34 D6), so the 37 edges are lost entirely - the
run paid ~1.9M tokens and banked nothing. Contrast katana:0 (9 turns, no
history probes, 0 proposals): per-chunk agentic yield is high-variance on top
of being expensive, and the trial later drowned in provider 429s.

**The coupling answer: yes, but split by level.** The evidence supports a
once-per-run project census (graph enumeration + history sampling, cached as
the shared surface dump) feeding a per-chunk one-shot that judges only its
slice against census + inventory - with correct out-of-chunk proposals
TRANSPORTED (backlog or a project-close assignment pass), never dropped. The
graph query capability earns its keep at the census level; per-chunk roaming is
the cost sink. What D-1 got right stands: the per-chunk turn must not roam the
project. What it got wrong is retracted: the 37 were not graph_view
misfiring, they were the pipeline discarding its own best work.

SUPERSEDED first reading: "the graph-capable assigner produced httpx:0 37
proposed / 0 kept / 37 unresolvable; katana:0 0 proposed. Zero kept, versus arm
A's 41 placed / 290. So on L0 the assigner does not bind graph_view." The kept
count measured the gate, not the proposals - a hasty generalisation from a
downstream zero.

### D-2 CoT drift

The verbatims that drive each proposer's chain of thought are L0-appropriate on the trunk (`proposer_reasoning.cot_scaffold` plus each role's prompt file).
The service-sourced sub-problem prompts (which drove the unit-first chains) moved to `exp/service-sourced` with `reasoning_workflow.py`.
The split is therefore the fix: the two pipelines no longer share one set of CoT verbatims.

### D-3 L1 domain prose

The `operator_kb` Overview is a shared skeleton attribute.
It is parsed (`scaffold.parse_overview`), persisted (`settings.application_overview`), surfaced (`read_l1_inventory`), and now prepended to each L0 proposer's human message through `pod.overview_block`.
The service-sourced experiment prepends it in its unit contexts.

## 4. Verification

- `tests/analysis` 323 passed.
- `tests/integration` 328 passed, 9 failed (env/drift: 5 arjun pre-existing, 3 live `assigner_eval_live`, 1 live `llm_sync`), 85 skipped.
- `tests/eval` + `tests/app` 988 passed.
- The analysis contract tier (`test_assigner_contracts`, `test_mechanism_typist_contracts`) is green after the stale-stub repair.

## 5. Known drift (work items)

- `tests/e2e/test_compaction_walkthrough.py::test_mechanism_typist_chained_lane_compacts_e2e` assumes one session across chunks; the proposer-cache experiment (`93d213e`) scopes each chunk to its own batch session.
- The 5 `test_arjun_consumption_contracts` failures and the live `assigner_eval_live` / `llm_sync_key_rotation` failures are unchanged from `dev`.
- The batched-L1-unit-first design docs remain on the trunk as records even though their code is experiment-only.
