# Audit plan: white-jotter context lifecycle and execution trace

## Status

Plan written before the deep trace audit.
Surface 1 and surface 2 are executed in order.
Each finding must be backed by at least two independent records: the durable app log, the Langfuse trace, or the project data root.
A signal that contradicts another source is recorded as a contradiction, never smoothed over.

## Progress

- [x] S1.1 Establish the configured window.
- [x] S1.2 Quantify growth from the durable compaction ledger.
- [x] S1.3 Quantify step jumps from Langfuse.
- [x] S1.4 Attribute jumps to tool calls.
- [x] S1.5 Inspect the tool data contracts and prompts.
- [x] S1.6 Cluster and diagnose.
- [x] S1.7 Write the surface 1 report.
- [x] S2.1 Read the official trial record.
- [x] S2.2 Audit the hunting artifacts.
- [x] S2.3 Audit the execution traces.
- [x] S2.4 Distinguish cap-stop effects from defects.
- [x] S2.5 Write the surface 2 report.

Surface 1 and surface 2 are complete.
The reports are `CONTEXT-LIFECYCLE-AUDIT-WHITE-JOTTER.md` and `EXECUTION-STACK-TRACE-AUDIT-WHITE-JOTTER.md`.

## Scope and assumptions

- The audited trial is the successful 7M white-jotter trial `white-jotter-1-20261022T030303-1618c524`, project `4786aefc-c3fd-46c1-a2ab-45b05cc38e25`, run `5c9590ff-9a83-4cea-9aff-be1bd51e2667`.
- The two failed white-jotter validation attempts are not the audit target. They are cited only where they explain a live defect.
- "Hunter agents" means the hunting subsystem: `hunting_threat_modeller`, `hunting_hunter`, `pod_runner`, and `pod_triager`.
  The analysis roles (`job_orchestrator`, `triager`, `assigner`, `mechanism_typist`) are included as a comparison because they share the same compaction machinery.
- The two observation surfaces are:
  1. **Context lifecycle**: how each session's context grows, when compaction interposes, and what causes vertical jumps.
  2. **Execution stack trace**: whether the hunting execution had functional failures, degraded agents, stale non-terminal artifacts, or mover defects.
- Reports go in `docs/experiments/unit-threat-model-eval-2026-10-20/`.

## Surface 1 - context lifecycle

### S1.1 Establish the configured window

- Read the compaction window, threshold, and wiring in code.
- Read the instance `.env` compaction overrides.
- Read the app log to confirm the runtime budget each role actually used.
- Output: a table of role, context limit, threshold, budget, and whether the role has compaction middleware.

### S1.2 Quantify growth from the durable compaction ledger

- Parse every `compaction ledger` line from the app log.
- Per thread: first and last occupancy, maximum occupancy, maximum positive delta, over-budget count.
- Identify every over-budget event and every `spawned` / `applied` / `failed` / `escalated` compaction event.
- Output: per-session growth table and a compaction-event timeline.

### S1.3 Quantify step jumps from Langfuse

- Group the generation observations by session.
- Compute total input tokens per generation (uncached + cache read).
- Compute the positive input-token delta between consecutive generations in a session.
- Rank sessions by maximum delta and by total tokens.
- Output: per-session jump table, with the jump time and trace id.

### S1.4 Attribute jumps to tool calls

- For the sessions with the largest jumps, fetch the generation outputs (small) and identify the tool call that precedes each jump.
- Match each jump to the tool name and argument size.
- Where the tool result is visible, measure its size. Where it is truncated, use the usage delta as the lower bound and say so.
- Output: jump-to-tool table.

### S1.5 Inspect the tool data contracts and prompts

- Read each implicated tool implementation and its system-prompt instruction.
- Record whether the response is bounded, paginated, summarised, or raw.
- Record whether the prompt tells the agent how to use the tool without flooding context.
- Output: tool contract table with the exact file and line references.

### S1.6 Cluster and diagnose

- Cluster the observed defects into failure-mode families.
- For each family, run the `/diagnosing-bugs` loop in a brief form:
  - symptom and evidence;
  - 3-5 ranked hypotheses;
  - the one probe that distinguishes them;
  - the upstream root cause and the failure chain;
  - the fix at the tool contract and prompt level.
- Output: a diagnosis section per family, with evidence citations.

### S1.7 Write the report

- File: `CONTEXT-LIFECYCLE-AUDIT-WHITE-JOTTER.md`.
- Include the per-role configuration table, the growth table, the jump table, the tool contract table, the clusters, and the diagnoses.
- State explicitly which findings are proven and which are inferred from a truncated trace.

## Surface 2 - execution stack trace and artifacts

### S2.1 Read the official trial record

- Read `trial.yaml`, `metrics.yaml`, and the terminal state.
- Extract the phase timings, stop reason, and the evidence pointers.

### S2.2 Audit the hunting artifacts

- Walk the project data root: hunts, loops, specs, pods, moves, consumed and produced stores.
- Build a status inventory.
- Find every artifact still in a non-terminal status, especially `hypothesised`.
- Classify each stale artifact as expected cap-stop leftover or functional defect.
- Check move records for missing, duplicated, or orphaned transitions.

### S2.3 Audit the execution traces

- Query Langfuse for error levels, tool errors, retries, and abnormal terminations in the pod runner and pod triager.
- Look for hunters that ended without a terminal write, loops that never completed, and pods that degraded to technical infeasibility.
- Check the app log for provider failures, compaction failures, mover errors, and state-store errors.
- Output: a functional-failure inventory with timestamps and evidence.

### S2.4 Distinguish cap-stop effects from defects

- For every stale artifact or degraded state, check whether it started after the cap-stop signal.
- If it started before the stop and never reached a terminal state, treat it as a functional defect.
- If it started after the stop or was cut by the stop, treat it as an expected leftover.
- Output: a classification table with the cut-off time and the reason.

### S2.5 Write the report

- File: `EXECUTION-STACK-TRACE-AUDIT-WHITE-JOTTER.md`.
- Include the artifact inventory, the stale-artifact classification, the functional-failure inventory, and the mover assessment.

## Feedback loops

- After S1.2, cross-check one over-budget event against the Langfuse generation at the same timestamp.
- After S1.3, cross-check the largest jump against the ledger delta at the same thread and minute.
- After S1.4, cross-check the tool name against the tool implementation and the prompt.
- After S2.2, cross-check every stale artifact against the trial stop time and the app log.
- After S2.3, cross-check every degraded pod against the pod export and the Langfuse trace.
- If a check fails, stop and record the contradiction before continuing.

## Deliverables

1. This plan.
2. `CONTEXT-LIFECYCLE-AUDIT-WHITE-JOTTER.md`.
3. `EXECUTION-STACK-TRACE-AUDIT-WHITE-JOTTER.md`.
4. A short summary in the conversation with the ranked root causes and the report paths.

## Acceptance

- Every root cause names a concrete file, setting, or data contract.
- Every quantitative claim has a source path and a time window.
- Every stale artifact is classified against the cap-stop time.
- Every proposed fix names the tool or prompt it changes.
- No source is treated as authoritative without a cross-check.
