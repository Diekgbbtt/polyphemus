# Plan: two comfyui analysis-only trials and their measurement

Status: active, written 2026-10-12 on `dev` at `c97750a`.
Authority: the operator directive of 2026-10-12 - execute two eval trials and measure, then stop the eval pipeline.
Scope: one baseline trial on the current version, one trial on a tuned configuration, and a comparative measurement of both.

## Objective

Run the comfyui analysis-only pipeline twice against the same target and ground truth:

1. **Trial 1 (baseline)** - the current version `c97750a`, with the eval instance's present environment.
2. **Trial 2 (tuned)** - the same version with a tuned per-proposer compaction configuration.

Measure both against the C1-C6 criteria in
`docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`,
comparatively against the incumbent arms A/B/C.
Stop the eval pipeline after both trials.

The operator authorized bypassing blocking conditions: a trial that fails functionally or caps at the 4,000,000 token budget is still a trial and is measured.

## Baseline

The comparison document holds three arms on the comfyui target:

- **A** - streamed L0-batch-first (incumbent).
- **B** - batched analysis-unit-first (`service_sourced` v1).
- **C** - enriched analysis-unit-first (`service_sourced` v2).

All three capture 14 of 14 ground-truth Services; the incumbent A wins C1/C2/C4.
The `dev` work since arm C lands W-a (HTTP-history capture integrity), W-b (assigner absent-surface degradation), W-c (surface-gap finding), and W-d (operator-KB Overview attribute).

## The two configurations

### Trial 1 - current configuration

- `eval_sha`: `c97750a` (the instance worktree advanced to it).
- Analysis mode: `service_sourced`.
- Prompt variant: `batched_l1unit_first` (the default).
- Per-unit statefulness: already the lifecycle - each Service runs on `AnalysisSession(run, role, batch=<service-slug>)`, so the context refreshes per unit and episodic memory rides the `notes` store. No change.
- Compaction: the instance environment sets the global `LLM_COMPACTION_THRESHOLD=0.2`, which overrides every role's declared default (resolution order: per-role env > global env > role default).
- Recon jobs: the full default plan (the same set the arm runs used), no `--jobs` subset.

### Trial 2 - tuned configuration

The one configuration delta is the per-proposer compaction threshold, set through the per-role env vars so they win over the global `0.2`:

- `LLM_COMPACTION_THRESHOLD_MECHANISM_TYPIST=0.08` (the mined role default).
- `LLM_COMPACTION_THRESHOLD_DATA_MODELLER=0.016` (the mined role default).
- `LLM_COMPACTION_THRESHOLD_ASSIGNER=0.05` (a small bound; the assigner declares no default).

Rationale: the diagnosed comfyui run showed `mechanism_typist` consuming 3,595,729 capped tokens over 36 calls with **0** cached input.
The global `0.2` let the typist's per-unit context grow far past its mined `0.08` bound, so every turn re-sent a large uncached prefix.
Restoring the per-role bounds compacts earlier and bounds the uncached prefix.

Everything else is identical to trial 1.

## Method

Per trial, driven manually through `eval/ph.py` (the route the diagnosed run took), on the eval host:

1. Advance `/opt/polymerhus-dev/eval/instances/eval-server-1` to the target SHA and recreate the agent container so the code is live.
2. Confirm the comfyui target and the `ph-eval-front` routing are up.
3. `ph.py project create eval-comfyui-1`.
4. `ph.py settings put` with the operator KB, the synthetic seed, `streaming_analysis=true`, `async_analysis_consumer=true`, `analysis_mode=service_sourced`, `hunt_after_analysis=false`.
5. `PYTHONPATH=src python3 eval/scaffold.py <project> --kb <kb>` (the deterministic L1 scaffold).
6. `ph.py recon launch` with the full default plan; poll to terminal, running the OPERATOR.md section 1.3 monitoring loop and recording every remediation.
7. Poll the analysis run to terminal.
8. Capture `GET /projects/{id}/usage` (per-agent capped tokens and cache spectrum), the graph (`ph.py graph get`), and the Langfuse session transcript for C6.
9. Measure C1-C6 and write the arm into the comparison document.

Feedback loop per trial: every poll reads the state and classifies it (F1-F7); the smallest-blast-radius remediation is applied (R1-R8); every remediation is recorded.

## Measurement

- **C1** service-to-surface aggregation, **C2** System anchoring, **C3** ground-truth breadth and depth: Cypher over the project graph (the queries in the comparison document's appendix).
- **C4** cache spectrum: the usage ledger's per-agent spectrum.
- **C5** L1 surface structure and L0 grounding: the appendix Cypher.
- **C6** proposer trajectory fidelity: the Langfuse trace and session transcript, five axes per proposer.

Each arm's row is added to the comparison document with the same metrics, so the runs stay comparable.

## Stop

After both trials are measured, stop the eval pipeline: stop any live run, then tear down the comfyui target and its routing. Preserve the instance worktree and data root.

## Sequence

1. Trial 1 on `c97750a`; measure; write the arm row.
2. Set the per-role compaction env vars; recreate the agent; trial 2; measure; write the arm row.
3. Stop the eval pipeline.

## Outcome (2026-10-13)

Both trials ran and were measured.

- **Trial 1 (arm D)** - project `98fb2d02`, capped at 4,583,885 tokens, analysis `stopped` gracefully.
  It placed 70 endpoints (24.1%) against arm C's 21 (7.2%) and reached 100% ground-truth Service aggregation, so the W-a..W-d fixes recovered most of the placement loss.
- **Trial 2 (arm E)** - project `d4a13619`, capped at 4,432,847 tokens, analysis `stopped` gracefully.
  The tuned per-proposer thresholds regressed quality (29 aggregates, 10.0% placement, 0 DataItems) and cache hygiene (76.2% cached against 87.8%) for a marginal cost saving, driven by compaction churn (8 `consecutive-pass cap` warnings against 0).

**Decision: reject the per-proposer tuned compaction thresholds; keep the current global `LLM_COMPACTION_THRESHOLD=0.2`.**
The measured cost saving does not offset the quality and cache regressions.
The instance `.env` change was reverted after the trial (`.env.bak-pre-trial2-compaction`).

Remediations recorded:

- R7-class configuration repair: the scaffold venv (`/opt/eval-scaffold-venv`) lacked the app runtime the W-d scaffold now imports (`psycopg`, `langgraph`, the langchain family, `neo4j`, `pydantic`). Installed, and `PYTHONPATH` corrected to `src:.` so the `db` package resolves. The run script's venv provisioning is stale and should be updated.
- The trial was driven manually through `eval/ph.py` (the diagnosed run's route), not the orchestrator `trial` verb, because the trial verb always chains into hunting and the measurement is analysis-only.

The measurement is recorded in `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md` (arms D and E).

