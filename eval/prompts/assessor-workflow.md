# Assessment workflow node

You reach this node through the `eval_monitor` tool, once a trial's execution
has completed successfully (terminal `complete`, or `stopped` at the hunting
cap) and no `verdicts.yaml` exists yet.
This prompt is the node; the subagent it dispatches has its own role prompt at
`eval/prompts/assessment.md`.

## What happens at this node

The monitor dispatches the assessment subagent once, handing it the role prompt,
the trial record, the ground truth, the data root, and the destination
`verdicts.yaml` in the trial directory.
The dispatch is fire-and-forget: the monitor does not block waiting for the
subagent.

## What the tick verifies

On each later tick the monitor reads the destination:

- **present and schema-valid** - every row carries the trial record's `eval_sha`
  and `stack_fingerprint`, and every `identified`/`partial` row carries an
  evidence chain whose paths are relative to the data root, begin with the
  `<project_id>/` segment, and resolve on disk - the node is done and the trial
  moves to the diagnosis node.
- **absent** - the node is `awaiting`; the monitor re-dispatches within its
  bounded count and budget.
- **present but rejected, or absent past the budget** - the node escalates with
  one named failure recorded on the trial record: `empty_file` (no file),
  `schema_invalid` (rejected), or `dispatcher_process` (the command raised).

## What this node does not do

It does not judge, score, or edit `verdicts.yaml`; the assessment subagent is
the sole writer.
It does not assess a failed run: a trial whose execution is `deferred` never
reaches this node.
It drives the node to a present file or a named escalation, then hands the
trial to the diagnosis node.
